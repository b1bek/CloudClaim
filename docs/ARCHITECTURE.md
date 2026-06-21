# Architecture

CloudClaim is organized around provider modules. Shared code stays in
`cloudclaim/core/`; cloud-specific behavior stays in `cloudclaim/clouds/<name>/`.

## Layout

```text
cloudclaim/
  cli.py
  core/
    output.py
    providers.py
    targets.py
  clouds/
    __init__.py
    azure/
      __init__.py
      availability.py
      catalog.py
      claims.py
      client.py
      commands.py
      inputs.py
      models.py
      output.py
      prerequisites.py
      services.py
    aws/
      __init__.py
      availability.py
      claims.py
      client.py
      commands.py
      inputs.py
      models.py
      output.py
      services.py
tests/
```

## Command Flow

Top-level dispatch:

1. `cloudclaim/cli.py` registers providers from `cloudclaim/clouds/__init__.py`.
2. Each provider exports a `PROVIDER` object from its package `__init__.py`.
3. The provider `commands.py` file owns its parser, subcommands, and execution.

Check flow:

1. `commands.py` loads targets with `inputs.py`.
2. Unsupported-only input skips credential precheck.
3. Claimable input runs provider `precheck`.
4. `availability.py` checks provider-side name availability.
5. `output.py` formats one result line as each target completes.

Claim flow:

1. `commands.py` loads targets and validates `--services`.
2. Claimable input runs provider `precheck`.
3. `claims.py` checks availability before creating anything.
4. `claims.py` creates proof resources only when availability is `available`.
5. Cleanup only runs when `--cleanup` is explicitly provided.

## Provider Module Responsibilities

`client.py`:

- Wraps provider CLIs.
- Normalizes subprocess success/failure.
- Implements credential precheck.
- Does not know about hostname classification.

`services.py` or `catalog.py`:

- Contains claimable hostname patterns.
- Returns typed targets only for claimable services.
- Lets unknown hostnames fall through to generic `unsupported`.

`inputs.py`:

- Handles direct hostnames and supported file formats.
- Accepts `.txt` files only for file input.
- Produces provider targets.
- Includes unsupported direct inputs as generic unsupported targets.
- Does not manually label known-but-unsupported services.

`availability.py`:

- Contains provider-side availability handlers.
- Normalizes availability to `available`, `not_available`, `unsupported`, or
  `error`.
- Must only report `available` for claim-authoritative checks.

`claims.py`:

- Contains proof-resource creation handlers.
- Always checks availability first.
- Converts create-time "not available" failures to `not_claimed`.
- Keeps resources by default.

`output.py`:

- Owns human and JSON payload shape for that provider.
- Keeps human output compact and streamed.
- Avoids verbose provider API errors except for actual failures.

`commands.py`:

- Owns CLI flags and command orchestration for that provider.
- Calls precheck before claimable API work.
- Writes files only when `--out` is explicitly provided.

## Claimable-Only Classification Rule

CloudClaim should not maintain a growing list of unsupported cloud services.
If a service has no claim-authoritative availability check and proof workflow,
do not add a service classifier for it.

Unsupported hostnames should be reported with the generic `unsupported`
service name instead of a known-but-unclaimable service label. This keeps
output simple and prevents false confidence from weak provider checks.

## Shared Core

Keep `cloudclaim/core/` small and provider-neutral:

- `output.py`: terminal formatting and banner helpers.
- `providers.py`: provider registration and dispatch.
- `targets.py`: generic target helpers.

Do not put Azure or AWS service logic in `core/`.

## Tests

Tests live in:

- `tests/test_cloudclaim.py` for Azure and shared behavior.
- `tests/test_aws_cloudclaim.py` for AWS behavior.

Run:

```bash
python3 -B -m unittest discover -s tests
```

Every new service needs tests for classification, input parsing when relevant,
availability normalization, claim behavior, output, and no-credential behavior
for unsupported-only input.
