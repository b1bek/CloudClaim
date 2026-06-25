from __future__ import annotations

from dataclasses import dataclass
import json
import os
import subprocess
from typing import Any


_SUBSCRIPTION: str | None = None


class AzureCredentialError(ValueError):
    pass


@dataclass(frozen=True)
class AzureServicePrincipalCredentials:
    client_id: str
    client_secret: str
    tenant_id: str
    subscription: str


SERVICE_PRINCIPAL_ENV = {
    "client_id": ("CLOUDCLAIM_AZURE_CLIENT_ID", "AZURE_CLIENT_ID"),
    "client_secret": ("CLOUDCLAIM_AZURE_CLIENT_SECRET", "AZURE_CLIENT_SECRET"),
    "tenant_id": ("CLOUDCLAIM_AZURE_TENANT_ID", "AZURE_TENANT_ID"),
    "subscription": ("CLOUDCLAIM_AZURE_SUBSCRIPTION", "AZURE_SUBSCRIPTION_ID"),
}

SERVICE_PRINCIPAL_DISPLAY = {
    "client_id": "AZURE_CLIENT_ID",
    "client_secret": "AZURE_CLIENT_SECRET",
    "tenant_id": "AZURE_TENANT_ID",
    "subscription": "AZURE_SUBSCRIPTION_ID or CLOUDCLAIM_AZURE_SUBSCRIPTION",
}


def configure_subscription(subscription: str | None) -> None:
    global _SUBSCRIPTION
    _SUBSCRIPTION = subscription or None


def first_env(*names: str) -> str | None:
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    return None


def service_principal_credentials_from_env(subscription: str | None = None) -> AzureServicePrincipalCredentials | None:
    values = {name: first_env(*env_names) for name, env_names in SERVICE_PRINCIPAL_ENV.items()}
    values["subscription"] = subscription or values["subscription"]
    if not any(values[name] for name in ("client_id", "client_secret")):
        return None

    missing = [name for name, value in values.items() if not value]
    if missing:
        display = ", ".join(SERVICE_PRINCIPAL_DISPLAY[name] for name in missing)
        raise AzureCredentialError(f"Azure service principal credentials are incomplete; missing {display}")

    return AzureServicePrincipalCredentials(
        client_id=str(values["client_id"]),
        client_secret=str(values["client_secret"]),
        tenant_id=str(values["tenant_id"]),
        subscription=str(values["subscription"]),
    )


def az_command(args: list[str], *, output: str, subscription: str | None = None, use_configured_subscription: bool = True) -> list[str]:
    command = ["az", *args, "--only-show-errors", "-o", output]
    selected_subscription = subscription or (_SUBSCRIPTION if use_configured_subscription else None)
    if selected_subscription:
        command.extend(["--subscription", selected_subscription])
    return command


def az_json(
    args: list[str],
    timeout: int = 60,
    subscription: str | None = None,
    use_configured_subscription: bool = True,
) -> tuple[bool, dict[str, Any]]:
    command = az_command(args, output="json", subscription=subscription, use_configured_subscription=use_configured_subscription)
    try:
        proc = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, {"error": f"{type(exc).__name__}: {exc}"}

    data: dict[str, Any] = {}
    output = (proc.stdout or "").strip()
    if output:
        try:
            parsed = json.loads(output)
            data = parsed if isinstance(parsed, dict) else {"value": parsed}
        except json.JSONDecodeError:
            data = {"raw_output": output}

    if proc.stderr.strip():
        data["stderr"] = proc.stderr.strip()
    if proc.returncode != 0:
        data.setdefault("error", f"az exited {proc.returncode}")
        return False, data
    return True, data


def az_text(args: list[str], timeout: int = 60, subscription: str | None = None, use_configured_subscription: bool = True) -> tuple[bool, str]:
    command = az_command(args, output="tsv", subscription=subscription, use_configured_subscription=use_configured_subscription)
    try:
        proc = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"{type(exc).__name__}: {exc}"

    if proc.returncode != 0:
        return False, (proc.stderr or proc.stdout or f"az exited {proc.returncode}").strip()
    return True, (proc.stdout or "").strip()


def require_az(ok: bool, data: dict[str, Any] | str, action: str) -> dict[str, Any] | str:
    if ok:
        return data

    detail = data if isinstance(data, str) else data.get("stderr") or data.get("error") or json.dumps(data)
    raise RuntimeError(f"{action} failed: {detail}")


def login_service_principal(creds: AzureServicePrincipalCredentials) -> None:
    ok, data = az_json(
        [
            "login",
            "--service-principal",
            "--username",
            creds.client_id,
            "--password",
            creds.client_secret,
            "--tenant",
            creds.tenant_id,
        ],
        timeout=60,
        use_configured_subscription=False,
    )
    if not ok:
        detail = data.get("stderr") or data.get("error") or json.dumps(data)
        raise AzureCredentialError(f"Azure service principal login failed: {detail}")


def configure_service_principal_from_env(subscription: str | None = None) -> str | None:
    creds = service_principal_credentials_from_env(subscription)
    if not creds:
        return subscription
    login_service_principal(creds)
    return creds.subscription


def precheck(subscription: str | None = None) -> dict[str, Any]:
    ok, data = az_json(["account", "show"], timeout=30, subscription=subscription)
    if not ok:
        detail = data.get("stderr") or data.get("error") or json.dumps(data)
        if subscription:
            detail = f"Azure credential precheck failed for subscription {subscription!r}: {detail}"
        return {"ok": False, "provider": "azure", "message": str(detail)}

    subscription = str(data.get("id", "") or "")
    if not subscription:
        return {"ok": False, "provider": "azure", "message": "Azure CLI account output did not include subscription id"}

    return {
        "ok": True,
        "provider": "azure",
        "account": str(data.get("user", {}).get("name", "") if isinstance(data.get("user"), dict) else ""),
        "subscription_id": subscription,
        "subscription_name": str(data.get("name", "") or ""),
        "tenant_id": str(data.get("tenantId", "") or ""),
    }


def subscription_id(subscription: str | None = None) -> str:
    data = require_az(*az_json(["account", "show"], timeout=30, subscription=subscription), action="read Azure account")
    assert isinstance(data, dict)
    sub = data.get("id")
    if not sub:
        raise RuntimeError("Azure CLI account output did not include subscription id")
    return str(sub)


def create_resource_group(resource_group: str, location: str) -> None:
    require_az(
        *az_json(
            ["group", "create", "-n", resource_group, "-l", location, "--tags", "purpose=cloudclaim-poc"],
            timeout=120,
        ),
        action="create resource group",
    )


def delete_resource_group(resource_group: str) -> tuple[bool, str]:
    return az_text(["group", "delete", "-n", resource_group, "--yes", "--no-wait"], timeout=60)
