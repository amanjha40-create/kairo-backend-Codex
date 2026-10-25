import copy
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import Mock

import pytest

from scripts.deployment_postflight import (
    PostflightFailed,
    RolloutCompletionFailed,
    RolloutCompletionTimeout,
    capture_deployment_identity,
    collect_checks,
    collect_ecs,
    evaluate,
    require_postflight,
    require_rollout_completion_then_postflight,
    task_record,
    wait_for_rollout_completion,
)


@pytest.fixture
def snapshot():
    return {
        "service": {
            "name": "api", "definition": "api:52", "expected_definition": "api:52",
            "desired": 1, "running": 1, "pending": 0, "expected_desired": 1,
            "target_port": 8000,
            "deployments": [{"id": "new", "status": "PRIMARY", "state": "COMPLETED",
                             "definition": "api:52"}],
        },
        "tasks": [
            {"id": "current", "definition": "api:52", "deployment_id": "new",
             "status": "RUNNING", "group": "service:api", "addresses": ["192.0.2.2"]},
            {"id": "previous", "definition": "api:51", "deployment_id": "old",
             "status": "STOPPED", "group": "service:api", "addresses": ["192.0.2.1"]},
        ],
        "known_previous_deployments": ["old"],
        "targets": [
            {"id": "192.0.2.2", "port": 8000, "state": "healthy", "reason": None},
            {"id": "192.0.2.1", "port": 8000, "state": "draining",
             "reason": "Target.DeregistrationInProgress"},
        ],
        "http": {"live": 200, "ready": 200},
        "alarms": {"expected_count": 2, "states": {"a": "OK", "b": "OK"}},
        "queues": {"counts": {"queue": {"visible": 0, "inflight": 0, "delayed": 0},
                              "dlq": {"visible": 0, "inflight": 0, "delayed": 0}},
                   "overdue": 0, "overdue_fresh": True},
        "target_5xx": {"observed": 0, "datapoints": 0},
    }


def failed(report):
    return {a["check"] for a in report["ASSERTIONS"] if a["status"] == "FAIL"}


class FakeClock:
    def __init__(self):
        self.value = 0.0

    def __call__(self):
        return self.value

    def sleep(self, seconds):
        self.value += seconds


class SnapshotSequence:
    def __init__(self, values):
        self.values = list(values)
        self.calls = 0

    def __call__(self):
        index = min(self.calls, len(self.values) - 1)
        self.calls += 1
        return copy.deepcopy(self.values[index])


def rollout_snapshot(state="IN_PROGRESS", *, target_state="healthy", old_completed=True):
    deployments = [{
        "id": "new", "status": "PRIMARY", "state": state,
        "definition": "api:54", "reason": None,
    }]
    if old_completed:
        deployments.append({
            "id": "old", "status": "ACTIVE", "state": "COMPLETED",
            "definition": "api:53", "reason": None,
        })
    return {
        "service": {
            "name": "api", "definition": "api:54", "expected_definition": "api:54",
            "desired": 1, "running": 1, "pending": 0, "expected_desired": 1,
            "target_port": 8000, "deployments": deployments,
        },
        "tasks": [
            {"id": "current", "definition": "api:54", "deployment_id": "new",
             "status": "RUNNING", "group": "service:api", "addresses": ["192.0.2.2"]},
            {"id": "previous", "definition": "api:53", "deployment_id": "old",
             "status": "RUNNING", "group": "service:api", "addresses": ["192.0.2.1"]},
        ],
        "known_previous_deployments": ["old"],
        "targets": [
            {"id": "192.0.2.2", "port": 8000,
             "state": target_state, "reason": None},
            {"id": "192.0.2.1", "port": 8000, "state": "draining",
             "reason": "Target.DeregistrationInProgress"},
        ],
    }


def test_a_current_healthy_previous_draining(snapshot):
    report = evaluate(snapshot)
    assert report["passed"]
    assert len(report["TARGET_GROUP"]["previous"]) == 1


