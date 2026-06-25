# CloudClaim Agent Guide

Keep changes conservative.

## Rules

- `available` means the provider says the name can be claimed and CloudClaim
  can reserve it.
- Unknown or weakly checked hostnames are generic `unsupported`.
- Classify only services CloudClaim can claim.
- `claim` checks availability before creating resources.
- Unsupported-only input must not require credentials.
- Write files only with `--out`.
- Print JSON only with `--json`.
- Cleanup only with `--cleanup`.
- File input is `.txt` only.
- Do not commit scan data, outputs, cache files, or credentials.
- Do not revert user changes unless explicitly asked.

## Docs

- README is user-facing only: purpose, support, requirements, credentials, run,
  and links.
- Keep maintainer rules in `AGENTS.md`, `docs/ARCHITECTURE.md`, or
  `docs/ADDING_SERVICES.md`, not README.
- Usage examples must match the real CLI.
- Credential policy examples must be complete copyable JSON, not fragments.
- Mention when credential files are optional because cloud CLI auth already
  exists.

## Layout

- Shared helpers: `cloudclaim/core/`
- Provider code: `cloudclaim/clouds/<provider>/`
- Tests: `tests/`
- Docs: `docs/`

Provider files:

- `client.py`: cloud CLI calls and precheck.
- `services.py` or `catalog.py`: claimable hostname patterns.
- `inputs.py`: input parsing.
- `availability.py`: availability checks.
- `claims.py`: proof resource creation.
- `output.py`: output payloads.
- `commands.py`: CLI flow.
- `models.py`: dataclasses.

## Finish

```bash
uv run python -B -m unittest discover -s tests
python3 -B -m unittest discover -s tests
git diff --check
python3 -B -m compileall -q cloudclaim tests
```
