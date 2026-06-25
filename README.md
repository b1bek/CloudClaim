# CloudClaim

CloudClaim checks dangling cloud hostnames and can create minimal proof
resources for supported services.

## Supported Services

Azure:

- `app_service`
- `public_ip_dns_label`
- `traffic_manager`
- `api_management`
- `blob_storage`
- `static_website_storage`
- `file_storage`
- `queue_storage`
- `table_storage`

AWS:

- `elastic_beanstalk`

## Requirements

- Python 3.11+
- Azure CLI (`az`) for Azure
- AWS CLI (`aws`) for AWS
- `uv` optional

## Credentials

CloudClaim reads your environment and loads `.env` when present. Use
`--env-file <path>` for another file. Do not commit credential files.
Credential files are optional if `az` or `aws` already has usable CLI
credentials.

Azure service principal:

```text
AZURE_CLIENT_ID=<app-id>
AZURE_CLIENT_SECRET=<client-secret>
AZURE_TENANT_ID=<tenant-id>
AZURE_SUBSCRIPTION_ID=<subscription-id>
```

AWS:

```text
AWS_PROFILE=cloudclaim-check
# or
AWS_ACCESS_KEY_ID=<access-key-id>
AWS_SECRET_ACCESS_KEY=<secret-access-key>
AWS_SESSION_TOKEN=<session-token-if-used>
```

See [Usage](docs/USAGE.md) for brief credential creation steps.

## Run

Input files must be `.txt`, one hostname per line.

```bash
uv run cloudclaim azure precheck
uv run cloudclaim azure check targets.txt
uv run cloudclaim azure claim targets.txt

uv run cloudclaim aws precheck
uv run cloudclaim aws check targets.txt
uv run cloudclaim aws claim targets.txt
```

Use `--json` for JSON lines. Use `--out result.json` to write full results.
Resources are kept unless `--cleanup` is passed.

## Docs

- [Usage](docs/USAGE.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Adding Services](docs/ADDING_SERVICES.md)
