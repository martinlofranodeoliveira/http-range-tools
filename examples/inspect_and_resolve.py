"""Inspect parsed specifications and handle expected input errors explicitly."""

from http_range_tools import RangeSyntaxError, parse_range, resolve_ranges

specs = parse_range("BYTES=,0002-0004,8-,-3,")
result = resolve_ranges(specs, 12)
assert [(part.start, part.stop) for part in result.ranges] == [(2, 5), (8, 12), (9, 12)]
print("Parsed:", specs)
print("Resolved:", result)
try:
    parse_range("bytes=0-2,8-7")
except RangeSyntaxError as error:
    print("Expected invalid input:", error.code)
else:
    raise AssertionError("A reversed member must invalidate the whole value")