def test_b_current_healthy_only(snapshot):
    snapshot["targets"].pop()
    assert evaluate(snapshot)["passed"]


@pytest.mark.parametrize("state", ["unhealthy", "initial", "draining", "unused", "unavailable"])
def test_c_unhealthy_current_never_excused(snapshot, state):
    snapshot["targets"][0]["state"] = state
    assert "current_targets_healthy" in failed(evaluate(snapshot))


def test_d_missing_current_target(snapshot):
    snapshot["targets"].pop(0)
    assert "current_target_coverage" in failed(evaluate(snapshot))


@pytest.mark.parametrize("key,value", [("running", 0), ("pending", 1), ("desired", 0)])
def test_e_service_counts(snapshot, key, value):
    snapshot["service"][key] = value
    assert "service_counts" in failed(evaluate(snapshot))


@pytest.mark.parametrize("endpoint,status", [("live", 500), ("ready", 503),
                                            ("live", "TimeoutError"), ("ready", "redirect")])
def test_f_http_failure(snapshot, endpoint, status):
    snapshot["http"][endpoint] = status
    assert "http_" + endpoint in failed(evaluate(snapshot))


@pytest.mark.parametrize("state", ["ALARM", "INSUFFICIENT_DATA"])
def test_g_alarm_failure(snapshot, state):
    snapshot["alarms"]["states"]["a"] = state
    assert "alarms_ok" in failed(evaluate(snapshot))


def test_h_original_failure_saved_before_rollback(snapshot, tmp_path):
    snapshot["targets"][0].update(state="unhealthy", reason="Target.FailedHealthChecks")
    report = evaluate(snapshot)
    path = tmp_path / "failure.json"

    def rollback():
        saved = json.loads(path.read_text())
        assert saved == report
        assert saved["SERVICE"]["definition"] == "api:52"
        assert saved["TASKS"][0]["id"] == "current"
        assert saved["TARGET_GROUP"]["current"][0]["reason"] == "Target.FailedHealthChecks"
        assert saved["HTTP"] == {"live": 200, "ready": 200}
        assert saved["timestamp"]
        assert "current_targets_healthy" in saved["rollback_trigger_reason"]
        raise RuntimeError("rollback failed")

    with pytest.raises(RuntimeError, match="rollback failed"):
        require_postflight(report, path, rollback)
    assert json.loads(path.read_text()) == report
    with pytest.raises(FileExistsError):
        require_postflight(evaluate(snapshot), path, Mock())


def test_failure_raises_after_successful_rollback(snapshot, tmp_path):
    snapshot["http"]["ready"] = 503
    rollback = Mock()
    with pytest.raises(PostflightFailed, match="http_ready"):
        require_postflight(evaluate(snapshot), tmp_path / "failure.json", rollback)
    rollback.assert_called_once_with()


def test_write_failure_prevents_rollback(snapshot, tmp_path):
    snapshot["http"]["ready"] = 503
    rollback = Mock()
    with pytest.raises(FileNotFoundError):
        require_postflight(evaluate(snapshot), tmp_path / "missing" / "failure.json", rollback)
    rollback.assert_not_called()


def test_success_does_not_rollback(snapshot, tmp_path):
    rollback = Mock()
    require_postflight(evaluate(snapshot), tmp_path / "pass.json", rollback)
    rollback.assert_not_called()


def test_unused_retired_target(snapshot):
    snapshot["targets"][1].update(state="unused", reason="Target.NotRegistered")
    assert evaluate(snapshot)["passed"]


def test_unknown_draining_target_rejected(snapshot):
    snapshot["targets"][1]["id"] = "192.0.2.99"
    assert "target_ownership_known" in failed(evaluate(snapshot))


