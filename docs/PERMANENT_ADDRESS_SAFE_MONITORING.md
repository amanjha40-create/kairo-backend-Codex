# Permanent Address privacy-safe Places telemetry

Audit base: `1c091845106e659e1a99e91379deee1062b3fcbc`. CASE B.
The former forward request marker omitted reverse calls and outcomes. Root
logging enriches records with user/request identifiers, so it must not format
these monitoring events. Raw Geo Places CloudTrail monitoring is superseded.

## Contract

The dedicated `kairo.safe_places` logger writes JSON to the existing stdout
stream, independent of LOG_JSON/LOG_LEVEL. It does not propagate to the root
logger, use request filters, or serialize arbitrary record fields. The formatter
constructs a fresh four-field object, with fixed enumerations:

- event: `permanent_address.places_call`
- environment: `production`, `staging`, `development`, `test`, otherwise `unknown`
- operation: `geocode` or `reverse_geocode`
- outcome: `started`, `succeeded`, `failed`

No addresses, query text, postal codes, coordinates, provider payloads, identities,
document IDs, encrypted targets, ciphertext, key IDs, exceptions or traces are
included. Duration is optional and intentionally omitted for the minimal patch.
The logger is silent before normal application logging startup configuration.

Each SDK invocation emits one started event and one terminal event. Count started
only for request attempts, never both events. Success means the SDK returned,
not that address quality, identity, persistence or verification passed. Failure
means the SDK call raised, without exposing exception text. Client-construction
or input-validation failures before the invocation produce no attempt event.
Crashes can prevent a terminal event; logs are not an exactly-once billing ledger.

No provider contract, retry behavior, policy, schema or API response changes.
Both operations retain total_max_attempts=1. The shared durable monthly request
reservation limit remains `PERMANENT_ADDRESS_MONTHLY_GEOCODE_LIMIT=100` for
forward and reverse requests combined. It is the enforcement mechanism, not logs.
The shared $5 Amazon Location budget remains a service/region cost guardrail.

## Future monitoring (not provisioned)

Existing recorded Production destination: `/ecs/kairo-backend`, us-east-1.
No new bucket, trail, EventBridge rule, log group, IAM or provider test is needed.
Later verify the actual destination and approved SNS ARN before provisioning.

Use fixed namespace `Kairo/PermanentAddressProduction`, no per-user dimensions,
metricValue=1, defaultValue=0, unit Count. For each operation and outcome use:

```text
{ $.event = "permanent_address.places_call" && $.environment = "production" && $.operation = "geocode" && $.outcome = "started" }
```

Substitute only the two allowed operations and three allowed outcomes to form
six fixed metrics: GeocodeAttempts/Succeeded/Failed and
ReverseGeocodeAttempts/Succeeded/Failed. Staging/test/unknown events do not match.
No raw-message extraction or high-cardinality dynamic dimensions.

Proposed alarms, requiring separate AWS approval: failed calls >=1 in five
minutes for either operation; combined attempts >100 in any 24 hours as an
anomaly signal, not a calendar-month enforcement replacement. Use Sum and
missing-data notBreaching because the feature can legitimately be idle/OFF.
Route only to the existing Production operations SNS; no new recipient/topic.
No sensitive log snippets in notifications. Alarm silence is not pipeline health
certification. Metric filters are not retroactive; validate delivery after an
independently approved deployment without inventing provider calls.

AWS syntax reference:
https://docs.aws.amazon.com/AmazonCloudWatch/latest/logs/FilterAndPatternSyntaxForMetricFilters.html
