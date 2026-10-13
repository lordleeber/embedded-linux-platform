"""Checks against a bound edge_oled (Step 10-a): /dev/edge_oled on the real SSD1306.

The client <bus>-003c comes from the overlay's oled@3c node under gen2_i2c
(c240000.i2c, i2c-1 on this board); edge_oled.ko binds it after insmod and
creates /dev/edge_oled. Without the device these tests skip, unless
EDGE_OLED_REQUIRE=1 (set by scripts/verify_edge_oled.sh after insmod);
EDGE_OLED_BUS overrides the bus number.

Interface (include/edge_oled.h): write() takes exactly one 1024-byte frame in
GDDRAM layout and sends it; read() returns the driver's copy of the frame (the
chip itself cannot be read over I2C); ioctl CLEAR = _IO(0xEB, 0x10), FILL =
_IOW(0xEB, 0x11, __u8) sets every byte. These tests change the picture; the
verify script asks a person what the panel shows.
"""

import errno
import fcntl
import os
from pathlib import Path
import stat
import struct
import subprocess
import time
import unittest


REPO = Path(__file__).resolve().parents[1]
BUS = int(os.environ.get("EDGE_OLED_BUS", "1"))
CLIENT = Path(f"/sys/bus/i2c/devices/{BUS}-003c")
DEV = Path("/dev/edge_oled")
PROBE = REPO / "build" / "oled_probe"
REQUIRED = os.environ.get("EDGE_OLED_REQUIRE") == "1"
FRAME = 1024
MAGIC = 0xEB
IOC_CLEAR = (MAGIC << 8) | 0x10                                   # _IO
IOC_FILL = (1 << 30) | (1 << 16) | (MAGIC << 8) | 0x11            # _IOW(.., __u8)


class EdgeOledDeviceTest(unittest.TestCase):
    def setUp(self):
        if not DEV.exists():
            if REQUIRED:
                self.fail(f"{DEV} missing with EDGE_OLED_REQUIRE=1")
            self.skipTest(f"{DEV} missing: edge_oled not bound")
        self.fd = os.open(DEV, os.O_RDWR)
        self.addCleanup(os.close, self.fd)

    def shadow(self):
        return os.pread(self.fd, FRAME + 1, 0)

    def test_bound_to_edge_oled(self):
        self.assertEqual(os.path.basename(os.readlink(CLIENT / "driver")), "edge_oled")

    def test_char_device_mode(self):
        st = os.stat(DEV)
        self.assertTrue(stat.S_ISCHR(st.st_mode))
        self.assertEqual(stat.S_IMODE(st.st_mode), 0o666)

    def test_write_then_read_back(self):
        frame = bytes((i * 7) & 0xFF for i in range(FRAME))
        self.assertEqual(os.write(self.fd, frame), FRAME)
        self.assertEqual(self.shadow(), frame)

    def test_wrong_size_is_einval_and_keeps_the_frame(self):
        os.write(self.fd, b"\x55" * FRAME)
        for n in (0, 1, FRAME - 1, FRAME + 1, 128):
            with self.subTest(n=n), self.assertRaises(OSError) as cm:
                os.write(self.fd, b"\xff" * n)
            self.assertEqual(cm.exception.errno, errno.EINVAL)
        self.assertEqual(self.shadow(), b"\x55" * FRAME)

    def test_clear_and_fill(self):
        fcntl.ioctl(self.fd, IOC_FILL, struct.pack("B", 0xAA))
        self.assertEqual(self.shadow(), b"\xaa" * FRAME)
        fcntl.ioctl(self.fd, IOC_CLEAR)
        self.assertEqual(self.shadow(), b"\x00" * FRAME)

    def test_unknown_ioctl_is_enotty(self):
        with self.assertRaises(OSError) as cm:
            fcntl.ioctl(self.fd, (MAGIC << 8) | 0x7F)
        self.assertEqual(cm.exception.errno, errno.ENOTTY)

    def test_oled_probe_refuses_while_bound(self):
        if not PROBE.exists():
            if REQUIRED:
                self.fail(f"{PROBE} missing")
            self.skipTest(f"{PROBE} missing")
        r = subprocess.run([str(PROBE), "--bus", str(BUS), "edge"], capture_output=True,
                           text=True, timeout=10)
        self.assertEqual(r.returncode, 1)
        self.assertIn("edge_oled", r.stderr)

    def test_200_frames_in_a_row(self):
        # Each write is window + 8 page messages; a flaky transfer anywhere fails it.
        t0 = time.monotonic()
        for n in range(200):
            self.assertEqual(os.write(self.fd, bytes([n & 0xFF]) * FRAME), FRAME, f"frame {n}")
        per_frame = (time.monotonic() - t0) / 200
        print(f"\n    {per_frame * 1000:.1f} ms per frame", end=" ")
        fcntl.ioctl(self.fd, IOC_CLEAR)


if __name__ == "__main__":
    unittest.main()