def test_old_healthy_cannot_mask_current_failure(snapshot):
    snapshot["targets"][0]["state"] = "unhealthy"
    snapshot["targets"][1].update(state="healthy", reason=None)
    assert "current_targets_healthy" in failed(evaluate(snapshot))


def test_same_revision_different_generation(snapshot):
    snapshot["tasks"][1]["definition"] = "api:52"
    assert evaluate(snapshot)["passed"]


def test_one_of_two_current_tasks_missing_eni(snapshot):
    snapshot["service"].update(desired=2, running=2, expected_desired=2)
    task = copy.deepcopy(snapshot["tasks"][0])
    task.update(id="second", addresses=[])
    snapshot["tasks"].append(task)
    assert "current_target_coverage" in failed(evaluate(snapshot))


@pytest.mark.parametrize("target,check", [(0, "current_target_coverage"),
                                          (1, "previous_targets_retiring")])
def test_wrong_target_port(snapshot, target, check):
    snapshot["targets"][target]["port"] = 9999
    assert check in failed(evaluate(snapshot))


def test_wrong_current_generation(snapshot):
    snapshot["tasks"][0]["deployment_id"] = "unknown"
    assert "current_task_count" in failed(evaluate(snapshot))


def test_ip_reuse_ambiguity_rejected(snapshot):
    snapshot["tasks"][1]["addresses"] = ["192.0.2.2"]
    assert "target_ownership_known" in failed(evaluate(snapshot))


@pytest.mark.parametrize("state", ["IN_PROGRESS", "FAILED"])
def test_unstable_deployment(snapshot, state):
    snapshot["service"]["deployments"][0]["state"] = state
    assert "deployment_stable" in failed(evaluate(snapshot))


def test_missing_alarm(snapshot):
    snapshot["alarms"]["states"].pop("b")
    assert "alarms_ok" in failed(evaluate(snapshot))


@pytest.mark.parametrize("queue", ["queue", "dlq"])
def test_queue_nonempty(snapshot, queue):
    snapshot["queues"]["counts"][queue]["visible"] = 1
    assert "queues_empty" in failed(evaluate(snapshot))


@pytest.mark.parametrize("value,fresh", [(1, True), (None, False), (0, False)])
def test_overdue(snapshot, value, fresh):
    snapshot["queues"].update(overdue=value, overdue_fresh=fresh)
    assert "overdue_zero" in failed(evaluate(snapshot))


def test_5xx(snapshot):
    snapshot["target_5xx"] = {"observed": 1, "datapoints": 1}
    assert "target_5xx" in failed(evaluate(snapshot))


def test_repeated_unhealthy_never_passes(snapshot):
    snapshot["targets"][0]["state"] = "unhealthy"
    for _ in range(3):
        assert not evaluate(snapshot)["passed"]


def test_companion_changed(snapshot):
    snapshot["companions"] = [{"name": "worker", "valid": False, "revision": 20}]
    assert "companion_worker" in failed(evaluate(snapshot))


