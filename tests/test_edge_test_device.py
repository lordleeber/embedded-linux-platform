"""Behaviour checks for /dev/edge_test (Step 2).

These tests talk to the real character device. They are skipped when the
module is not loaded, unless EDGE_TEST_REQUIRE=1 is set (the acceptance
script scripts/verify_edge_test.sh sets it after insmod).
"""

import ctypes
import errno
import os
from pathlib import Path
import stat
import subprocess
import unittest


DEV = Path(os.environ.get("EDGE_TEST_DEV", "/dev/edge_test"))
BUF_SIZE = 256
REQUIRED = os.environ.get("EDGE_TEST_REQUIRE") == "1"


def write_fresh(data):
    fd = os.open(DEV, os.O_WRONLY | os.O_TRUNC)
    try:
        return os.write(fd, data)
    finally:
        os.close(fd)


def read_all(chunk=4096):
    fd = os.open(DEV, os.O_RDONLY)
    try:
        parts = []
        while True:
            part = os.read(fd, chunk)
            if not part:
                return b"".join(parts)
            parts.append(part)
    finally:
        os.close(fd)


@unittest.skipUnless(REQUIRED or DEV.exists(),
                     f"{DEV} not present; load the module or set EDGE_TEST_REQUIRE=1")
class EdgeTestDeviceTest(unittest.TestCase):
    def setUp(self):
        write_fresh(b"")

    def test_node_is_world_rw_char_device(self):
        st = DEV.stat()
        self.assertTrue(stat.S_ISCHR(st.st_mode))
        self.assertEqual(stat.S_IMODE(st.st_mode), 0o666)

    def test_write_then_read_round_trip(self):
        self.assertEqual(write_fresh(b"hello\n"), 6)
        self.assertEqual(read_all(), b"hello\n")

    def test_read_reaches_eof(self):
        write_fresh(b"abc")
        fd = os.open(DEV, os.O_RDONLY)
        try:
            self.assertEqual(os.read(fd, 100), b"abc")
            self.assertEqual(os.read(fd, 100), b"")
        finally:
            os.close(fd)

    def test_small_reads_reassemble_the_buffer(self):
        write_fresh(b"0123456789")
        self.assertEqual(read_all(chunk=3), b"0123456789")

    def test_o_trunc_discards_previous_content(self):
        write_fresh(b"hello world")
        write_fresh(b"hi")
        self.assertEqual(read_all(), b"hi")

    def test_open_for_read_keeps_content(self):
        write_fresh(b"keep")
        read_all()
        self.assertEqual(read_all(), b"keep")

    def test_sequential_writes_append_within_one_open(self):
        fd = os.open(DEV, os.O_WRONLY | os.O_TRUNC)
        try:
            os.write(fd, b"he")
            os.write(fd, b"llo")
        finally:
            os.close(fd)
        self.assertEqual(read_all(), b"hello")

    def test_exact_capacity_fits(self):
        data = bytes(range(256))
        self.assertEqual(write_fresh(data), BUF_SIZE)
        self.assertEqual(read_all(), data)

    def test_overflow_is_short_write_then_enospc(self):
        data = b"x" * 200 + b"y" * 100
        fd = os.open(DEV, os.O_WRONLY | os.O_TRUNC)
        try:
            self.assertEqual(os.write(fd, data), BUF_SIZE)
            with self.assertRaises(OSError) as ctx:
                os.write(fd, b"z")
            self.assertEqual(ctx.exception.errno, errno.ENOSPC)
        finally:
            os.close(fd)
        self.assertEqual(read_all(), data[:BUF_SIZE])

    def test_bad_user_pointer_returns_efault_and_keeps_buffer(self):
        write_fresh(b"safe")
        libc = ctypes.CDLL(None, use_errno=True)
        libc.write.argtypes = (ctypes.c_int, ctypes.c_void_p, ctypes.c_size_t)
        libc.read.argtypes = (ctypes.c_int, ctypes.c_void_p, ctypes.c_size_t)
        bad = ctypes.c_void_p(1)

        fd = os.open(DEV, os.O_WRONLY)
        try:
            self.assertEqual(libc.write(fd, bad, 4), -1)
            self.assertEqual(ctypes.get_errno(), errno.EFAULT)
        finally:
            os.close(fd)

        fd = os.open(DEV, os.O_RDONLY)
        try:
            self.assertEqual(libc.read(fd, bad, 4), -1)
            self.assertEqual(ctypes.get_errno(), errno.EFAULT)
        finally:
            os.close(fd)
        self.assertEqual(read_all(), b"safe")

    def test_shell_echo_and_cat(self):
        subprocess.run(["sh", "-c", f"echo hello > {DEV}"], check=True)
        out = subprocess.run(["cat", str(DEV)], check=True, capture_output=True)
        self.assertEqual(out.stdout, b"hello\n")

    def test_shell_overflow_reports_error(self):
        result = subprocess.run(["sh", "-c", f"head -c 300 /dev/zero > {DEV}"],
                                capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("No space left on device", result.stderr)
        self.assertEqual(read_all(), b"\0" * BUF_SIZE)


if __name__ == "__main__":
    unittest.main()
