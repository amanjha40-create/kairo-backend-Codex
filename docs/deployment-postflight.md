# ECS deployment postflight

## Incident and evidence limit

The temporary Public Passport rollout harness used:

```python
assert targets and all(t['TargetHealth']['State'] == 'healthy' for t in targets)
```

It evaluated every registered ALB target, including previous tasks in the
300-second deregistration window. A subsequent read-only check reproduced the
failure at `health.py:25` with one healthy target and retiring targets reporting
`draining / Target.DeregistrationInProgress`. ECS service completion does not
mean every retiring ALB registration has disappeared.

The original API52 postflight assertion is **not recoverable**: the saved rollout
report retained only `AssertionError`, and the temporary scripts are no longer
on disk. The captured script placed the error after ECS stabilization; this is
not proof that the original failure was the same ALB assertion. Do not rewrite
the historical evidence or present that inference as a confirmed cause.

## Corrected model

`scripts/deployment_postflight.py` is the durable replacement for that temporary
postflight gate, not a product-code change or a deployment command.

- Before `update_service`, capture the existing service's RUNNING tasks with
  `task_record`; preserve that list in the rollout witness.
- After ECS stabilizes, `collect_ecs` uses task-definition ARN **and** PRIMARY
  deployment ID (`startedBy`) to identify the new generation, then maps task ENI
  addresses and the service container port to ALB IP targets.
- Every current task must have its registered, healthy target. Desired/running
  counts must equal the approved positive desired count; pending must be zero;
  the expected revision must be the sole completed PRIMARY deployment.
- Only previously captured generations may have `draining` with
  `Target.DeregistrationInProgress`, or `unused` with `Target.NotRegistered`.
  ALB uses `draining` for deregistration; no invented `deregistering` state is
  accepted. Unknown targets, ambiguous reused IPs, unhealthy current targets,
  missing replacement targets and unhealthy old targets fail closed.
- `collect_checks` retains HTTP 200/no-redirect, expected alarms, empty queues,
  fresh zero Overdue and no observed target 5xx requirements. No 5xx datapoints
  means no observed errors, not proof of zero errors. Companion worker stability
  must be supplied in `companions` from its service read; omit no existing gate.
- This collector intentionally supports the current single-IP-target-group ECS
  deployment shape. Other target types require an explicit supported adapter,
  never a fallback that ignores ownership.

## Rollout-controller integration contract

There is no deploy/retry capability in this module. A future separately approved
rollout controller must use these functions instead of the removed temporary
`health.py` and must not catch `PostflightFailed` and replace it with a generic
exception category:

```python
snapshot = collect_ecs(ecs, elb, cluster=cluster, service_name=service,
                       expected_definition=definition, expected_desired=1,
                       previous_tasks=pre_update_tasks)
snapshot.update(collect_checks(cw, sqs, base_url=base_url,
                               alarm_names=expected_alarm_names,
                               queue_urls=queue_and_dlq))
snapshot['companions'] = companion_service_observations
report = evaluate(snapshot)
require_postflight(report, unique_evidence_path, rollback=rollback_to_baseline)
```

Use bounded SDK timeouts and disable SDK retries in the controller. An observation
or mapping error must stop the rollout, never become a passing snapshot. Do not
rerun the deployment automatically. Pre-update task evidence is mandatory for
allowing old targets to drain; absent evidence fails closed.

`require_postflight` writes JSON with exclusive creation, flushes and fsyncs it
**before** invoking rollback. Reports include SERVICE, TASKS, TARGET_GROUP, HTTP,
ALARMS, QUEUES and every named assertion with expected/actual values, timestamp
and rollback trigger. They contain task/deployment/target identifiers, not
container environment, credentials, document data or application URLs/tokens.
Rollback success or failure cannot overwrite the original evidence. Use a
different file for rollback health. Evidence-write failure prevents the rollback
callback; the controller must escalate that failure without discarding context.

## Offline validation

The CLI evaluates a saved sanitized snapshot only and performs no AWS calls:

```sh
python scripts/deployment_postflight.py snapshot.json unique-report.json
python -m pytest tests/test_deployment_postflight.py --noconftest -q
```

Tests cover the eight requested cases, generation/port coverage, unknown targets,
same-revision redeployments, ownership ambiguity, all health gates, immutable
failure evidence, failing rollback and the read-only collectors. CLI fixture
replays are synthetic, not reconstructed historical AWS evidence. No Staging or
Production lifecycle test is necessary for this harness-only correction.
