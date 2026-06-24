# Usage

CloudClaim commands are grouped by cloud provider:

```bash
uv run cloudclaim <provider> <command> [options] <inputs...>
python3 -m cloudclaim <provider> <command> [options] <inputs...>
```

Current providers:

- `azure`
- `aws`

## Prerequisites

- Python 3.11+
- `uv` when using the `uv run cloudclaim ...` workflow
- Azure CLI (`az`) for Azure claimable checks and claims
- AWS CLI (`aws`) for AWS claimable checks and claims

CloudClaim calls provider CLIs through subprocesses. It does not install or
manage cloud CLIs as Python dependencies.

## Precheck

Use precheck to verify that the provider CLI exists, is authenticated, and can
read the active account.

```bash
uv run cloudclaim azure precheck
uv run cloudclaim azure precheck --json

uv run cloudclaim aws precheck
uv run cloudclaim aws precheck --profile default --json

python3 -m cloudclaim azure precheck
python3 -m cloudclaim azure precheck --json

python3 -m cloudclaim aws precheck
python3 -m cloudclaim aws precheck --profile default --json
```

`check` and `claim` automatically run precheck before provider API calls when
at least one claimable target is present. Unsupported-only input does not
require provider credentials.

## List Claimable Services

```bash
uv run cloudclaim azure services
uv run cloudclaim azure services --json

uv run cloudclaim aws services
uv run cloudclaim aws services --json

python3 -m cloudclaim azure services
python3 -m cloudclaim azure services --json

python3 -m cloudclaim aws services
python3 -m cloudclaim aws services --json
```

The service list is the source of truth for claimable service families. A
service should appear here only when CloudClaim has a proof-resource claim
handler for it.

Current Azure claimable services:

- `app_service`
- `public_ip_dns_label`
- `traffic_manager`
- `blob_storage`
- `static_website_storage`
- `file_storage`
- `queue_storage`
- `table_storage`

Current AWS claimable services:

- `elastic_beanstalk`

## Check

Check direct hostnames:

```bash
uv run cloudclaim azure check cc-test-app.azurewebsites.net
uv run cloudclaim azure check cc-test-label.eastus.cloudapp.azure.com
uv run cloudclaim azure check cc-test-tm.trafficmanager.net
uv run cloudclaim aws check cc-test-eb.us-east-1.elasticbeanstalk.com

python3 -m cloudclaim azure check cc-test-app.azurewebsites.net
python3 -m cloudclaim azure check cc-test-label.eastus.cloudapp.azure.com
python3 -m cloudclaim azure check cc-test-tm.trafficmanager.net
python3 -m cloudclaim aws check cc-test-eb.us-east-1.elasticbeanstalk.com
```

Check files:

```bash
uv run cloudclaim azure check targets.txt
uv run cloudclaim aws check targets.txt

python3 -m cloudclaim azure check targets.txt
python3 -m cloudclaim aws check targets.txt
```

`check` output is streamed per target:

```text
cc-test-app.azurewebsites.net [available] [azure] [app_service]
cc-test-tm.trafficmanager.net [available] [azure] [traffic_manager]
cc-test-eb.us-east-1.elasticbeanstalk.com [available] [aws] [elastic_beanstalk]
cc-test-eb-parent.us-west-2.elasticbeanstalk.com [available] [aws] [elastic_beanstalk] [child:child.cc-test-eb-parent.us-west-2.elasticbeanstalk.com]
cc-test-label.eastus.cloudapp.azure.com [not-available] [azure] [public_ip_dns_label]
```

Use JSON lines:

```bash
uv run cloudclaim azure check targets.txt --json
python3 -m cloudclaim azure check targets.txt --json
```

Write full raw results:

```bash
uv run cloudclaim azure check targets.txt --out azure-check.json
python3 -m cloudclaim azure check targets.txt --out azure-check.json
```

## Claim

`claim` always checks availability before creating proof resources. It only
attempts claimable services whose provider-side availability result is
`available`.

