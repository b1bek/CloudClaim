from __future__ import annotations

import argparse
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class Provider:
    name: str
    resource_group_prefix: str
    add_parser: Callable[[argparse._SubParsersAction[argparse.ArgumentParser]], None]
    dispatch: Callable[[argparse.Namespace], int]


def register_providers(subcommands: argparse._SubParsersAction[argparse.ArgumentParser], providers: list[Provider]) -> None:
    for provider in providers:
        provider.add_parser(subcommands)


def dispatch_provider(args: argparse.Namespace, providers: dict[str, Provider]) -> int:
    provider = providers.get(getattr(args, "cloud", ""))
    if not provider:
        return 2

    args.resource_group_prefix = provider.resource_group_prefix
    return provider.dispatch(args)