def test_read_only_collector_and_secret_projection(snapshot):
    raw = {"taskArn": "arn/task/current", "taskDefinitionArn": "api:52",
           "startedBy": "new", "lastStatus": "RUNNING", "group": "service:api",
           "overrides": {"secret": "must-not-appear"},
           "attachments": [{"type": "ElasticNetworkInterface", "details": [
               {"name": "privateIPv4Address", "value": "192.0.2.2"}]}]}
    assert "must-not-appear" not in json.dumps(task_record(raw))
    ecs, elb = Mock(), Mock()
    ecs.describe_services.return_value = {"services": [{
        "taskDefinition": "api:52", "desiredCount": 1, "runningCount": 1, "pendingCount": 0,
        "deployments": [{"id": "new", "status": "PRIMARY", "rolloutState": "COMPLETED",
                         "taskDefinition": "api:52"}],
        "loadBalancers": [{"targetGroupArn": "tg", "containerPort": 8000}],
    }]}
    ecs.get_paginator.return_value.paginate.return_value = [{"taskArns": ["arn/task/current"]}]
    ecs.describe_tasks.return_value = {"tasks": [raw]}
    elb.describe_target_groups.return_value = {"TargetGroups": [{"TargetType": "ip"}]}
    elb.describe_target_health.return_value = {"TargetHealthDescriptions": [
        {"Target": {"Id": t["id"], "Port": t["port"]},
         "TargetHealth": {"State": t["state"], "Reason": t["reason"]}}
        for t in snapshot["targets"]]}
    result = collect_ecs(ecs, elb, cluster="fixture", service_name="api",
                         expected_definition="api:52", expected_desired=1,
                         previous_tasks=[copy.deepcopy(snapshot["tasks"][1])])
    assert evaluate({**snapshot, **result})["passed"]
    assert all(c[0].split(".")[0] in {"describe_services", "get_paginator",
                                      "get_paginator()", "describe_tasks"}
               for c in ecs.mock_calls)
    assert all(c[0] in {"describe_target_groups", "describe_target_health"}
               for c in elb.mock_calls)


def test_http_metric_collectors_are_read_only(monkeypatch):
    now = datetime(2026, 10, 24, tzinfo=UTC)
    response = Mock()
    response.status = 200
    urls = []

    def opened(url, timeout):
        assert timeout == 15
        urls.append(url)
        response.url = url
        context = Mock()
        context.__enter__ = Mock(return_value=response)
        context.__exit__ = Mock(return_value=False)
        return context

    monkeypatch.setattr("scripts.deployment_postflight.urlopen", opened)
    cw, sqs = Mock(), Mock()
    names = ["fixture-deletion-reconciliation-overdue", "fixture-Target-5xx-Spike"]
    cw.describe_alarms.return_value = {"MetricAlarms": [
        {"AlarmName": n, "StateValue": "OK", "Namespace": "fixture", "MetricName": n}
        for n in names]}
    cw.get_metric_statistics.side_effect = [
        {"Datapoints": [{"Timestamp": now, "Maximum": 0}]}, {"Datapoints": []}]
    sqs.get_queue_attributes.return_value = {"Attributes": {
        "ApproximateNumberOfMessages": "0", "ApproximateNumberOfMessagesNotVisible": "0",
        "ApproximateNumberOfMessagesDelayed": "0",
    }}
    result = collect_checks(cw, sqs, base_url="https://fixture.invalid", alarm_names=names,
                            queue_urls={"queue": "fixture-q", "dlq": "fixture-dlq"}, now=now)
    assert result["http"] == {"live": 200, "ready": 200}
    assert result["queues"]["overdue_fresh"]
    assert result["target_5xx"] == {"observed": 0, "datapoints": 0}
    assert len(urls) == 2
    assert all(c[0] in {"describe_alarms", "get_metric_statistics"} for c in cw.mock_calls)
    assert all(c[0] == "get_queue_attributes" for c in sqs.mock_calls)


def test_report_is_detached_from_mutating_rollback_state(snapshot):
    report = evaluate(snapshot)
    snapshot["http"]["ready"] = 503
    snapshot["tasks"].clear()
    assert report["HTTP"]["ready"] == 200
    assert len(report["TASKS"]) == 2


@pytest.mark.parametrize("unhealthy", [False, True])
def test_offline_cli_dry_run(snapshot, tmp_path, unhealthy):
    if unhealthy:
        snapshot["targets"][0].update(state="unhealthy", reason="Target.FailedHealthChecks")
    source, output = tmp_path / "snapshot.json", tmp_path / "report.json"
    source.write_text(json.dumps(snapshot))
    command = Path(__file__).parents[1] / "scripts" / "deployment_postflight.py"
    result = subprocess.run([sys.executable, str(command), str(source), str(output)],
                            capture_output=True, text=True, check=False)
    assert result.returncode == int(unhealthy)
    assert json.loads(output.read_text())["passed"] is not unhealthy


