# Adding Providers And Services

CloudClaim should be easy to extend, but the bar for adding a service is high:
`available` must mean the hostname is actually claimable through a supported
proof workflow.

## Add A Service To An Existing Provider

Use this checklist for each new service.

1. Confirm claimability

The service must have:

- A stable hostname pattern.
- A provider-side name availability check or an equivalent claim-authoritative
  API.
- A proof-resource creation path that reserves the same hostname.
- A cleanup story, even if cleanup is manual by default.

Do not add services that only have weak DNS/NXDOMAIN checks. Unsupported
hostnames should stay generic `unsupported`.

2. Add classification

Azure service patterns live in:

```text
cloudclaim/clouds/azure/catalog.py
cloudclaim/clouds/azure/services.py
```

AWS service patterns live in:

```text
cloudclaim/clouds/aws/services.py
```

Only claimable services should be classified. If the service is not claimable,
do not add a pattern.

3. Add availability

Add a handler in the provider `availability.py`.

The normalized result should include:

- `registration_status`
- `registration_available`
- provider/check metadata
- checked name and region/location
- raw provider response

Use `available` only when the provider check is claim-authoritative.

4. Add claim logic

Add a handler in the provider `claims.py`.

Rules:

- Check availability before creating resources.
- Do not claim if availability is not exactly `available`.
- Convert create-time "not available" errors into `not_claimed`.
- Treat the claim as hostname reservation proof only unless the handler also
  explicitly deploys and verifies hosted content.
- Keep resources by default.
- Run cleanup only when `--cleanup` is passed.

5. Add CLI service selection

The provider `CLAIMABLE_SERVICES` set should include the new service. The
existing `--services` validation will reject anything outside that set.

6. Add output handling

Provider output should stay compact:

```text
app.azurewebsites.net [available] [azure] [app_service]
name.eastus.cloudapp.azure.com [claimed] [azure] [public_ip_dns_label] [rg:rg-cloudclaim-azure-demo]
cloudclaim-eb-target.us-east-1.elasticbeanstalk.com [claimed] [aws] [elastic_beanstalk] [env:cc-cloudclaim-eb-target]
```

Avoid printing raw cloud API text for normal `not-available` or `unsupported`
results. Show compact API errors only for actual failures.

7. Add tests

Add focused tests for:

- Classification of supported hostnames.
- Non-classification of unsupported hostnames.
- File/direct input loading.
- Availability normalization.
- Claim checks before creation.
- No create call when not available.
- Output formatting.
- JSON output when relevant.
- Unsupported-only input avoiding credential precheck.

Run:

```bash
python3 -B -m unittest discover -s tests
```

## Add A New Cloud Provider

Create a new provider package:

```text
cloudclaim/clouds/<provider>/
  __init__.py
  availability.py
  claims.py
  client.py
  commands.py
  inputs.py
  models.py
  output.py
  services.py
```

The provider package must export a `PROVIDER` object:

```python
from cloudclaim.core.providers import Provider

from .commands import add_provider_parser, dispatch

PROVIDER = Provider("<provider>", "<resource-prefix>", add_provider_parser, dispatch)
```

Register it in:

```text
cloudclaim/clouds/__init__.py
```

Provider commands should support:

- `services`
- `precheck`
- `check`
- `claim`
- `--json`
- `--out`
- `--color` / `--no-color`

## Precheck Requirements

Each provider client should expose a `precheck()` function that returns a
dictionary with:

```python
{
    "ok": True,
    "provider": "<provider>",
    ...
}
```

On failure:

```python
{
    "ok": False,
    "provider": "<provider>",
    "message": "actionable error"
}
```

Commands should run precheck automatically only when claimable targets are
present. Unsupported-only input should not require provider credentials.

## Documentation Updates

For every provider or service addition, update:

- `README.md` for quickstart/support lists.
- `docs/USAGE.md` for command examples and options.
- `docs/ARCHITECTURE.md` only if module boundaries change.
- Tests for the new behavior.

## Review Checklist

Before committing:

```bash
python3 -B -m unittest discover -s tests
git diff --check
```

Confirm:

- No automatic output files are created without `--out`.
- JSON output is only produced with `--json`.
- Human output stays compact and streamed.
- Unsupported hostnames are generic unsupported.
- Created resources are kept unless `--cleanup` is passed.
