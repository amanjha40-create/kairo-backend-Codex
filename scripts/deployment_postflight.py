"""Read-only ECS postflight gate. No deploy/retry operation is exposed by the CLI.

Call require_postflight(report, evidence_path, rollback) from a rollout controller.
The exclusive evidence file is fsynced before the rollback callback is invoked.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen


class PostflightFailed(RuntimeError):
    def __init__(self, report):
        self.report = report
        super().__init__(report["rollback_trigger_reason"])


def task_record(task):
    """Keep only deployment identity and ENI addresses, never container environment."""
    addresses = sorted({
        detail["value"]
        for attachment in task.get("attachments", [])
        if attachment.get("type") == "ElasticNetworkInterface"
        for detail in attachment.get("details", [])
        if detail.get("name") == "privateIPv4Address"
    })
    return {
        "id": task["taskArn"].rsplit("/", 1)[-1],
        "definition": task["taskDefinitionArn"],
        "deployment_id": task.get("startedBy"),
        "status": task["lastStatus"],
        "group": task.get("group"),
        "addresses": addresses,
    }


def evaluate(snapshot):
    """Evaluate a single observation; never convert a failed observation into a pass."""
    report = {
        "timestamp": datetime.now(UTC).isoformat(),
        "SERVICE": snapshot["service"],
        "TASKS": snapshot["tasks"],
        "TARGET_GROUP": {"current": [], "previous": [], "unknown": []},
        "HTTP": snapshot["http"],
        "ALARMS": snapshot["alarms"],
        "QUEUES": snapshot["queues"],
        "ASSERTIONS": [],
    }

    def check(name, condition, expected, actual, message):
        report["ASSERTIONS"].append({
            "check": name, "status": "PASS" if condition else "FAIL",
            "message": message, "expected": expected, "actual": actual,
        })

    service = snapshot["service"]
    expected = service["expected_definition"]
    deployments = service["deployments"]
    primary = [d for d in deployments if d["status"] == "PRIMARY"]
    primary_id = primary[0]["id"] if len(primary) == 1 else None
    check("service_revision", service["definition"] == expected, expected,
          service["definition"], "Service must use the expected task definition")
    counts = [service[k] for k in ("desired", "running", "pending")]
    check("service_counts", counts == [service["expected_desired"],
                                      service["expected_desired"], 0]
          and service["expected_desired"] > 0,
          [service["expected_desired"], service["expected_desired"], 0], counts,
          "Desired/running counts must match the approved count, with no pending tasks")
    stable = (len(deployments) == len(primary) == 1
              and primary[0]["state"] == "COMPLETED"
              and primary[0]["definition"] == expected)
    check("deployment_stable", stable, "one completed PRIMARY at expected revision",
          deployments, "Current ECS deployment must have completed successfully")
    tasks = [t for t in snapshot["tasks"] if t["group"] == "service:" + service["name"]]
    current = [t for t in tasks if t["definition"] == expected
               and t["deployment_id"] == primary_id and t["status"] == "RUNNING"]
    check("current_task_count", len(current) == service["expected_desired"],
          service["expected_desired"], len(current),
          "Running tasks must belong to the expected PRIMARY generation")
    known_deployments = set(snapshot["known_previous_deployments"])
    previous = [t for t in tasks if t["deployment_id"] in known_deployments
                and t["deployment_id"] != primary_id]
    current_ids = {t["id"] for t in current}
    previous_ids = {t["id"] for t in previous}
    for target in snapshot["targets"]:
        owners = [t for t in tasks if target["id"] in t["addresses"]]
        # Never excuse an unknown/IP-reused target merely because it is draining.
        ids = {t["id"] for t in owners}
        kind = "unknown"
        if ids and ids <= current_ids:
            kind = "current"
        elif ids and ids <= previous_ids:
            kind = "previous"
        report["TARGET_GROUP"][kind].append({**target, "task_ids": sorted(ids)})
    group = report["TARGET_GROUP"]
    expected_keys = {(ip, service["target_port"]) for t in current for ip in t["addresses"]}
    actual_keys = {(t["id"], t["port"]) for t in group["current"]}
    check("current_target_coverage", bool(expected_keys) and expected_keys == actual_keys
          and all(t["addresses"] for t in current) and len(expected_keys) >= len(current),
          sorted(expected_keys), sorted(actual_keys),
          "Every current task must have its expected registered target")
    check("current_targets_healthy", bool(group["current"])
          and all(t["state"] == "healthy" for t in group["current"]),
          "all current targets healthy", group["current"],
          "A retiring target cannot substitute for a healthy current target")
    retiring = {("draining", "Target.DeregistrationInProgress"),
                ("unused", "Target.NotRegistered")}
    check("previous_targets_retiring", all((t["state"], t["reason"]) in retiring
                                          and t["port"] == service["target_port"]
                                          for t in group["previous"]),
          sorted(retiring), group["previous"],
          "Only proven previous-generation targets in normal retirement are tolerated")
    check("target_ownership_known", not group["unknown"], [], group["unknown"],
          "Every registered target must map unambiguously to an observed ECS generation")
    for kind in ("live", "ready"):
        check("http_" + kind, snapshot["http"][kind] == 200, 200, snapshot["http"][kind],
              "Health endpoint must return HTTP 200 without redirect")
    alarms = snapshot["alarms"]
    check("alarms_ok", len(alarms["states"]) == alarms["expected_count"]
          and all(s == "OK" for s in alarms["states"].values()),
          {"count": alarms["expected_count"], "state": "OK"}, alarms["states"],
          "Every expected alarm must exist and be OK")
    queues = snapshot["queues"]
    check("queues_empty", bool(queues["counts"])
          and all(v == 0 for q in queues["counts"].values() for v in q.values()),
          "all queue/DLQ counters zero", queues["counts"], "Queues and DLQ must be empty")
    check("overdue_zero", queues["overdue"] == 0 and queues["overdue_fresh"],
          "fresh Overdue=0", {"value": queues["overdue"], "fresh": queues["overdue_fresh"]},
          "Missing/stale/nonzero Overdue data fails closed")
    check("target_5xx", snapshot["target_5xx"]["observed"] == 0,
          0, snapshot["target_5xx"], "Any observed target 5xx fails postflight")
    for companion in snapshot.get("companions", []):
        check("companion_" + companion["name"], companion["valid"], True, companion,
              "Companion service revision and stable counts must remain unchanged")
    failures = [a for a in report["ASSERTIONS"] if a["status"] == "FAIL"]
    report["passed"] = not failures
    report["rollback_trigger_reason"] = "; ".join(
        a["check"] + ": " + a["message"] for a in failures
    )
    # Freeze a JSON-native snapshot so later rollback/state changes cannot alter it.
    return json.loads(json.dumps(report))


def require_postflight(report, evidence_path, rollback=None):
    """Never overwrite original evidence, including if rollback itself raises."""
    with Path(evidence_path).open("x") as handle:
        json.dump(report, handle, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    if not report["passed"]:
        if rollback is not None:
            rollback()
        raise PostflightFailed(report)
    return report


def collect_ecs(ecs, elb, *, cluster, service_name, expected_definition,
                expected_desired, previous_tasks):
    """Read-only ip-target/Fargate collector; previous_tasks is a pre-update capture.

    Capture RUNNING tasks with task_record BEFORE update_service and preserve them.
    Missing or ambiguous ownership fails closed, rather than accepting arbitrary draining IPs.
    """
    response = ecs.describe_services(cluster=cluster, services=[service_name])
    if response.get("failures") or len(response["services"]) != 1:
        raise ValueError("ecs_service_lookup_failed")
    service = response["services"][0]
    deployments = [{"id": d["id"], "status": d["status"],
                    "definition": d["taskDefinition"], "state": d.get("rolloutState")}
                   for d in service["deployments"]]
    task_arns = []
    for page in ecs.get_paginator("list_tasks").paginate(
        cluster=cluster, serviceName=service_name, desiredStatus="RUNNING"
    ):
        task_arns.extend(page["taskArns"])
    tasks = []
    for offset in range(0, len(task_arns), 100):
        batch = ecs.describe_tasks(cluster=cluster, tasks=task_arns[offset:offset + 100])
        if batch.get("failures"):
            raise ValueError("ecs_task_lookup_failed")
        tasks.extend(task_record(t) for t in batch["tasks"])
    by_id = {t["id"]: t for t in previous_tasks}
    by_id.update({t["id"]: t for t in tasks})
    if len(service["loadBalancers"]) != 1:
        raise ValueError("expected_one_target_group")
    binding = service["loadBalancers"][0]
    group_arn = binding["targetGroupArn"]
    groups = elb.describe_target_groups(TargetGroupArns=[group_arn])["TargetGroups"]
    if len(groups) != 1 or groups[0]["TargetType"] != "ip":
        raise ValueError("expected_ip_target_group")
    targets = elb.describe_target_health(TargetGroupArn=group_arn)["TargetHealthDescriptions"]
    return {
        "service": {"name": service_name, "definition": service["taskDefinition"],
                    "expected_definition": expected_definition,
                    "desired": service["desiredCount"], "running": service["runningCount"],
                    "pending": service["pendingCount"], "expected_desired": expected_desired,
                    "deployments": deployments, "target_port": binding["containerPort"]},
        "tasks": list(by_id.values()),
        "known_previous_deployments": sorted({t["deployment_id"] for t in previous_tasks
                                              if t["deployment_id"]}),
        "targets": [{"id": t["Target"]["Id"], "port": t["Target"]["Port"],
                     "state": t["TargetHealth"]["State"],
                     "reason": t["TargetHealth"].get("Reason")}
                    for t in targets],
    }


def collect_checks(cw, sqs, *, base_url, alarm_names, queue_urls, now=None):
    """Read-only HTTP/CloudWatch/SQS gates; config contains resource IDs, never secrets."""
    now = now or datetime.now(UTC)
    http = {}
    for kind in ("live", "ready"):
        url = base_url.rstrip("/") + "/api/v1/health/" + kind
        try:
            with urlopen(url, timeout=15) as response:
                http[kind] = response.status if response.url == url else "redirect"
        except HTTPError as error:
            http[kind] = error.code
        except Exception as error:
            http[kind] = type(error).__name__
    alarms = cw.describe_alarms(AlarmNames=alarm_names)["MetricAlarms"]
    states = {a["AlarmName"]: a["StateValue"] for a in alarms}
    counts = {}
    for name, url in queue_urls.items():
        attrs = sqs.get_queue_attributes(QueueUrl=url, AttributeNames=[
            "ApproximateNumberOfMessages", "ApproximateNumberOfMessagesNotVisible",
            "ApproximateNumberOfMessagesDelayed",
        ])["Attributes"]
        counts[name] = {k: int(v) for k, v in attrs.items()}
        if len(attrs) != 3:
            raise ValueError("missing_queue_counters")
    metric_results = {}
    for suffix, stat in (("deletion-reconciliation-overdue", "Maximum"),
                         ("Target-5xx-Spike", "Sum")):
        matches = [a for a in alarms if a["AlarmName"].endswith(suffix)]
        if len(matches) != 1:
            raise ValueError("missing_or_ambiguous_health_metric")
        alarm = matches[0]
        points = cw.get_metric_statistics(
            Namespace=alarm["Namespace"], MetricName=alarm["MetricName"],
            Dimensions=alarm.get("Dimensions", []), StartTime=now - timedelta(minutes=15),
            EndTime=now, Period=60, Statistics=[stat],
        )["Datapoints"]
        metric_results[suffix] = points
    overdue = metric_results["deletion-reconciliation-overdue"]
    latest = max(overdue, key=lambda p: p["Timestamp"]) if overdue else None
    errors = metric_results["Target-5xx-Spike"]
    return {
        "http": http, "alarms": {"expected_count": len(alarm_names), "states": states},
        "queues": {"counts": counts, "overdue": latest["Maximum"] if latest else None,
                   "overdue_fresh": bool(latest and timedelta(0) <= now - latest["Timestamp"]
                                         <= timedelta(minutes=15))},
        # No datapoints means no observed errors, not proven zero traffic/errors.
        "target_5xx": {"observed": sum(p["Sum"] for p in errors),
                       "datapoints": len(errors)},
    }


def main():
    parser = argparse.ArgumentParser(description="Offline postflight snapshot evaluation only")
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("evidence", type=Path)
    args = parser.parse_args()
    report = evaluate(json.loads(args.snapshot.read_text()))
    try:
        require_postflight(report, args.evidence)
    except PostflightFailed:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
