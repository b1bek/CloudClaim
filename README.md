# CloudClaim

CloudClaim checks whether dangling cloud hostnames are claimable and can create
minimal proof resources for claimable services.

It is conservative by design: unsupported or unclaimable hostnames are reported
as generic `unsupported`.

## Quick Start

Prerequisites:

- Python 3.11+
- `uv`
- Azure CLI (`az`) for Azure checks/claims
- AWS CLI (`aws`) for AWS checks/claims

```bash
uv run cloudclaim azure precheck
uv run cloudclaim aws precheck --profile default

uv run cloudclaim azure check targets.txt
uv run cloudclaim aws check targets.txt --profile default

uv run cloudclaim azure claim targets.txt
uv run cloudclaim aws claim targets.txt --profile default
```

Input files must be `.txt`, one hostname per line. Direct hostname arguments
also work.

CloudClaim claims only reserve the provider hostname with a minimal proof
resource. They do not deploy a complete hosted PoC page, application, or content
response; do provider-specific deployment/configuration after the claim if you
need that.

Resources are kept by default. Use `--cleanup` only when you want CloudClaim to
start cleanup automatically.

## Claimable Services

Azure:

- `app_service`
- `public_ip_dns_label`
- `traffic_manager`
- `blob_storage`
- `static_website_storage`
- `file_storage`
- `queue_storage`
- `table_storage`

AWS:

- `elastic_beanstalk` (`name.region.elasticbeanstalk.com`; descendant labels
  normalize to this parent CNAME)

## Output

Human output streams compact tagged lines:

```text
cc-test-label.eastus.cloudapp.azure.com [available] [azure] [public_ip_dns_label]
cc-test-tm.trafficmanager.net [available] [azure] [traffic_manager]
cc-test-eb.us-east-1.elasticbeanstalk.com [not-available] [aws] [elastic_beanstalk]
cc-test-eb-parent.us-west-2.elasticbeanstalk.com [available] [aws] [elastic_beanstalk] [child:child.cc-test-eb-parent.us-west-2.elasticbeanstalk.com]
```

Use `--json` for JSON lines and `--out result.json` only when you want a full
result file.

## Docs

- [Usage](docs/USAGE.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Adding Providers And Services](docs/ADDING_SERVICES.md)
- [Agent Guide](AGENTS.md)

## Development

```bash
uv run python -B -m unittest discover -s tests
```
