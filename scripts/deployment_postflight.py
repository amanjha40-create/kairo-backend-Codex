"""Read-only ECS postflight gate. No deploy/retry operation is exposed by the CLI.

Call require_postflight(report, evidence_path, rollback) from a rollout controller.
The exclusive evidence file is fsynced before the rollback callback is invoked.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen


class PostflightFailed(RuntimeError):
    def __init__(self, report):
        self.report = report
        super().__init__(report["rollback_trigger_reason"])


class RolloutCompletionFailed(RuntimeError):
    def __init__(self, report):
        self.report = report
        super().__init__(report["failure_code"])


class RolloutCompletionTimeout(RolloutCompletionFailed):
    pass


def _write_once(path: Path, value: object) -> None:
    with path.open("x") as handle:
        json.dump(value, handle, indent=2)
        handle.flush()
        os.fsync(handle.fileno())


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


def capture_deployment_identity(service: dict, expected_definition: str) -> str:
    """Capture the exact new PRIMARY generation from update_service output."""
    matching = [
        item
        for item in service.get("deployments", [])
        if item.get("status") == "PRIMARY"
        and item.get("taskDefinition", item.get("definition")) == expected_definition
    ]
    if len(matching) != 1 or not matching[0].get("id"):
        raise ValueError("expected_exact_new_primary_deployment")
    return matching[0]["id"]


def _rollout_observation(
    snapshot: dict,
    *,
    expected_deployment_id: str,
    expected_definition: str,
    expected_desired: int,
    poll_count: int,
    elapsed_seconds: float,
    timeout_seconds: float,
) -> dict:
    """Build a sanitized observation for one exact ECS deployment generation."""
    service = snapshot["service"]
    deployments = service["deployments"]
    matching = [item for item in deployments if item["id"] == expected_deployment_id]
    primary = [item for item in deployments if item["status"] == "PRIMARY"]
    deployment = matching[0] if len(matching) == 1 else None
    primary_matches = (
        deployment is not None
        and len(primary) == 1
        and primary[0]["id"] == expected_deployment_id
        and deployment["definition"] == expected_definition
    )
    counts = {
        "desired": service["desired"],
        "running": service["running"],
        "pending": service["pending"],
    }
    counts_ready = counts == {
        "desired": expected_desired,
        "running": expected_desired,
        "pending": 0,
    }

    service_tasks = [
        item
        for item in snapshot["tasks"]
        if item["group"] == "service:" + service["name"]
    ]
    tasks = [
        item
        for item in service_tasks
        if item["definition"] == expected_definition
        and item["deployment_id"] == expected_deployment_id
        and item["status"] == "RUNNING"
    ]
    target_port = service["target_port"]
    expected_targets = {
        (address, target_port)
        for task in tasks
        for address in task["addresses"]
    }
    current_targets = [
        item
        for item in snapshot["targets"]
        if (item["id"], item["port"]) in expected_targets
    ]
    actual_targets = {(item["id"], item["port"]) for item in current_targets}
    targets_ready = (
        len(tasks) == expected_desired
        and all(task["addresses"] for task in tasks)
        and bool(expected_targets)
        and expected_targets == actual_targets
        and all(item["state"] == "healthy" for item in current_targets)
    )
    rollout_state = deployment.get("state") if deployment else None
    ready = (
        primary_matches
        and counts_ready
        and rollout_state == "COMPLETED"
        and targets_ready
    )
    failure_code = ""
    if deployment is None:
        failure_code = "rollout_deployment_identity_missing"
    elif rollout_state == "FAILED":
        failure_code = "rollout_failed"

    return {
        "timestamp": datetime.now(UTC).isoformat(),
        "passed": ready,
        "failure_code": failure_code,
        "expected": {
            "deployment_id": expected_deployment_id,
            "task_definition": expected_definition,
            "desired": expected_desired,
        },
        "deployment": deployment,
        "primary_deployments": primary,
        "counts": counts,
        "task_ids": sorted(item["id"] for item in tasks),
        "observed_task_ids": sorted(item["id"] for item in service_tasks),
        "targets": [
            {
                "id": item["id"],
                "port": item["port"],
                "state": item["state"],
                "reason": item.get("reason"),
            }
            for item in snapshot["targets"]
        ],
        "current_targets": [
            {
                "id": item["id"],
                "port": item["port"],
                "state": item["state"],
                "reason": item.get("reason"),
            }
            for item in current_targets
        ],
        "elapsed_seconds": round(elapsed_seconds, 3),
        "poll_count": poll_count,
        "timeout_seconds": timeout_seconds,
        "timeout_reason": "",
    }


def wait_for_rollout_completion(
    collect_snapshot: Callable[[], dict],
    *,
    expected_deployment_id: str,
    expected_definition: str,
    expected_desired: int,
    evidence_path: Path,
    rollback: Callable[[], None] | None = None,
    timeout_seconds: float = 600,
    poll_interval_seconds: float = 15,
    clock: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,
) -> dict:
    """Wait for one captured ECS generation before durable postflight.

    A failure report is exclusively created and fsynced before rollback. The
    generic ECS services-stable waiter is intentionally not used because it may
    return before the PRIMARY deployment reports rolloutState=COMPLETED.
    """
    if timeout_seconds <= 0 or poll_interval_seconds <= 0 or expected_desired <= 0:
        raise ValueError("invalid_rollout_wait_configuration")
    started = clock()
    poll_count = 0
    while True:
        poll_count += 1
        elapsed = max(0.0, clock() - started)
        report = _rollout_observation(
            collect_snapshot(),
            expected_deployment_id=expected_deployment_id,
            expected_definition=expected_definition,
            expected_desired=expected_desired,
            poll_count=poll_count,
            elapsed_seconds=elapsed,
            timeout_seconds=timeout_seconds,
        )
        if report["passed"]:
            _write_once(evidence_path, report)
            return report
        if report["failure_code"]:
            _write_once(evidence_path, report)
            if rollback is not None:
                rollback()
            raise RolloutCompletionFailed(report)
        if elapsed >= timeout_seconds:
            report["failure_code"] = "rollout_completion_timeout"
            report["timeout_reason"] = (
                "exact PRIMARY deployment did not reach COMPLETED with healthy "
                "current targets before the bounded deadline"
            )
            _write_once(evidence_path, report)
            if rollback is not None:
                rollback()
            raise RolloutCompletionTimeout(report)
        sleeper(min(poll_interval_seconds, timeout_seconds - elapsed))


def require_rollout_completion_then_postflight(
    collect_rollout_snapshot: Callable[[], dict],
    collect_postflight_snapshot: Callable[[], dict],
    *,
    expected_deployment_id: str,
    expected_definition: str,
    expected_desired: int,
    rollout_evidence_path: Path,
    postflight_evidence_path: Path,
    rollback: Callable[[], None] | None = None,
    timeout_seconds: float = 600,
    poll_interval_seconds: float = 15,
    clock: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,
) -> dict:
    """Run postflight only after the exact new ECS generation is complete."""
    wait_for_rollout_completion(
        collect_rollout_snapshot,
        expected_deployment_id=expected_deployment_id,
        expected_definition=expected_definition,
        expected_desired=expected_desired,
        evidence_path=rollout_evidence_path,
        rollback=rollback,
        timeout_seconds=timeout_seconds,
        poll_interval_seconds=poll_interval_seconds,
        clock=clock,
        sleeper=sleeper,
    )
    report = evaluate(collect_postflight_snapshot())
    return require_postflight(report, postflight_evidence_path, rollback=rollback)


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
    _write_once(Path(evidence_path), report)
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
                    "definition": d["taskDefinition"], "state": d.get("rolloutState"),
                    "reason": d.get("rolloutStateReason")}
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
