"""Original implementation informed by RFC 9110 sections 14.1 and 5.6.

The caller supplies the size of the selected representation. This module has
no HTTP response policy and performs no file or network access.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
import re
from typing import Union

_TOKEN = re.compile(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+", re.ASCII)
_MEMBER = re.compile(r"([0-9]*)-([0-9]*)", re.ASCII)
_MAX_EMPTY_MEMBERS = 16
_CHUNK_DIGITS = 9
_CHUNK_BASE = 10 ** _CHUNK_DIGITS


def _unsigned_integer(value: int, name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{name} must be an integer, not a Boolean")
    if value < 0:
        raise ValueError(f"{name} must be nonnegative")


def _positive_integer(value: int, name: str) -> None:
    _unsigned_integer(value, name)
    if value == 0:
        raise ValueError(f"{name} must be positive")


def _parse_decimal(digits: str) -> int:
    """Convert already-validated ASCII digits without a global guard change.

    Each int() conversion handles at most nine digits, so Python's optional
    per-conversion decimal limit cannot reject a bounded valid field value.
    """
    result = 0
    for offset in range(0, len(digits), _CHUNK_DIGITS):
        chunk = digits[offset:offset + _CHUNK_DIGITS]
        result = result * (10 ** len(chunk)) + int(chunk)
    return result


def _format_decimal(value: int) -> str:
    """Format a nonnegative integer without the decimal conversion guard."""
    if value == 0:
        return "0"
    chunks = []
    while value:
        value, remainder = divmod(value, _CHUNK_BASE)
        chunks.append(remainder)
    return str(chunks[-1]) + "".join(f"{part:09d}" for part in reversed(chunks[:-1]))


class RangeError(ValueError):
    """Base class for Range field errors; ``code`` is stable."""

    code = "invalid_range"


class RangeSyntaxError(RangeError):
    """The field is not valid byte Range syntax."""

    code = "invalid_range"


class RangeLimitError(RangeError):
    """A caller-selected or fixed parser resource bound was exceeded."""

    code = "limit_exceeded"


class UnsupportedRangeUnit(RangeError):
    """The envelope names an unknown unit; its payload was not interpreted."""

    code = "unsupported_unit"

    def __init__(self, unit: str) -> None:
        self.unit = unit.lower()
        super().__init__("Range unit is not supported; only bytes is supported")


@dataclass(frozen=True)
class ClosedRange:
    """Inclusive HTTP offsets, with ``0 <= first <= last``."""

    first: int
    last: int

    def __post_init__(self) -> None:
        _unsigned_integer(self.first, "first")
        _unsigned_integer(self.last, "last")
        if self.last < self.first:
            raise ValueError("last must not precede first")


@dataclass(frozen=True)
class OpenRange:
    """An inclusive starting offset extending to the representation end."""

    first: int

    def __post_init__(self) -> None:
        _unsigned_integer(self.first, "first")


@dataclass(frozen=True)
class SuffixRange:
    """At most ``length`` final bytes; zero is valid but unsatisfiable."""

    length: int

    def __post_init__(self) -> None:
        _unsigned_integer(self.length, "length")


RangeSpec = Union[ClosedRange, OpenRange, SuffixRange]


@dataclass(frozen=True)
class ResolvedRange:
    """A half-open interval suitable for ``data[start:stop]``."""

    start: int
    stop: int

    def __post_init__(self) -> None:
        _unsigned_integer(self.start, "start")
        _unsigned_integer(self.stop, "stop")
        if self.stop < self.start:
            raise ValueError("stop must not precede start")

    @property
    def length(self) -> int:
        return self.stop - self.start


@dataclass(frozen=True)
class RangeResult:
    """Resolution preserving order and duplicates, with explicit satisfaction."""

    size: int
    ranges: tuple[ResolvedRange, ...]
    satisfiable: bool
    unsatisfied_count: int

    def __post_init__(self) -> None:
        _unsigned_integer(self.size, "size")
        _unsigned_integer(self.unsatisfied_count, "unsatisfied_count")
        if not isinstance(self.ranges, tuple) or any(
            not isinstance(item, ResolvedRange) for item in self.ranges
        ):
            raise TypeError("ranges must be a tuple of ResolvedRange objects")
        if not isinstance(self.satisfiable, bool):
            raise TypeError("satisfiable must be a Boolean")


def parse_range(
    value: str, *, max_header_length: int = 8192, max_ranges: int = 16
) -> tuple[RangeSpec, ...]:
    """Parse one ASCII Range field value, without the ``Range:`` field name.

    Unknown token units have a distinct error. At most sixteen empty comma
    members are ignored; at least one nonempty byte member remains required.
    """
    _positive_integer(max_header_length, "max_header_length")
    _positive_integer(max_ranges, "max_ranges")
    if not isinstance(value, str):
        raise TypeError("value must be a string")
    if len(value) > max_header_length:
        raise RangeLimitError("Range field exceeds max_header_length")
    if not value.isascii() or any(
        ord(character) < 32 and character != "\t" or ord(character) == 127
        for character in value
    ):
        raise RangeSyntaxError("Range field must contain ASCII text without controls")

    unit, separator, payload = value.strip(" \t").partition("=")
    if not separator or _TOKEN.fullmatch(unit) is None:
        raise RangeSyntaxError("Expected a token range unit immediately followed by =")
    if unit.lower() != "bytes":
        raise UnsupportedRangeUnit(unit)

    specs: list[RangeSpec] = []
    empty_count = 0
    for member in payload.split(","):
        member = member.strip(" \t")
        if not member:
            empty_count += 1
            if empty_count > _MAX_EMPTY_MEMBERS:
                raise RangeLimitError("Range field exceeds sixteen empty list members")
            continue
        if len(specs) >= max_ranges:
            raise RangeLimitError("Range field exceeds max_ranges")
        match = _MEMBER.fullmatch(member)
        if match is None:
            raise RangeSyntaxError("Expected first-last, first-, or -length")
        first_text, last_text = match.groups()
        if not first_text and not last_text:
            raise RangeSyntaxError("A range member must contain a number")
        if not first_text:
            specs.append(SuffixRange(_parse_decimal(last_text)))
            continue
        first = _parse_decimal(first_text)
        if not last_text:
            specs.append(OpenRange(first))
            continue
        last = _parse_decimal(last_text)
        if last < first:
            raise RangeSyntaxError("A last offset must not precede its first offset")
        specs.append(ClosedRange(first, last))
    if not specs:
        raise RangeSyntaxError("Range field needs at least one nonempty member")
    return tuple(specs)


def resolve_ranges(specs: Sequence[RangeSpec], size: int) -> RangeResult:
    """Resolve a nonempty parsed sequence against a nonnegative byte size.

    Positive suffixes resolve to an empty but satisfiable slice at size zero,
    as defined by RFC 9110 section 14.1.2. No ranges are merged or reordered.
    """
    _unsigned_integer(size, "size")
    if not isinstance(specs, Sequence) or isinstance(specs, (str, bytes, bytearray)):
        raise TypeError("specs must be a finite sequence of range spec objects")
    if len(specs) == 0:
        raise ValueError("specs must not be empty")

    resolved = []
    unsatisfied = 0
    for spec in specs:
        if isinstance(spec, SuffixRange):
            if spec.length == 0:
                unsatisfied += 1
            else:
                resolved.append(ResolvedRange(max(0, size - spec.length), size))
        elif isinstance(spec, (ClosedRange, OpenRange)):
            if spec.first >= size:
                unsatisfied += 1
            else:
                stop = min(size, spec.last + 1) if isinstance(spec, ClosedRange) else size
                resolved.append(ResolvedRange(spec.first, stop))
        else:
            raise TypeError("specs must contain only declared range spec classes")
    return RangeResult(size, tuple(resolved), bool(resolved), unsatisfied)


def resolve_range(
    value: str, size: int, *, max_header_length: int = 8192, max_ranges: int = 16
) -> RangeResult:
    """Validate size, parse a field value, then resolve its byte members."""
    _unsigned_integer(size, "size")
    specs = parse_range(value, max_header_length=max_header_length, max_ranges=max_ranges)
    return resolve_ranges(specs, size)