def test_rollout_waits_for_in_progress_then_runs_postflight(snapshot, tmp_path):
    clock = FakeClock()
    rollout = SnapshotSequence([
        rollout_snapshot(),
        rollout_snapshot(state="COMPLETED", old_completed=False),
    ])
    postflight = Mock(return_value=snapshot)

    report = require_rollout_completion_then_postflight(
        rollout,
        postflight,
        expected_deployment_id="new",
        expected_definition="api:54",
        expected_desired=1,
        rollout_evidence_path=tmp_path / "rollout.json",
        postflight_evidence_path=tmp_path / "postflight.json",
        timeout_seconds=10,
        poll_interval_seconds=1,
        clock=clock,
        sleeper=clock.sleep,
    )

    assert report["passed"]
    assert rollout.calls == 2
    postflight.assert_called_once_with()
    saved = json.loads((tmp_path / "rollout.json").read_text())
    assert saved["passed"]
    assert saved["deployment"]["state"] == "COMPLETED"
    assert saved["poll_count"] == 2


def test_rollout_does_not_run_postflight_during_multiple_in_progress_polls(
    snapshot, tmp_path,
):
    clock = FakeClock()
    rollout = SnapshotSequence([
        rollout_snapshot(),
        rollout_snapshot(),
        rollout_snapshot(),
        rollout_snapshot(state="COMPLETED", old_completed=False),
    ])
    postflight = Mock(return_value=snapshot)

    require_rollout_completion_then_postflight(
        rollout,
        postflight,
        expected_deployment_id="new",
        expected_definition="api:54",
        expected_desired=1,
        rollout_evidence_path=tmp_path / "rollout.json",
        postflight_evidence_path=tmp_path / "postflight.json",
        timeout_seconds=10,
        poll_interval_seconds=1,
        clock=clock,
        sleeper=clock.sleep,
    )

    assert rollout.calls == 4
    postflight.assert_called_once_with()


def test_failed_rollout_fails_immediately_and_persists_diagnostics(tmp_path):
    clock = FakeClock()
    value = rollout_snapshot(state="FAILED")
    value["service"]["deployments"][0]["reason"] = "fixture deployment failed"
    rollout = SnapshotSequence([value])
    rollback = Mock()
    evidence = tmp_path / "failed.json"

    with pytest.raises(RolloutCompletionFailed, match="rollout_failed"):
        wait_for_rollout_completion(
            rollout,
            expected_deployment_id="new",
            expected_definition="api:54",
            expected_desired=1,
            evidence_path=evidence,
            rollback=rollback,
            timeout_seconds=10,
            poll_interval_seconds=1,
            clock=clock,
            sleeper=clock.sleep,
        )

    saved = json.loads(evidence.read_text())
    assert saved["failure_code"] == "rollout_failed"
    assert saved["deployment"]["reason"] == "fixture deployment failed"
    assert saved["poll_count"] == 1
    assert saved["task_ids"] == ["current"]
    assert saved["current_targets"] == [{
        "id": "192.0.2.2", "port": 8000, "state": "healthy", "reason": None,
    }]
    rollback.assert_called_once_with()


def test_rollout_completion_timeout_is_bounded_and_persisted(tmp_path):
    clock = FakeClock()
    rollout = SnapshotSequence([rollout_snapshot()])
    rollback = Mock()
    evidence = tmp_path / "timeout.json"

    with pytest.raises(RolloutCompletionTimeout, match="rollout_completion_timeout"):
        wait_for_rollout_completion(
            rollout,
            expected_deployment_id="new",
            expected_definition="api:54",
            expected_desired=1,
            evidence_path=evidence,
            rollback=rollback,
            timeout_seconds=2,
            poll_interval_seconds=1,
            clock=clock,
            sleeper=clock.sleep,
        )

    saved = json.loads(evidence.read_text())
    assert saved["failure_code"] == "rollout_completion_timeout"
    assert saved["elapsed_seconds"] == 2
    assert saved["poll_count"] == 3
    assert saved["timeout_reason"]
    rollback.assert_called_once_with()


