from __future__ import annotations

import argparse

from .clouds import PROVIDERS, PROVIDERS_BY_NAME
from .core.providers import dispatch_provider, register_providers


def build_parser(*, prog: str = "cloudclaim") -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=prog, description="Cloud dangling-hostname claimability validator")
    subcommands = parser.add_subparsers(dest="cloud")
    register_providers(subcommands, PROVIDERS)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.cloud in PROVIDERS_BY_NAME:
        if not getattr(args, "command", None):
            parser.parse_args([args.cloud, "--help"])
            return 2
        return dispatch_provider(args, PROVIDERS_BY_NAME)

    parser.print_help()
    return 2
