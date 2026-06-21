from __future__ import annotations

from pathlib import Path

from .models import AzureTarget
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


def target_from_value(value: str, fallback_location: str, source: str) -> list[AzureTarget]:
    hostname = value.strip()
    if not hostname:
        return []

    target = classify_hostname(hostname, fallback_location, source=source)
    if target:
        return [target]

    return [
        AzureTarget(
            service="unsupported",
            azure_hostname=normalize_hostname(hostname),
            name="",
            location=fallback_location,
            source=source,
        )
    ]


def targets_from_values(values: list[str], fallback_location: str, source: str) -> list[AzureTarget]:
    targets: list[AzureTarget] = []
    for value in values:
        targets.extend(target_from_value(value, fallback_location, source))
    return targets


def load_targets_from_file(path: Path, fallback_location: str) -> list[AzureTarget]:
    if path.suffix.lower() != ".txt":
        raise SystemExit(f"Only .txt input files are supported: {path}")
    return targets_from_values(read_text_values(path), fallback_location, str(path))


def load_targets(inputs: list[str], fallback_location: str) -> list[AzureTarget]:
    targets: list[AzureTarget] = []
    for value in inputs:
        path = Path(value)
        if path.exists():
            targets.extend(load_targets_from_file(path, fallback_location))
            continue

        targets.extend(target_from_value(value, fallback_location, value))
    return targets
