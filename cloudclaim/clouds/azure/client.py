from __future__ import annotations

import json
import subprocess
from typing import Any


def az_json(args: list[str], timeout: int = 60) -> tuple[bool, dict[str, Any]]:
    command = ["az", *args, "--only-show-errors", "-o", "json"]
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


def az_text(args: list[str], timeout: int = 60) -> tuple[bool, str]:
    command = ["az", *args, "--only-show-errors", "-o", "tsv"]
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


def precheck() -> dict[str, Any]:
    ok, data = az_json(["account", "show"], timeout=30)
    if not ok:
        detail = data.get("stderr") or data.get("error") or json.dumps(data)
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


def subscription_id() -> str:
    data = require_az(*az_json(["account", "show"], timeout=30), action="read Azure account")
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
