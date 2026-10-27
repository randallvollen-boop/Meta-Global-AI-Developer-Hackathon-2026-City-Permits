# Acceptance evidence

Runtime evidence is written under `evidence/runs/` and is intentionally excluded from Git. Each run directory contains a manifest, individual check results and artifact hashes. The verifier rejects missing references, changed files, secret-shaped fields and a replay represented as live evidence.

Local verification:

```bash
uv run python scripts/verify_evidence.py evidence/runs/deterministic
```

The deterministic run records live-only checks as `blocked`. Only a successful strict-schema provider response recorded by a live run can satisfy live Muse evidence.
