from __future__ import annotations

from typing import Any


COLORS = {
    "reset": "\033[0m",
    "green": "\033[32m",
    "yellow": "\033[33m",
    "red": "\033[31m",
    "cyan": "\033[36m",
    "blue": "\033[34m",
    "magenta": "\033[35m",
}

BANNER = (
    "   ____ _                 _  ____ _       _           \n"
    "  / ___| | ___  _   _  __| |/ ___| | __ _(_)_ __ ___  \n"
    " | |   | |/ _ \\| | | |/ _` | |   | |/ _` | | '_ ` _ \\ \n"
    " | |___| | (_) | |_| | (_| | |___| | (_| | | | | | | |\n"
    "  \\____|_|\\___/ \\__,_|\\__,_|\\____|_|\\__,_|_|_| |_| |_|\n"
    "                                          by @b1bek"
)


def emit(line: str = "") -> None:
    print(line, flush=True)


def should_color(mode: str) -> bool:
    if mode == "always":
        return True
    if mode == "never":
        return False
    return True


def paint(value: str, color: str, enabled: bool) -> str:
    if not enabled:
        return value
    return f"{COLORS[color]}{value}{COLORS['reset']}"


def color_for_tag(value: Any) -> str:
    text = str(value)
    if text in {"INF", "azure", "aws"}:
        return "cyan"
    if text == "WRN":
        return "yellow"
    if text == "ERR":
        return "red"
    if text in {"available", "claimed", "check", "claim", "check,claim"}:
        return "green"
    if text in {"not-available", "not-claimed", "failed", "claim:failed"}:
        return "red"
    if text in {"quota", "duplicate", "skipped", "unsupported"}:
        return "yellow"
    if text.startswith("rg:") or text.startswith("region:") or text.startswith("env:"):
        return "magenta"
    return "blue"


def tag(value: Any, *, color: bool = False) -> str:
    return paint(f"[{value}]", color_for_tag(value), color)


def tag_join(*values: Any, color: bool = False) -> str:
    return " ".join(tag(value, color=color) for value in values if value not in {"", None})


def compact_message(value: Any, *, limit: int = 240) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return f"{text[: limit - 1].rstrip()}..."


def log_line(level: str, message: str, *, color: bool) -> str:
    return f"{tag(level, color=color)} {message}"


def print_banner(*, color: bool = False) -> None:
    emit(paint(BANNER, "cyan", color))
