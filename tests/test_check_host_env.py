"""End-to-end checks for the Step 1 environment report."""

import os
from pathlib import Path
import subprocess
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/check_host_env.sh"
TOOLS = ("gcc", "g++", "cmake", "make", "git", "dtc", "i2cdetect", "v4l2-ctl")


class HostEnvTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        (self.root / "etc").mkdir()
        (self.root / "proc/device-tree").mkdir(parents=True)
        (self.root / "lib/modules/5.15.148-tegra/build").mkdir(parents=True)
        (self.root / "etc/os-release").write_text('PRETTY_NAME="Test Linux"\n')
        (self.root / "etc/nv_tegra_release").write_text('# R36 (release), REVISION: 4.7\n')
        (self.root / "proc/device-tree/model").write_bytes(b"Test Jetson Board\x00")
        uname = self.bin / "uname"
        uname.write_text('#!/bin/sh\ncase "$1" in\n  -r) echo 5.15.148-tegra;;\n  -m) echo aarch64;;\n  -a) echo "Linux test 5.15.148-tegra aarch64";;\nesac\n')
        uname.chmod(0o755)
        for tool in TOOLS:
            (self.bin / tool).symlink_to("/bin/true")

    def run_check(self, *args):
        env = os.environ.copy()
        env["PATH"] = str(self.bin)
        env["CHECK_HOST_ENV_ROOT"] = str(self.root)
        return subprocess.run(["/bin/bash", str(SCRIPT), *args], env=env,
                              text=True, capture_output=True, check=False)

    def test_all_tools_and_board_information_pass(self):
        result = self.run_check()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("PASS gcc", result.stdout)
        self.assertIn("PASS kernel headers", result.stdout)
        self.assertIn("Test Jetson Board", result.stdout)
        self.assertIn("R36 (release), REVISION: 4.7", result.stdout)

    def test_missing_tool_fails_and_identifies_it(self):
        (self.bin / "dtc").unlink()
        result = self.run_check()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("FAIL dtc", result.stdout)
        self.assertIn("PASS gcc", result.stdout)

    def test_record_writes_board_snapshot_even_when_a_tool_is_missing(self):
        (self.bin / "v4l2-ctl").unlink()
        record = self.root / "record.txt"
        result = self.run_check("--record", str(record))
        self.assertNotEqual(result.returncode, 0)
        snapshot = record.read_text()
        self.assertIn("Test Jetson Board", snapshot)
        self.assertIn("5.15.148-tegra", snapshot)
        self.assertIn("Kernel headers present: yes", snapshot)
        self.assertNotIn("PASS", snapshot)

    def test_record_marks_missing_kernel_headers(self):
        (self.root / "lib/modules/5.15.148-tegra/build").rmdir()
        record = self.root / "record.txt"
        result = self.run_check("--record", str(record))
        self.assertEqual(result.returncode, 1)
        self.assertIn("FAIL kernel headers", result.stdout)
        snapshot = record.read_text()
        self.assertIn("Kernel headers path: ", snapshot)
        self.assertIn("Kernel headers present: no", snapshot)

    def test_missing_l4t_and_board_fail(self):
        (self.root / "etc/nv_tegra_release").unlink()
        (self.root / "proc/device-tree/model").unlink()
        result = self.run_check()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("FAIL board model", result.stdout)
        self.assertIn("FAIL L4T release", result.stdout)


if __name__ == "__main__":
    unittest.main()
