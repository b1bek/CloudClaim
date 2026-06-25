from __future__ import annotations

import json
import subprocess
from typing import Any


def aws_command(args: list[str], *, region: str | None = None, profile: str | None = None, output: str = "json") -> list[str]:
    command = ["aws", *args]
    if region:
        command.extend(["--region", region])
    if profile:
        command.extend(["--profile", profile])
    if output:
        command.extend(["--output", output])
    return command


def aws_json(
    args: list[str],
    *,
    region: str | None = None,
    profile: str | None = None,
    timeout: int = 60,
) -> tuple[bool, dict[str, Any]]:
    command = aws_command(args, region=region, profile=profile, output="json")
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
        data.setdefault("error", f"aws exited {proc.returncode}")
        return False, data
    return True, data


def aws_text(
    args: list[str],
    *,
    region: str | None = None,
    profile: str | None = None,
    timeout: int = 60,
) -> tuple[bool, str]:
    command = aws_command(args, region=region, profile=profile, output="text")
    try:
        proc = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"{type(exc).__name__}: {exc}"

    if proc.returncode != 0:
        return False, (proc.stderr or proc.stdout or f"aws exited {proc.returncode}").strip()
    return True, (proc.stdout or "").strip()


def require_aws(ok: bool, data: dict[str, Any] | str, action: str) -> dict[str, Any] | str:
    if ok:
        return data

    detail = data if isinstance(data, str) else data.get("stderr") or data.get("error") or json.dumps(data)
    raise RuntimeError(f"{action} failed: {detail}")


def precheck(*, region: str | None = None, profile: str | None = None) -> dict[str, Any]:
    ok, data = aws_json(["sts", "get-caller-identity"], region=region, profile=profile, timeout=30)
    if not ok:
        detail = data.get("stderr") or data.get("error") or json.dumps(data)
        if profile:
            detail = f"AWS credential precheck failed for profile {profile!r}: {detail}"
        return {"ok": False, "provider": "aws", "message": str(detail), "region": region or "", "profile": profile or ""}

    account = str(data.get("Account", "") or "")
    arn = str(data.get("Arn", "") or "")
    user_id = str(data.get("UserId", "") or "")
    if not account or not arn:
        return {"ok": False, "provider": "aws", "message": "AWS STS output did not include account/arn", "region": region or "", "profile": profile or ""}

    return {
        "ok": True,
        "provider": "aws",
        "account": account,
        "arn": arn,
        "user_id": user_id,
        "region": region or "",
        "profile": profile or "",
    }
