"""Public behavior checks and a small exhaustive slice-equivalence exercise."""

from dataclasses import FrozenInstanceError
import sys
import unittest

from http_range_tools import (
    ClosedRange, OpenRange, RangeError, RangeLimitError, RangeResult,
    RangeSyntaxError, ResolvedRange, SuffixRange, UnsupportedRangeUnit,
    parse_range, resolve_range, resolve_ranges,
)


class ParserTests(unittest.TestCase):
    def test_parsed_types_and_leading_zeros(self):
        self.assertEqual(parse_range("BYTES= 0002-0004,9-,-02"),
                         (ClosedRange(2, 4), OpenRange(9), SuffixRange(2)))

    def test_ascii_whitespace_and_empty_members(self):
        self.assertEqual(parse_range("\t bytes=, \t2-4,,\t \t"), (ClosedRange(2, 4),))

    def test_empty_member_bound(self):
        self.assertEqual(parse_range("bytes=" + "," * 16 + "0-0"), (ClosedRange(0, 0),))
        with self.assertRaises(RangeLimitError):
            parse_range("bytes=" + "," * 17 + "0-0")

    def test_nonempty_member_count_is_independent(self):
        self.assertEqual(len(parse_range("bytes=,0-0,,1-1,", max_ranges=2)), 2)
        with self.assertRaises(RangeLimitError):
            parse_range("bytes=0-0,1-1,2-2", max_ranges=2)

    def test_exact_raw_header_limit(self):
        value = "\tbytes=0-1 "
        self.assertEqual(parse_range(value, max_header_length=len(value)), (ClosedRange(0, 1),))
        with self.assertRaises(RangeLimitError):
            parse_range(value, max_header_length=len(value) - 1)

    def test_configurable_limits_validate_types_and_values(self):
        for name in ("max_ranges", "max_header_length"):
            for bad in (True, False, 1.5, "8", None):
                with self.subTest(name=name, bad=bad), self.assertRaises(TypeError):
                    parse_range("bytes=0-0", **{name: bad})
            for bad in (0, -1):
                with self.subTest(name=name, bad=bad), self.assertRaises(ValueError):
                    parse_range("bytes=0-0", **{name: bad})

    def test_non_string_input(self):
        for value in (None, b"bytes=0-0", 4, ["bytes=0-0"]):
            with self.subTest(value=value), self.assertRaises(TypeError):
                parse_range(value)

    def test_invalid_members_invalidate_entire_field(self):
        invalid = (
            "", "bytes=", "bytes= , ,", "bytes=-", "bytes=8-7", "bytes=0-1,8-7",
            "bytes=+1-2", "bytes=1 -2", "bytes=1- 2", "bytes=1--2", "bytes=--2",
            "bytes=1", "bytes=1.0-2", "bytes=1e2-", "bytes=0-1;", "bytes=0-1=2",
            "bytes =0-1", "Range: bytes=0-1", "=0-1", "by/tes=0-1",
        )
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(RangeSyntaxError):
                parse_range(value)

    def test_non_ascii_and_controls(self):
        for character in ("\n", "\r", "\x00", "\x0b", "\x0c", "\x1f", "\x7f", "\u00a0", "１", "١"):
            with self.subTest(character=repr(character)), self.assertRaises(RangeSyntaxError):
                parse_range("bytes=0-1" + character)

    def test_unknown_unit_is_distinct_and_payload_is_not_interpreted(self):
        for header in ("ITEMS=anything", "items=", "items=3--2", "items=with spaces"):
            with self.subTest(header=header), self.assertRaises(UnsupportedRangeUnit) as caught:
                parse_range(header)
            self.assertEqual(caught.exception.unit, "items")
            self.assertEqual(caught.exception.code, "unsupported_unit")
            self.assertIsInstance(caught.exception, RangeError)

    def test_stable_error_codes(self):
        self.assertEqual(RangeSyntaxError.code, "invalid_range")
        self.assertEqual(RangeLimitError.code, "limit_exceeded")

    def test_huge_decimal_numerals_without_global_setting_changes(self):
        get_guard = getattr(sys, "get_int_max_str_digits", lambda: None)
        before = get_guard()
        huge = "9" * 5000
        parsed = parse_range("bytes=" + huge + "-")[0]
        self.assertEqual(parsed.first, 10 ** 5000 - 1)
        self.assertEqual(resolve_range("bytes=1-" + huge, 12).ranges, (ResolvedRange(1, 12),))
        self.assertEqual(resolve_range("bytes=-" + huge, 12).ranges, (ResolvedRange(0, 12),))
        self.assertFalse(resolve_range("bytes=" + huge + "-", 12).satisfiable)
        self.assertEqual(get_guard(), before)


