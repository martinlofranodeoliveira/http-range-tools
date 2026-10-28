import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

import http_range_tools
from http_range_tools.cli import main


class CliTests(unittest.TestCase):
    def run_cli(self, *args):
        environment = {"PYTHONPATH": str(Path(http_range_tools.__file__).resolve().parents[1]),
                       "PYTHONDONTWRITEBYTECODE": "1"}
        return subprocess.run([sys.executable, "-S", "-B", "-m", "http_range_tools", *args],
                              capture_output=True, text=True, env=environment, timeout=10)

    def test_success_json(self):
        process = self.run_cli("--size", "00012", "bytes=2-4,-2")
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(process.stderr, "")
        self.assertEqual(json.loads(process.stdout), {
            "size": 12, "ranges": [{"start": 2, "stop": 5, "length": 3},
                                   {"start": 10, "stop": 12, "length": 2}],
            "satisfiable": True, "unsatisfied_count": 0,
        })
        self.assertTrue(process.stdout.endswith("\n"))

    def test_unsatisfiable_exit_one_with_same_schema(self):
        process = self.run_cli("--size", "12", "bytes=12-,-0")
        self.assertEqual(process.returncode, 1)
        self.assertEqual(json.loads(process.stdout),
                         {"size": 12, "ranges": [], "satisfiable": False, "unsatisfied_count": 2})
        self.assertEqual(process.stderr, "")

    def test_empty_positive_suffix_exit_zero(self):
        process = self.run_cli("--size", "0", "bytes=-1")
        self.assertEqual(process.returncode, 0)
        self.assertEqual(json.loads(process.stdout)["ranges"], [{"start": 0, "stop": 0, "length": 0}])

    def test_parser_error_codes_and_streams(self):
        cases = (("bytes=3-2", "invalid_range", []), ("items=foo", "unsupported_unit", []),
                 ("bytes=0-0,1-1", "limit_exceeded", ["--max-ranges", "1"]),
                 ("bytes=0-0", "limit_exceeded", ["--max-header-length", "8"]))
        for header, code, options in cases:
            with self.subTest(code=code):
                process = self.run_cli("--size", "4", *options, header)
                self.assertEqual(process.returncode, 2)
                self.assertEqual(process.stdout, "")
                error = json.loads(process.stderr)["error"]
                self.assertEqual(error["code"], code)
                self.assertTrue(error["message"])
                self.assertNotIn("Traceback", process.stderr)

    def test_usage_errors(self):
        cases = ([], ["bytes=0-0"], ["--size", "1"], ["--size", "-1", "bytes=0-0"],
                 ["--size", "+1", "bytes=0-0"], ["--size", "١", "bytes=0-0"],
                 ["--size", "1.0", "bytes=0-0"], ["--size", "9" * 8193, "bytes=0-0"],
                 ["--size", "2", "--max-ranges", "0", "bytes=0-0"])
        for args in cases:
            with self.subTest(kind=len(args)):
                process = self.run_cli(*args)
                self.assertEqual(process.returncode, 2)
                self.assertEqual(process.stdout, "")
                self.assertIn("usage:", process.stderr)
                self.assertNotIn("Traceback", process.stderr)

    def test_huge_size_and_header_stay_exact_json_numbers(self):
        size = "1" + "0" * 4999
        process = self.run_cli("--size", size, "bytes=0-")
        self.assertEqual(process.returncode, 0, process.stderr)
        # Preserve numeric tokens as text in this independent JSON reader.
        result = json.loads(process.stdout, parse_int=str)
        self.assertEqual(result["size"], size)
        self.assertEqual(result["ranges"], [{"start": "0", "stop": size, "length": size}])
        self.assertNotIn('"' + size + '"', process.stdout)
        process = self.run_cli("--size", "12", "bytes=0-" + "9" * 5000)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(json.loads(process.stdout)["ranges"][0]["stop"], 12)

    def test_help(self):
        process = self.run_cli("--help")
        self.assertEqual(process.returncode, 0)
        self.assertEqual(process.stderr, "")
        self.assertIn("Exit codes:", process.stdout)
        self.assertIn("8192", process.stdout)
        self.assertIn("16", process.stdout)

    def test_maximum_size_digits_are_accepted(self):
        size = "9" * 8192
        process = self.run_cli("--size", size, "bytes=-1")
        self.assertEqual(process.returncode, 0, process.stderr)
        result = json.loads(process.stdout, parse_int=str)
        self.assertEqual(result["size"], size)
        self.assertEqual(result["ranges"][0]["length"], "1")
        self.assertEqual(result["ranges"][0]["stop"], size)

    def test_import_does_not_execute_cli(self):
        environment = dict(os.environ, PYTHONPATH=str(Path(http_range_tools.__file__).resolve().parents[1]))
        process = subprocess.run([sys.executable, "-S", "-B", "-c", "import http_range_tools"],
                                 capture_output=True, text=True, env=environment, timeout=10)
        self.assertEqual((process.returncode, process.stdout, process.stderr), (0, "", ""))
        self.assertTrue(callable(main))


if __name__ == "__main__":
    unittest.main()
