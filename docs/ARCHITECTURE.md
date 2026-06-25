# Architecture

Shared code stays in `cloudclaim/core/`. Provider code stays in
`cloudclaim/clouds/<provider>/`.

Provider files:

- `client.py`: cloud CLI calls and precheck.
- `services.py` or `catalog.py`: claimable hostname patterns.
- `inputs.py`: direct and `.txt` input parsing.
- `availability.py`: cloud availability checks.
- `claims.py`: proof resource creation and cleanup.
- `output.py`: human and JSON output.
- `commands.py`: parser and command flow.
- `models.py`: dataclasses.

Rules:

- Only classify services CloudClaim can claim.
- Unsupported-only input must not require credentials.
- `claim` must check availability before create.
- Write files only with `--out`.
- Print JSON only with `--json`.
- Cleanup only with `--cleanup`.
