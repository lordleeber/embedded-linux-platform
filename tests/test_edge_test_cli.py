"""Checks for the Step 3 userspace side: shared ioctl header and edge_test_cli.

Usage-error and missing-device cases run anywhere. Cases that need the real
device are skipped unless /dev/edge_test exists (or EDGE_TEST_REQUIRE=1).
The CLI is built with CMake into build/ on first use.
"""

import os
from pathlib import Path
import shutil
import subprocess
import unittest


REPO = Path(__file__).resolve().parents[1]
HEADER = REPO / "include/edge_test_ioctl.h"
BUILD = REPO / "build"
CLI = BUILD / "edge_test_cli"
DEV = Path(os.environ.get("EDGE_TEST_DEV", "/dev/edge_test"))
REQUIRED = os.environ.get("EDGE_TEST_REQUIRE") == "1"


def build_cli():
    subprocess.run(["cmake", "-S", str(REPO), "-B", str(BUILD)], check=True, capture_output=True)
    subprocess.run(["cmake", "--build", str(BUILD)], check=True, capture_output=True)


def cli(*args):
    return subprocess.run([str(CLI), *args], text=True, capture_output=True, check=False)


class HeaderTest(unittest.TestCase):
    def compile_header(self, compiler, lang):
        src = f'#include "{HEADER.name}"\nint main(void) {{ return EDGE_TEST_GET_VALUE == EDGE_TEST_SET_VALUE; }}\n'
        return subprocess.run([compiler, "-x", lang, "-std=" + ("c11" if lang == "c" else "c++17"),
                               "-Wall", "-Werror", "-fsyntax-only", "-I", str(HEADER.parent), "-"],
                              input=src, text=True, capture_output=True, check=False)

    def test_header_compiles_as_c(self):
        result = self.compile_header("gcc", "c")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_header_compiles_as_cxx(self):
        result = self.compile_header("g++", "c++")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_header_uses_only_fixed_size_types(self):
        text = HEADER.read_text()
        for banned in ("unsigned long", "unsigned int", " long ", "size_t", " int "):
            self.assertNotIn(banned, text, f"ioctl header must not use {banned.strip()!r}")


class CliUsageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        build_cli()

    def assert_usage_error(self, *args):
        result = cli(*args)
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("usage:", result.stderr)
        self.assertEqual(result.stdout, "")

    def test_no_arguments(self):
        self.assert_usage_error()

    def test_unknown_command(self):
        self.assert_usage_error("frob")

    def test_set_without_value(self):
        self.assert_usage_error("set")

    def test_set_rejects_bad_numbers(self):
        for bad in ("abc", "-1", "12x", "", "4294967296", "0x10"):
            with self.subTest(value=bad):
                self.assert_usage_error("set", bad)

    def test_get_takes_no_value(self):
        self.assert_usage_error("get", "1")

    def test_missing_device_is_runtime_error(self):
        result = cli("--device", "/nonexistent/edge_test", "get")
        self.assertEqual(result.returncode, 1)
        self.assertIn("/nonexistent/edge_test", result.stderr)
        self.assertIn("No such file or directory", result.stderr)


@unittest.skipUnless(REQUIRED or DEV.exists(), f"{DEV} not present; load the module or set EDGE_TEST_REQUIRE=1")
class CliDeviceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        build_cli()

    def test_set_then_get(self):
        for value in ("123", "0", "4294967295"):
            with self.subTest(value=value):
                self.assertEqual(cli("--device", str(DEV), "set", value).returncode, 0)
                result = cli("--device", str(DEV), "get")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, value + "\n")


if __name__ == "__main__":
    unittest.main()
