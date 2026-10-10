"""Tests for scripts/install_edge_gpio_overlay.py against fake extlinux.conf files.

The fixture mirrors this Jetson's real /boot/extlinux/extlinux.conf layout:
DEFAULT points at the JetsonIO label, which already carries an IMX219 overlay.
"""

from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "install_edge_gpio_overlay.py"
ENTRY = "/boot/edge-gpio-overlay.dtbo"

JETSONIO = """TIMEOUT 30
DEFAULT JetsonIO

MENU TITLE L4T boot options

LABEL primary
      MENU LABEL primary kernel
      LINUX /boot/Image
      INITRD /boot/initrd
      APPEND ${cbootargs} root=PARTUUID=x rw

# LABEL backup
#    MENU LABEL backup kernel
#    LINUX /boot/Image.backup

LABEL JetsonIO
\tMENU LABEL Custom Header Config: <CSI Camera IMX219-A>
\tLINUX /boot/Image
\tFDT /boot/dtb/kernel_tegra234-p3768-0000+p3767-0005-nv-super.dtb
\tINITRD /boot/initrd
\tAPPEND ${cbootargs} root=PARTUUID=x rw
\tOVERLAYS /boot/tegra234-p3767-camera-p3768-imx219-A.dtbo
"""

PRIMARY_ONLY = """TIMEOUT 30
DEFAULT primary

LABEL primary
      MENU LABEL primary kernel
      LINUX /boot/Image
      INITRD /boot/initrd
      APPEND ${cbootargs} root=PARTUUID=x rw

# LABEL backup
#    LINUX /boot/Image.backup
"""


class InstallOverlayTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.conf = self.dir / "extlinux.conf"
        self.boot = self.dir / "boot"
        self.boot.mkdir()
        self.dtbo = self.dir / "src.dtbo"
        self.dtbo.write_bytes(b"\xd0\x0d\xfe\xed fake")

    def tearDown(self):
        self.tmp.cleanup()

    def run_script(self, *args):
        return subprocess.run([sys.executable, str(SCRIPT), "--extlinux", str(self.conf),
                               "--boot-dir", str(self.boot), *args],
                              capture_output=True, text=True)

    def label_block(self, text, label):
        lines, out, inside = text.splitlines(), [], False
        for line in lines:
            if line.strip().startswith("LABEL "):
                inside = line.split()[1] == label
            if inside:
                out.append(line)
        return "\n".join(out)

    def test_appends_to_existing_overlays_of_default_label(self):
        self.conf.write_text(JETSONIO)
        res = self.run_script("install", str(self.dtbo))
        self.assertEqual(res.returncode, 0, res.stderr)
        block = self.label_block(self.conf.read_text(), "JetsonIO")
        self.assertIn(f"\tOVERLAYS /boot/tegra234-p3767-camera-p3768-imx219-A.dtbo,{ENTRY}\n"
                      .rstrip("\n"), block)
        self.assertNotIn(ENTRY, self.label_block(self.conf.read_text(), "primary"))

    def test_copies_dtbo_and_keeps_backup(self):
        self.conf.write_text(JETSONIO)
        self.assertEqual(self.run_script("install", str(self.dtbo)).returncode, 0)
        self.assertEqual((self.boot / "edge-gpio-overlay.dtbo").read_bytes(), self.dtbo.read_bytes())
        self.assertEqual((self.dir / "extlinux.conf.edge-gpio.bak").read_text(), JETSONIO)

    def test_install_twice_is_idempotent_and_backup_is_the_original(self):
        self.conf.write_text(JETSONIO)
        self.run_script("install", str(self.dtbo))
        once = self.conf.read_text()
        res = self.run_script("install", str(self.dtbo))
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(self.conf.read_text(), once)
        self.assertEqual(self.conf.read_text().count(ENTRY), 1)
        self.assertEqual((self.dir / "extlinux.conf.edge-gpio.bak").read_text(), JETSONIO)

    def test_adds_overlays_line_when_default_label_has_none(self):
        self.conf.write_text(PRIMARY_ONLY)
        res = self.run_script("install", str(self.dtbo))
        self.assertEqual(res.returncode, 0, res.stderr)
        block = self.label_block(self.conf.read_text(), "primary")
        self.assertIn(f"      OVERLAYS {ENTRY}", block)
        # The new line belongs to the label, before the trailing comment block.
        text = self.conf.read_text()
        self.assertLess(text.index("OVERLAYS"), text.index("# LABEL backup"))

    def test_remove_restores_original_text(self):
        for original in (JETSONIO, PRIMARY_ONLY):
            with self.subTest(original=original.splitlines()[1]):
                self.conf.write_text(original)
                self.run_script("install", str(self.dtbo))
                res = self.run_script("remove")
                self.assertEqual(res.returncode, 0, res.stderr)
                self.assertEqual(self.conf.read_text(), original)
                self.assertFalse((self.boot / "edge-gpio-overlay.dtbo").exists())

    def test_remove_when_not_installed_is_noop(self):
        self.conf.write_text(JETSONIO)
        res = self.run_script("remove")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(self.conf.read_text(), JETSONIO)

    def test_missing_default_label_is_an_error_and_file_untouched(self):
        broken = JETSONIO.replace("DEFAULT JetsonIO", "DEFAULT nosuch")
        self.conf.write_text(broken)
        res = self.run_script("install", str(self.dtbo))
        self.assertEqual(res.returncode, 1)
        self.assertEqual(self.conf.read_text(), broken)
        self.assertFalse((self.boot / "edge-gpio-overlay.dtbo").exists())

    def test_empty_overlays_line_keeps_the_next_line_intact(self):
        # "\tOVERLAYS\n": a \s+ in the pattern would swallow the newline and glue the
        # entry onto the following line.
        conf = JETSONIO.replace("\tOVERLAYS /boot/tegra234-p3767-camera-p3768-imx219-A.dtbo\n",
                                "\tOVERLAYS\n") + "LABEL after\n      LINUX /boot/Image\n"
        self.conf.write_text(conf)
        res = self.run_script("install", str(self.dtbo))
        self.assertEqual(res.returncode, 0, res.stderr)
        text = self.conf.read_text()
        self.assertIn(f"\tOVERLAYS {ENTRY}\n", text)
        self.assertIn("\nLABEL after\n", text)

    def test_unparseable_overlays_line_is_refused(self):
        # Spaces in the value: never add a second OVERLAYS line next to it.
        broken = JETSONIO.replace("imx219-A.dtbo", "imx219-A.dtbo, /boot/other.dtbo")
        self.conf.write_text(broken)
        res = self.run_script("install", str(self.dtbo))
        self.assertEqual(res.returncode, 1, res.stdout + res.stderr)
        self.assertEqual(self.conf.read_text(), broken)
        self.assertFalse((self.boot / "edge-gpio-overlay.dtbo").exists())

    def test_remove_strips_the_entry_from_every_label(self):
        # DEFAULT may have moved since install; the dtbo is deleted, so no label may keep it.
        conf = JETSONIO.replace("      APPEND ${cbootargs} root=PARTUUID=x rw\n",
                                f"      APPEND ${{cbootargs}} root=PARTUUID=x rw\n      OVERLAYS {ENTRY}\n", 1)
        self.conf.write_text(conf)
        self.assertEqual(self.run_script("install", str(self.dtbo)).returncode, 0)
        res = self.run_script("remove")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertNotIn(ENTRY, self.conf.read_text())

    def test_write_is_atomic_and_keeps_mode(self):
        # Written through a temp file + rename: nothing left behind, permissions kept.
        self.conf.write_text(JETSONIO)
        self.conf.chmod(0o640)
        self.assertEqual(self.run_script("install", str(self.dtbo)).returncode, 0)
        self.assertEqual(self.conf.stat().st_mode & 0o777, 0o640)
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()),
                         ["boot", "extlinux.conf", "extlinux.conf.edge-gpio.bak", "src.dtbo"])

    def test_usage_errors_exit_2(self):
        self.conf.write_text(JETSONIO)
        self.assertEqual(self.run_script().returncode, 2)
        self.assertEqual(self.run_script("install").returncode, 2)
        self.assertEqual(self.run_script("install", str(self.dir / "nope.dtbo")).returncode, 2)
        self.conf.unlink()
        self.assertEqual(self.run_script("install", str(self.dtbo)).returncode, 2)


if __name__ == "__main__":
    unittest.main()
