"""Behaviour checks for /dev/edge_button (Step 5-b) that need no button press.

The node exists only on an overlay boot with edge_button.ko loaded; otherwise
these tests skip, unless EDGE_BUTTON_REQUIRE=1 (set by
scripts/verify_edge_button.sh after insmod). Nobody may press the button while
they run: they rely on the event queue staying empty. Presses are checked by
the acceptance script with a person at the button.

Event layout (include/edge_button.h): u64 timestamp_ns, u32 seq, u32 pressed.
"""

import errno
import os
from pathlib import Path
import resource
import signal
import stat
import time
import unittest


DEV = Path(os.environ.get("EDGE_BUTTON_DEV", "/dev/edge_button"))
SYSFS = Path("/sys/bus/platform/devices/edge-button")
REQUIRED = os.environ.get("EDGE_BUTTON_REQUIRE") == "1"
EVENT_SIZE = 16


class Alarm(Exception):
    pass


def raise_alarm(signum, frame):
    raise Alarm()


class EdgeButtonDeviceTest(unittest.TestCase):
    def setUp(self):
        if not DEV.exists():
            if REQUIRED:
                self.fail(f"{DEV} missing but EDGE_BUTTON_REQUIRE=1")
            self.skipTest(f"{DEV} not present (overlay not applied or module not loaded)")

    def open(self, flags=os.O_RDONLY):
        fd = os.open(DEV, flags)
        self.addCleanup(os.close, fd)
        return fd

    def test_node_is_read_only_char_device(self):
        st = DEV.stat()
        self.assertTrue(stat.S_ISCHR(st.st_mode))
        self.assertEqual(stat.S_IMODE(st.st_mode), 0o444)

    def test_nonblocking_read_without_event_is_eagain(self):
        fd = self.open(os.O_RDONLY | os.O_NONBLOCK)
        with self.assertRaises(BlockingIOError):
            os.read(fd, EVENT_SIZE)

    def test_buffer_smaller_than_one_event_is_einval(self):
        fd = self.open(os.O_RDONLY | os.O_NONBLOCK)
        for size in (1, EVENT_SIZE - 1):
            with self.subTest(size=size):
                with self.assertRaises(OSError) as ctx:
                    os.read(fd, size)
                self.assertEqual(ctx.exception.errno, errno.EINVAL)

    def test_second_open_is_ebusy(self):
        # One reader owns the queue; a second one would silently steal its events.
        self.open()
        with self.assertRaises(OSError) as ctx:
            os.open(DEV, os.O_RDONLY)
        self.assertEqual(ctx.exception.errno, errno.EBUSY)

    def test_reopen_after_close_works(self):
        os.close(os.open(DEV, os.O_RDONLY))
        self.open()

    def test_blocking_read_sleeps_without_cpu_and_signal_interrupts_it(self):
        # No press for 1.5 s: read() must stay asleep (not spin) until the signal.
        fd = self.open()
        old = signal.signal(signal.SIGALRM, raise_alarm)
        self.addCleanup(signal.signal, signal.SIGALRM, old)
        cpu0 = resource.getrusage(resource.RUSAGE_SELF)
        t0 = time.monotonic()
        signal.setitimer(signal.ITIMER_REAL, 1.5)
        try:
            with self.assertRaises(Alarm):
                os.read(fd, EVENT_SIZE)
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
        elapsed = time.monotonic() - t0
        cpu1 = resource.getrusage(resource.RUSAGE_SELF)
        cpu = (cpu1.ru_utime - cpu0.ru_utime) + (cpu1.ru_stime - cpu0.ru_stime)
        self.assertGreaterEqual(elapsed, 1.4)
        self.assertLess(cpu, 0.1, f"read() used {cpu:.3f} s CPU while blocked")

    def test_fd_still_usable_after_interrupted_read(self):
        fd = self.open()
        old = signal.signal(signal.SIGALRM, raise_alarm)
        self.addCleanup(signal.signal, signal.SIGALRM, old)
        signal.setitimer(signal.ITIMER_REAL, 0.2)
        try:
            with self.assertRaises(Alarm):
                os.read(fd, EVENT_SIZE)
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
        os.set_blocking(fd, False)
        with self.assertRaises(BlockingIOError):
            os.read(fd, EVENT_SIZE)

    def test_counters_are_exposed_in_sysfs(self):
        for name in ("irq_count", "event_count", "dropped"):
            with self.subTest(name=name):
                text = (SYSFS / name).read_text()
                self.assertRegex(text, r"^\d+\n$")


if __name__ == "__main__":
    unittest.main()
