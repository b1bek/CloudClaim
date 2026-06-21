from __future__ import annotations

from pathlib import Path

from .models import AwsTarget
from .services import classify_hostname, normalize_hostname

TEXT_HEADER_NAMES = {"hostname", "host", "hostnames", "hosts", "target", "targets"}


def read_text_values(path: Path) -> list[str]:
    values: list[str] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            value = line.strip()
            if not value or value.startswith("#"):
                continue
            if not values and value.lower() in TEXT_HEADER_NAMES:
                continue
            values.append(value)
    return values


def target_from_value(value: str, source: str) -> list[AwsTarget]:
    hostname = value.strip()
    if not hostname:
        return []

    target = classify_hostname(hostname, source=source)
    if target:
        return [target]

    return [AwsTarget("unsupported", normalize_hostname(hostname), "", "", source=source)]


def targets_from_values(values: list[str], source: str) -> list[AwsTarget]:
    targets: list[AwsTarget] = []
    for value in values:
        targets.extend(target_from_value(value, source))
    return targets


def load_targets_from_file(path: Path) -> list[AwsTarget]:
    if path.suffix.lower() != ".txt":
        raise SystemExit(f"Only .txt input files are supported: {path}")
    return targets_from_values(read_text_values(path), str(path))


def load_targets(inputs: list[str]) -> list[AwsTarget]:
    targets: list[AwsTarget] = []
    for value in inputs:
        path = Path(value)
        if path.exists():
            targets.extend(load_targets_from_file(path))
            continue
        targets.extend(target_from_value(value, value))
    return targets
