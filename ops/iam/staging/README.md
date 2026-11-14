# Staging IAM policies

Version-controlled inline policies in this directory are applied only after the
live policy is compared with the tracked document. Apply an approved policy with:

```sh
aws iam put-role-policy \
  --role-name <role> \
  --policy-name <policy> \
  --policy-document file://<tracked-policy.json>
```

After applying, retrieve the policy, compare its canonical JSON with the tracked
document, and use IAM policy simulation plus a role-backed service preflight.
Production policies must not be applied from this directory.

## Resume replay limits

The approved Nova 2 Lite inference profile may return a model-specific
`ValidationException` stating that token counting is unsupported. The Resume
worker may use its configured request-byte limit only for that exact response.
Authorization, throttling, transport, and all other provider errors must still
fail the job and must not fall back to inference.

For a one-page Staging replay with a USD 0.02 combined provider ceiling, use all
of these controls together:

- `RESUME_MODEL_MAX_REQUEST_BYTES=20500`
- `RESUME_MODEL_MAX_OUTPUT_TOKENS=4200`
- `RESUME_MAX_RETRIES=0`
- one Textract page and one Nova invocation only
- no alternate model or provider fallback

At the prices recorded on 2026-11-14 (Nova 2 Lite: USD 0.00033/1K input tokens
and USD 0.00275/1K output tokens; Textract Detect Document Text: USD 0.0015 per
page), the conservative byte-as-token upper bound is USD 0.019815. Reconfirm
current AWS pricing before every paid replay. These replay controls and IAM
documents are Staging-only and do not define Production permissions.