CloudClaim only claims/reserves the provider hostname by creating the minimal
proof resource for that service. It does not deploy a complete hosted PoC page,
application, or content response. A working hosted PoC requires additional
provider-specific deployment/configuration after the claim.

```bash
uv run cloudclaim azure claim targets.txt
uv run cloudclaim aws claim targets.txt

python3 -m cloudclaim azure claim targets.txt
python3 -m cloudclaim aws claim targets.txt
```

Claim only selected service families:

```bash
uv run cloudclaim azure claim targets.txt --services app_service,public_ip_dns_label,traffic_manager
uv run cloudclaim aws claim targets.txt --services elastic_beanstalk

python3 -m cloudclaim azure claim targets.txt --services app_service,public_ip_dns_label,traffic_manager
python3 -m cloudclaim aws claim targets.txt --services elastic_beanstalk
```

Keep resources by default:

```bash
uv run cloudclaim azure claim cc-test-label.eastus.cloudapp.azure.com
uv run cloudclaim aws claim cc-test-eb.us-east-1.elasticbeanstalk.com

python3 -m cloudclaim azure claim cc-test-label.eastus.cloudapp.azure.com
python3 -m cloudclaim aws claim cc-test-eb.us-east-1.elasticbeanstalk.com
```

Start cleanup after claim:

```bash
uv run cloudclaim azure claim cc-test-label.eastus.cloudapp.azure.com --cleanup
uv run cloudclaim aws claim cc-test-eb.us-east-1.elasticbeanstalk.com --cleanup

python3 -m cloudclaim azure claim cc-test-label.eastus.cloudapp.azure.com --cleanup
python3 -m cloudclaim aws claim cc-test-eb.us-east-1.elasticbeanstalk.com --cleanup
```

## Input Formats

Direct hostname inputs are accepted:

```text
cc-test-app.azurewebsites.net
cc-test-label.eastus.cloudapp.azure.com
cc-test-tm.trafficmanager.net
ccteststorage.blob.core.windows.net
ccteststorage.web.core.windows.net
cc-test-eb.us-east-1.elasticbeanstalk.com
```

File input is `.txt` only. Each non-empty line is treated as one hostname.
Blank lines and `#` comments are ignored. A first-line header such as
`hostname`, `host`, `targets`, or `hosts` is ignored.

Example:

```text
hostname
cc-test-app.azurewebsites.net
cc-test-label.eastus.cloudapp.azure.com
cc-test-tm.trafficmanager.net
ccteststorage.blob.core.windows.net
ccteststorage.web.core.windows.net
cc-test-eb.us-east-1.elasticbeanstalk.com
```

Existing files with other extensions, such as `.csv`, `.json`, `.jsonl`,
`.list`, or `.hosts`, are rejected. Convert scanner exports to a plain `.txt`
hostname list before using them with CloudClaim.

## Provider Options

Azure:

- `--location auto` is the default fallback.
- `name.region.cloudapp.azure.com` uses the encoded region.
- App Service uses automatic fallback locations unless `--location <region>` is
  provided.
- `--resource-group <name>` controls the resource group for claim resources.

AWS:

- Elastic Beanstalk claim targets use `name.region.elasticbeanstalk.com`.
- Descendant Beanstalk inputs such as
  `child.name.region.elasticbeanstalk.com` are normalized to the parent claim
  target and printed with `[child:<input>]`.
- `--profile <name>` passes an AWS CLI profile.
- `--application-name <name>` controls the Elastic Beanstalk application.
- `--solution-stack-name <name>` overrides automatic Elastic Beanstalk platform
  selection.

## Cleanup

CloudClaim keeps proof resources by default. Manual cleanup examples:

```bash
az group delete -n <resource-group> --yes --no-wait
aws elasticbeanstalk terminate-environment --environment-name <environment> --terminate-resources
```

Use `--cleanup` only when you want CloudClaim to start cleanup automatically.
