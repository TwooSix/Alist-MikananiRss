"""Small command-line bootstrap shared by standard Skill scripts."""

from __future__ import annotations

import argparse
import asyncio
import inspect
import json
import sys
from collections.abc import Callable


def run_cli(run: Callable) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--json",
        dest="payload",
        default=None,
        help="JSON object containing arguments for this Skill script",
    )
    args = parser.parse_args()
    raw_payload = args.payload
    if raw_payload is None:
        raw_payload = sys.stdin.read() if not sys.stdin.isatty() else "{}"
    raw_payload = raw_payload.strip() or "{}"
    try:
        payload = json.loads(raw_payload)
        if not isinstance(payload, dict):
            raise ValueError("--json must contain an object")
    except ValueError as error:
        print(f"Invalid arguments: {error}", file=sys.stderr)
        raise SystemExit(2) from error

    try:
        result = run(**payload)
        if inspect.isawaitable(result):
            result = asyncio.run(result)
    except (TypeError, ValueError) as error:
        print(f"Invalid arguments: {error}", file=sys.stderr)
        raise SystemExit(2) from error
    except Exception as error:  # noqa: BLE001
        print(f"Skill script failed: {error}", file=sys.stderr)
        raise SystemExit(4) from error

    if isinstance(result, (dict, list)):
        print(json.dumps(result, ensure_ascii=False))
    elif result is not None:
        print(str(result))


__all__ = ["run_cli"]