class ResolutionTests(unittest.TestCase):
    def test_closed_open_and_suffix_ranges(self):
        result = resolve_range("bytes=2-4,9-,-2", 12)
        self.assertEqual(result, RangeResult(12, (ResolvedRange(2, 5), ResolvedRange(9, 12),
                                                ResolvedRange(10, 12)), True, 0))
        self.assertEqual([part.length for part in result.ranges], [3, 3, 2])

    def test_clamp_and_filter_unsatisfiable_members(self):
        result = resolve_range("bytes=9-99,30-,-99,12-12,-0", 12)
        self.assertEqual(result.ranges, (ResolvedRange(9, 12), ResolvedRange(0, 12)))
        self.assertTrue(result.satisfiable)
        self.assertEqual(result.unsatisfied_count, 3)

    def test_wholly_unsatisfiable(self):
        self.assertEqual(resolve_range("bytes=12-,-0", 12), RangeResult(12, (), False, 2))

    def test_empty_representation_positive_suffix_remains_satisfiable(self):
        self.assertEqual(resolve_range("bytes=0-,-0,-1,-9", 0),
                         RangeResult(0, (ResolvedRange(0, 0), ResolvedRange(0, 0)), True, 2))
        self.assertEqual(resolve_range("bytes=0-", 0), RangeResult(0, (), False, 1))

    def test_order_overlaps_adjacency_and_duplicates_are_preserved(self):
        self.assertEqual(resolve_range("bytes=5-8,0-2,2-5,6-6,6-6", 10).ranges,
                         tuple(ResolvedRange(*pair) for pair in ((5, 9), (0, 3), (2, 6), (6, 7), (6, 7))))

    def test_size_errors_and_precedence(self):
        for bad in (True, False, None, 2.0, "12"):
            with self.subTest(bad=bad), self.assertRaises(TypeError):
                resolve_range("invalid", bad)
        with self.assertRaises(ValueError) as caught:
            resolve_range("invalid", -1)
        self.assertNotIsInstance(caught.exception, RangeError)

    def test_parsed_input_sequence_validation(self):
        self.assertEqual(resolve_ranges([OpenRange(2)], 4).ranges, (ResolvedRange(2, 4),))
        self.assertEqual(len(resolve_ranges([OpenRange(0)] * 20, 4).ranges), 20)
        with self.assertRaises(ValueError):
            resolve_ranges([], 4)
        for specs in ("bytes=0-0", b"x", (item for item in [OpenRange(0)]), None, [1], [None]):
            with self.subTest(kind=type(specs).__name__), self.assertRaises(TypeError):
                resolve_ranges(specs, 4)

    def test_constructors_validate_and_freeze(self):
        factories = (lambda value: ClosedRange(value, 4), lambda value: OpenRange(value),
                     lambda value: SuffixRange(value), lambda value: ResolvedRange(value, 4),
                     lambda value: RangeResult(value, (), False, 0),
                     lambda value: RangeResult(0, (), False, value))
        for factory in factories:
            for bad in (True, 1.0, "1", None):
                with self.subTest(bad=bad), self.assertRaises(TypeError):
                    factory(bad)
            with self.assertRaises(ValueError):
                factory(-1)
        for factory in (lambda: ClosedRange(3, 2), lambda: ResolvedRange(3, 2)):
            with self.assertRaises(ValueError):
                factory()
        with self.assertRaises(FrozenInstanceError):
            OpenRange(0).first = 1

    def test_small_exhaustive_ranges_select_expected_bytes(self):
        for size in range(8):
            data = bytes(range(size))
            for first in range(10):
                for last in range(first, 10):
                    with self.subTest(size=size, first=first, last=last):
                        result = resolve_range(f"bytes={first}-{last}", size)
                        selected = b"".join(data[part.start:part.stop] for part in result.ranges)
                        self.assertEqual(selected, data[first:last + 1])
                        self.assertEqual(result.satisfiable, first < size)
            for length in range(10):
                with self.subTest(size=size, suffix=length):
                    result = resolve_range(f"bytes=-{length}", size)
                    selected = b"".join(data[part.start:part.stop] for part in result.ranges)
                    self.assertEqual(selected, data[-length:] if length else b"")
                    self.assertEqual(result.satisfiable, length > 0)


if __name__ == "__main__":
    unittest.main()
