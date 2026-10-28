"""Bounded HTTP byte Range parsing and offline half-open slice resolution."""

from .core import (
    ClosedRange,
    OpenRange,
    RangeError,
    RangeLimitError,
    RangeResult,
    RangeSpec,
    RangeSyntaxError,
    ResolvedRange,
    SuffixRange,
    UnsupportedRangeUnit,
    parse_range,
    resolve_range,
    resolve_ranges,
)

__all__ = [
    "ClosedRange", "OpenRange", "RangeError", "RangeLimitError", "RangeResult",
    "RangeSpec", "RangeSyntaxError", "ResolvedRange", "SuffixRange",
    "UnsupportedRangeUnit", "parse_range", "resolve_range", "resolve_ranges",
]

__version__ = "0.1.0"
