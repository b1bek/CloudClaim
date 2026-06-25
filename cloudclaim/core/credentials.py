from __future__ import annotations

import os
from pathlib import Path


DEFAULT_ENV_FILE = ".env"


class CredentialFileError(ValueError):
    pass


def unquote_env_value(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def env_file_path(path: str | None) -> Path | None:
    selected_path = path or os.environ.get("CLOUDCLAIM_ENV_FILE")
    if selected_path:
        return Path(selected_path).expanduser()
    candidate = Path(DEFAULT_ENV_FILE)
    if candidate.exists():
        return candidate
    return None


def load_env_file(path: str | None) -> dict[str, str]:
    resolved_path = env_file_path(path)
    if not resolved_path:
        return {}

    loaded = {}
    try:
        lines = resolved_path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        reason = exc.strerror or str(exc)
        raise CredentialFileError(f"credential env file could not be read: {resolved_path} ({reason})") from exc

    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        loaded[key] = unquote_env_value(value)

    os.environ.update(loaded)
    return loaded