def test_old_completed_deployment_cannot_satisfy_new_generation(tmp_path):
    clock = FakeClock()
    rollout = SnapshotSequence([
        rollout_snapshot(),
        rollout_snapshot(state="COMPLETED", old_completed=False),
    ])

    result = wait_for_rollout_completion(
        rollout,
        expected_deployment_id="new",
        expected_definition="api:54",
        expected_desired=1,
        evidence_path=tmp_path / "rollout.json",
        timeout_seconds=10,
        poll_interval_seconds=1,
        clock=clock,
        sleeper=clock.sleep,
    )

    assert result["passed"]
    assert result["deployment"]["id"] == "new"
    assert result["poll_count"] == 2
    assert capture_deployment_identity(
        {"deployments": [
            {"id": "new", "status": "PRIMARY", "taskDefinition": "api:54"},
            {"id": "old", "status": "ACTIVE", "taskDefinition": "api:53"},
        ]},
        "api:54",
    ) == "new"


def test_completed_rollout_with_previous_target_draining_passes(snapshot, tmp_path):
    clock = FakeClock()
    result = require_rollout_completion_then_postflight(
        SnapshotSequence([rollout_snapshot(state="COMPLETED")]),
        Mock(return_value=snapshot),
        expected_deployment_id="new",
        expected_definition="api:54",
        expected_desired=1,
        rollout_evidence_path=tmp_path / "rollout.json",
        postflight_evidence_path=tmp_path / "postflight.json",
        timeout_seconds=10,
        poll_interval_seconds=1,
        clock=clock,
        sleeper=clock.sleep,
    )

    assert result["passed"]
    assert len(result["TARGET_GROUP"]["previous"]) == 1


def test_postflight_still_rejects_unhealthy_target_after_completion(snapshot, tmp_path):
    clock = FakeClock()
    snapshot["targets"][0].update(state="unhealthy", reason="Target.FailedHealthChecks")
    rollback = Mock()

    with pytest.raises(PostflightFailed, match="current_targets_healthy"):
        require_rollout_completion_then_postflight(
            SnapshotSequence([rollout_snapshot(state="COMPLETED")]),
            Mock(return_value=snapshot),
            expected_deployment_id="new",
            expected_definition="api:54",
            expected_desired=1,
            rollout_evidence_path=tmp_path / "rollout.json",
            postflight_evidence_path=tmp_path / "postflight.json",
            rollback=rollback,
            timeout_seconds=10,
            poll_interval_seconds=1,
            clock=clock,
            sleeper=clock.sleep,
        )

    assert json.loads((tmp_path / "rollout.json").read_text())["passed"]
    assert not json.loads((tmp_path / "postflight.json").read_text())["passed"]
    rollback.assert_called_once_with()


def test_rollout_failure_evidence_survives_rollback_failure(tmp_path):
    clock = FakeClock()
    evidence = tmp_path / "failed.json"

    def rollback():
        saved = json.loads(evidence.read_text())
        assert saved["failure_code"] == "rollout_failed"
        assert saved["deployment"]["id"] == "new"
        raise RuntimeError("rollback failed")

    with pytest.raises(RuntimeError, match="rollback failed"):
        wait_for_rollout_completion(
            SnapshotSequence([rollout_snapshot(state="FAILED")]),
            expected_deployment_id="new",
            expected_definition="api:54",
            expected_desired=1,
            evidence_path=evidence,
            rollback=rollback,
            timeout_seconds=10,
            poll_interval_seconds=1,
            clock=clock,
            sleeper=clock.sleep,
        )

    assert json.loads(evidence.read_text())["failure_code"] == "rollout_failed"
