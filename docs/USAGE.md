# Usage

## Commands

```bash
uv run cloudclaim <provider> <command> [inputs...]
python3 -m cloudclaim <provider> <command> [inputs...]
```

Providers: `azure`, `aws`.

Commands:

- `services`: list supported services.
- `precheck`: verify CLI credentials.
- `check`: check claimability.
- `claim`: create proof resources for available targets.

Examples:

```bash
uv run cloudclaim azure check targets.txt
uv run cloudclaim aws check targets.txt
uv run cloudclaim azure claim targets.txt
uv run cloudclaim aws claim targets.txt
```

## Input

Only direct hostnames and `.txt` files are accepted. `.txt` files use one
hostname per line. Blank lines, `#` comments, and a first-line `hostname`
header are ignored.

## Credential Files

CloudClaim reads the current environment and loads `.env` when present. Use
`--env-file <path>` to load another file.
Credential files are optional if `az` or `aws` already has usable CLI
credentials.

Azure:

```text
AZURE_CLIENT_ID=<app-id>
AZURE_CLIENT_SECRET=<client-secret>
AZURE_TENANT_ID=<tenant-id>
AZURE_SUBSCRIPTION_ID=<subscription-id>
```

AWS:

```text
AWS_PROFILE=cloudclaim-check
# or access keys:
AWS_ACCESS_KEY_ID=<access-key-id>
AWS_SECRET_ACCESS_KEY=<secret-access-key>
AWS_SESSION_TOKEN=<session-token-if-used>
```

## Create Credentials

Use separate check and claim credentials when possible.

Azure check role file:

```json
{
  "Name": "CloudClaim Check",
  "IsCustom": true,
  "Description": "CloudClaim check permissions.",
  "Actions": [
    "Microsoft.Web/checknameavailability/action",
    "Microsoft.Network/locations/checkDnsNameAvailability/action",
    "Microsoft.Network/checkTrafficManagerNameAvailabilityV2/action",
    "Microsoft.ApiManagement/checkNameAvailability/action",
    "Microsoft.Storage/checkNameAvailability/action"
  ],
  "NotActions": [],
  "AssignableScopes": ["/subscriptions/<subscription-id>"]
}
```

Azure claim role file:

```json
{
  "Name": "CloudClaim Claim",
  "IsCustom": true,
  "Description": "CloudClaim check and claim permissions.",
  "Actions": [
    "Microsoft.Web/checknameavailability/action",
    "Microsoft.Network/locations/checkDnsNameAvailability/action",
    "Microsoft.Network/checkTrafficManagerNameAvailabilityV2/action",
    "Microsoft.ApiManagement/checkNameAvailability/action",
    "Microsoft.Storage/checkNameAvailability/action",
    "Microsoft.Resources/subscriptions/resourceGroups/read",
    "Microsoft.Resources/subscriptions/resourceGroups/write",
    "Microsoft.Resources/subscriptions/resourceGroups/delete",
    "Microsoft.Web/serverfarms/read",
    "Microsoft.Web/serverfarms/write",
    "Microsoft.Web/sites/read",
    "Microsoft.Web/sites/write",
    "Microsoft.Network/publicIPAddresses/read",
    "Microsoft.Network/publicIPAddresses/write",
    "Microsoft.Network/trafficManagerProfiles/read",
    "Microsoft.Network/trafficManagerProfiles/write",
    "Microsoft.ApiManagement/service/read",
    "Microsoft.ApiManagement/service/write",
    "Microsoft.Storage/storageAccounts/read",
    "Microsoft.Storage/storageAccounts/write"
  ],
  "NotActions": [],
  "AssignableScopes": ["/subscriptions/<subscription-id>"]
}
```

Save the Azure role you need as `cloudclaim-azure-role.json`, then create the
app:

```bash
SUB=$(az account show --query id -o tsv)
# Replace <subscription-id> in the role file with $SUB before this.
az role definition create --role-definition cloudclaim-azure-role.json
az ad sp create-for-rbac --name cloudclaim --role "CloudClaim Check" --scopes "/subscriptions/$SUB"
```

Use the returned `appId`, `password`, `tenant`, and `$SUB` as the Azure env
file values.

AWS check policy file:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "sts:GetCallerIdentity",
        "elasticbeanstalk:CheckDNSAvailability"
      ],
      "Resource": "*"
    }
  ]
}
```

AWS claim policy file:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "sts:GetCallerIdentity",
        "elasticbeanstalk:CheckDNSAvailability",
        "elasticbeanstalk:CreateApplication",
        "elasticbeanstalk:ListAvailableSolutionStacks",
        "elasticbeanstalk:CreateEnvironment",
        "elasticbeanstalk:DescribeEnvironments",
        "elasticbeanstalk:TerminateEnvironment"
      ],
      "Resource": "*"
    }
  ]
}
```

Save the AWS policy you need as `cloudclaim-aws-policy.json`, then create the
profile:

```bash
aws iam create-policy --policy-name CloudClaimCheck --policy-document file://cloudclaim-aws-policy.json
aws iam attach-user-policy --user-name <user> --policy-arn arn:aws:iam::<account-id>:policy/CloudClaimCheck
aws configure --profile cloudclaim-check
```

Elastic Beanstalk service roles and instance profiles must already exist in the
account/region.

## Claim Behavior

`claim` checks availability before creating resources. It only attempts targets
reported as `available`. Resources are kept unless `--cleanup` is passed.
