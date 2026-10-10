"""Behaviour checks for /dev/edge_gpio (Step 4).

The node only exists when the edge-gpio overlay is applied at boot and
edge_gpio.ko is loaded. Without it these tests skip, unless EDGE_GPIO_REQUIRE=1
is set (scripts/verify_edge_gpio.sh sets it after insmod on an overlay boot).

The file interface is logical: "1" means LED on whatever the DT polarity is.
The physical pin level is checked by the acceptance script via debugfs (root).
"""

import errno
import os
from pathlib import Path
import stat
import unittest


DEV = Path(os.environ.get("EDGE_GPIO_DEV", "/dev/edge_gpio"))
REQUIRED = os.environ.get("EDGE_GPIO_REQUIRE") == "1"


def write(data):
    fd = os.open(DEV, os.O_WRONLY)
    try:
        return os.write(fd, data)
    finally:
        os.close(fd)


def read_all():
    fd = os.open(DEV, os.O_RDONLY)
    try:
        parts = []
        while True:
            part = os.read(fd, 64)
            if not part:
                return b"".join(parts)
            parts.append(part)
    finally:
        os.close(fd)


class EdgeGpioDeviceTest(unittest.TestCase):
    def setUp(self):
        if not DEV.exists():
            if REQUIRED:
                self.fail(f"{DEV} missing but EDGE_GPIO_REQUIRE=1")
            self.skipTest(f"{DEV} not present (overlay not applied or module not loaded)")
        self.addCleanup(write, b"0")

    def test_node_is_char_device_0666(self):
        st = DEV.stat()
        self.assertTrue(stat.S_ISCHR(st.st_mode))
        self.assertEqual(stat.S_IMODE(st.st_mode), 0o666)

    def test_on_then_off_reads_back(self):
        self.assertEqual(write(b"1"), 1)
        self.assertEqual(read_all(), b"1\n")
        self.assertEqual(write(b"0"), 1)
        self.assertEqual(read_all(), b"0\n")

    def test_shell_style_trailing_newline_is_accepted(self):
        self.assertEqual(write(b"1\n"), 2)
        self.assertEqual(read_all(), b"1\n")

    def test_state_survives_reopen(self):
        write(b"1")
        self.assertEqual(read_all(), b"1\n")
        self.assertEqual(read_all(), b"1\n")

    def test_read_is_two_bytes_then_eof(self):
        fd = os.open(DEV, os.O_RDONLY)
        try:
            self.assertEqual(len(os.read(fd, 1)), 1)
            self.assertEqual(os.read(fd, 64), b"\n")
            self.assertEqual(os.read(fd, 64), b"")
        finally:
            os.close(fd)

    def test_invalid_values_are_rejected_and_state_kept(self):
        write(b"1")
        for bad in (b"2", b"-1", b"on", b"", b"\n", b"10", b"1 1"):
            with self.subTest(bad=bad):
                with self.assertRaises(OSError) as ctx:
                    write(bad)
                self.assertEqual(ctx.exception.errno, errno.EINVAL)
                self.assertEqual(read_all(), b"1\n")


if __name__ == "__main__":
    unittest.main()
