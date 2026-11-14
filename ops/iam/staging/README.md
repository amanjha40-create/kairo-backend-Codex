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
