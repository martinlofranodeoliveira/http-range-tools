"""Offline JSON command-line interface; no file, stdin, or network inputs."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence

from .core import (
    ClosedRange, OpenRange, RangeError, RangeResult, RangeSpec,
    _format_decimal, _parse_decimal, parse_range, resolve_range,
)


def _size_argument(value: str) -> int:
    if not 1 <= len(value) <= 8192 or not all("0" <= digit <= "9" for digit in value):
        raise argparse.ArgumentTypeError("size must contain 1–8192 ASCII decimal digits")
    return _parse_decimal(value)


def _limit_argument(value: str) -> int:
    if not value or not all("0" <= digit <= "9" for digit in value):
        raise argparse.ArgumentTypeError("limit must be a positive integer")
    result = _parse_decimal(value)
    if result == 0:
        raise argparse.ArgumentTypeError("limit must be positive")
    return result


def _result_json(result: RangeResult) -> str:
    # Only fixed keys, Booleans, and validated nonnegative integers are emitted.
    # Chunked integer formatting preserves exact JSON numbers beyond CPython's
    # decimal conversion guard, without changing process-global settings.
    parts = [
        '{"start":' + _format_decimal(part.start)
        + ',"stop":' + _format_decimal(part.stop)
        + ',"length":' + _format_decimal(part.length) + '}'
        for part in result.ranges
    ]
    return (
        '{"size":' + _format_decimal(result.size)
        + ',"ranges":[' + ",".join(parts) + ']'
        + ',"satisfiable":' + ("true" if result.satisfiable else "false")
        + ',"unsatisfied_count":' + _format_decimal(result.unsatisfied_count) + '}'
    )


def _parsed_json(specs: Sequence[RangeSpec]) -> str:
    parts = []
    for spec in specs:
        if isinstance(spec, ClosedRange):
            parts.append('{"type":"closed","first":' + _format_decimal(spec.first)
                         + ',"last":' + _format_decimal(spec.last) + '}')
        elif isinstance(spec, OpenRange):
            parts.append('{"type":"open","first":' + _format_decimal(spec.first) + '}')
        else:
            parts.append('{"type":"suffix","length":' + _format_decimal(spec.length) + '}')
    return '{"unit":"bytes","ranges":[' + ",".join(parts) + ']}'


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="http-range-tools",
        description="Parse or resolve one HTTP byte Range field offline as JSON.",
        epilog=(
            "Exit codes: 0 valid parse-only input or satisfiable resolution, "
            "1 valid but unsatisfiable resolution, 2 input error. "
            "The default header bound is 8192 ASCII characters and 16 nonempty ranges; "
            "at most 16 empty comma members are ignored. No files or network are read."
        ),
    )
    parser.add_argument("header", help="Range field value, for example 'bytes=2-4,-2'")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--size", type=_size_argument,
                      help="resolve against a byte size: 1–8192 ASCII decimal digits")
    mode.add_argument("--parse-only", action="store_true",
                      help="inspect range syntax without a size or satisfiability check")
    parser.add_argument("--max-header-length", type=_limit_argument, default=8192,
                        help="maximum untrimmed header characters (default: 8192)")
    parser.add_argument("--max-ranges", type=_limit_argument, default=16,
                        help="maximum nonempty range members (default: 16)")
    args = parser.parse_args(argv)
    try:
        if args.parse_only:
            specs = parse_range(args.header, max_header_length=args.max_header_length,
                                max_ranges=args.max_ranges)
            output = _parsed_json(specs)
            exit_code = 0
        else:
            result = resolve_range(args.header, args.size,
                                   max_header_length=args.max_header_length,
                                   max_ranges=args.max_ranges)
            output = _result_json(result)
            exit_code = 0 if result.satisfiable else 1
    except RangeError as error:
        print(json.dumps({"error": {"code": error.code, "message": str(error)}},
                         ensure_ascii=True, separators=(",", ":")), file=sys.stderr)
        return 2
    print(output)
    return exit_code
