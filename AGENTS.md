# CloudClaim Agent Guide

This file is for coding agents and maintainers working in this repository.

## Project Goal

CloudClaim validates claimability for dangling cloud hostnames and can create
benign proof resources for claimable services.

The project must stay conservative:

- `available` means actually claimable through a provider-side check and proof
  workflow.
- Unsupported or weakly checked hostnames are generic `unsupported`.
- Do not add known-but-unclaimable service labels.
- Do not create output files unless the user passes `--out`.
- Do not print JSON unless the user passes `--json`.
- Do not cleanup cloud resources unless the user passes `--cleanup`.
- File input is `.txt` only; direct hostname arguments are still allowed.

## Repository Layout

```text
cloudclaim/
  cli.py
  core/
  clouds/
    azure/
    aws/
pyproject.toml
tests/
docs/
```

Shared helpers belong in `cloudclaim/core/`. Provider-specific code belongs in
`cloudclaim/clouds/<provider>/`.

## Provider Module Boundaries

For each provider:

- `client.py`: CLI subprocess wrapper and credential precheck.
- `services.py` or `catalog.py`: claimable hostname classification only.
- `inputs.py`: direct/file input parsing.
- `availability.py`: provider-side availability checks.
- `claims.py`: proof-resource creation and cleanup flow.
- `output.py`: provider-specific human/JSON output payloads.
- `commands.py`: provider CLI parser and orchestration.
- `models.py`: provider dataclasses.

Do not put provider-specific service logic in `cloudclaim/core/`.

## Claimable-Only Classification

Classifiers must only return real service names for services CloudClaim can
claim with its own proof-resource workflow. Everything else should fall through
to generic unsupported. Do not add a service pattern just because the hostname
is recognizable.

## CLI Behavior Rules

Human output:

- Color by default.
- Stream result lines as targets complete.
- Keep normal `not-available` output short.
- Show compact provider API errors only for actual failures.

JSON:

- Only with `--json`.
- Emit compact JSON lines for per-target output.

Files:

- Only write result files with `--out`.
- Only accept `.txt` files as input files.

Precheck:

- `precheck` commands should validate CLI credentials.
- `check` and `claim` should automatically precheck before claimable provider
  API calls.
- Unsupported-only input should not require credentials.

Cleanup:

- Keep proof resources by default.
- Run cleanup only when `--cleanup` is explicitly passed.

## Adding Services

Before adding a service, confirm:

- The hostname pattern is stable.
- The provider has a claim-authoritative availability check.
- CloudClaim can create a proof resource that reserves the same hostname.
- Tests can verify check-before-create behavior.

Then update provider-local modules and docs. See
`docs/ADDING_SERVICES.md`.

## Testing

Run before finishing changes:

```bash
uv run python -B -m unittest discover -s tests
python3 -B -m unittest discover -s tests
git diff --check
```

Prefer the `uv` command when available. The plain `python3` command is the
fallback.

Add tests for every behavior change. At minimum, service additions need tests
for classification, unsupported fallthrough, availability normalization, claim
flow, output, and no-credential unsupported-only behavior.

## Git And Local Files

Ignored local inputs and generated files include:

- `claim.txt`
- `dangling-dns-record-*.csv`
- `cloudclaim_*.json`
- `*_claims.json`
- `audit-reports/`

Do not commit local scan data, proof outputs, cache files, or credentials.
