// oled_probe: bring up a 128x64 SSD1306 OLED from userspace through /dev/i2c-N (Step 9).
//
// No driver: i2c-dev hands us the bus and every message is one I2C_RDWR write of
// [control byte][stream] (see ssd1306.h). Each run sends the full init sequence, the
// whole frame and then Display ON, so it works on a panel that has just been powered up
// as well as on one a previous program left in any state. The chip cannot be read back
// over I2C; a person checks the picture (scripts/verify_oled_probe.sh).
//
// Usage: oled_probe [--bus N] [--addr 0xNN] [--force] [clear|pixel|pattern|edge|off]
//   default: bus 1 (header pins 27/28), address 0x3C, mode edge
//   --force  write even when a kernel driver (Step 10-a's edge_oled) is bound to the address
//   clear   blank screen, display on
//   pixel   the four corners and the centre (128x64: (0,0) (127,0) (0,63) (127,63) (64,32))
//   pattern 1-pixel border and a diagonal from the top-left corner
//   edge    "EDGE", 4x scaled, centred
//   off     display off (RAM kept); no init
// Exit status: 0 = done, 1 = bus or I/O error, or the address is bound to a driver, 2 = usage.
#include <cerrno>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fcntl.h>
#include <linux/i2c-dev.h>
#include <linux/i2c.h>
#include <string>
#include <sys/ioctl.h>
#include <unistd.h>
#include <vector>

#include "ssd1306.h"

namespace {

int usage(const char *argv0)
{
    std::fprintf(stderr,
                 "usage: %s [--bus N] [--addr 0x03..0x77] [--force] [clear|pixel|pattern|edge|off]\n",
                 argv0);
    return 2;
}

// base 10 for the bus (i2c-N; "010" is not octal), 0 for the address ("0x3c").
bool parse(const char *s, int base, long lo, long hi, long *out)
{
    char *end = nullptr;
    errno = 0;
    long v = std::strtol(s, &end, base);
    if (errno || end == s || *end || v < lo || v > hi)
        return false;
    *out = v;
    return true;
}

// One write message; the controller sends START, address+W, the bytes, STOP.
bool write_msg(int fd, std::uint16_t addr, std::vector<std::uint8_t> &bytes)
{
    i2c_msg msg{};
    msg.addr = addr;
    msg.flags = 0;
    msg.len = static_cast<std::uint16_t>(bytes.size());
    msg.buf = bytes.data();
    i2c_rdwr_ioctl_data xfer{&msg, 1};
    int done = ioctl(fd, I2C_RDWR, &xfer);
    if (done != 1) {
        if (done >= 0)
            errno = EIO;   // nothing transferred, errno not set
        return false;
    }
    return true;
}

// Step 10-a: with edge_oled.ko bound to this address, I2C_RDWR would still reach the chip
// (it never claims the address, so no EBUSY) and re-init it under the driver. Returns the
// driver's name, or "" when the client does not exist or is unbound. OLED_PROBE_SYSFS
// replaces /sys (tests).
std::string bound_driver(long bus, long addr)
{
    const char *root = std::getenv("OLED_PROBE_SYSFS");
    char link[256], target[256];
    std::snprintf(link, sizeof link, "%s/bus/i2c/devices/%ld-%04lx/driver", root ? root : "/sys",
                  bus, addr);
    ssize_t n = readlink(link, target, sizeof target - 1);
    if (n <= 0)
        return "";
    target[n] = '\0';
    const char *slash = std::strrchr(target, '/');
    return slash ? slash + 1 : target;
}

}  // namespace

int main(int argc, char **argv)
{
    long bus = 1, addr = 0x3C;
    std::string mode;
    bool force = false;
    for (int i = 1; i < argc; ++i) {
        if (!std::strcmp(argv[i], "--force")) {
            force = true;
        } else if (!std::strcmp(argv[i], "--bus") || !std::strcmp(argv[i], "--addr")) {
            bool is_bus = argv[i][2] == 'b';
            if (i + 1 >= argc ||
                !parse(argv[i + 1], is_bus ? 10 : 0, is_bus ? 0 : 0x03, is_bus ? 255 : 0x77,
                       is_bus ? &bus : &addr))
                return usage(argv[0]);
            ++i;
        } else if (mode.empty() && (!std::strcmp(argv[i], "clear") || !std::strcmp(argv[i], "pixel") ||
                                    !std::strcmp(argv[i], "pattern") || !std::strcmp(argv[i], "edge") ||
                                    !std::strcmp(argv[i], "off"))) {
            mode = argv[i];
        } else {
            return usage(argv[0]);
        }
    }
    if (mode.empty())
        mode = "edge";

    std::string drv = force ? "" : bound_driver(bus, addr);
    if (!drv.empty()) {
        std::fprintf(stderr, "%ld-%04lx is bound to driver %s (%s): use its interface, or --force\n",
                     bus, addr, drv.c_str(), std::strerror(EBUSY));
        return 1;
    }

    char path[32];
    std::snprintf(path, sizeof path, "/dev/i2c-%ld", bus);
    int fd = open(path, O_RDWR);
    if (fd < 0) {
        std::fprintf(stderr, "open %s: %s\n", path, std::strerror(errno));
        return 1;
    }

    const auto a = static_cast<std::uint16_t>(addr);
    std::vector<std::vector<std::uint8_t>> msgs;
    if (mode == "off") {
        msgs.push_back(ssd1306::command_frame({ssd1306::kDisplayOff}));
    } else {
        msgs.push_back(ssd1306::command_frame(ssd1306::init_sequence()));
        for (auto &m : ssd1306::frame_writes(ssd1306::test_picture(mode.c_str())))
            msgs.push_back(std::move(m));
        msgs.push_back(ssd1306::command_frame({ssd1306::kDisplayOn}));
    }
    for (std::size_t n = 0; n < msgs.size(); ++n) {
        if (!write_msg(fd, a, msgs[n])) {
            // No ACK (OLED unplugged or unpowered, wrong address) is EREMOTEIO.
            std::fprintf(stderr, "%s addr 0x%02lx message %zu of %zu: %s\n", path, addr, n + 1,
                         msgs.size(), std::strerror(errno));
            close(fd);
            return 1;
        }
    }
    close(fd);
    std::printf("%s: %zu messages to 0x%02lx on %s\n", mode.c_str(), msgs.size(), addr, path);
    return 0;
}
