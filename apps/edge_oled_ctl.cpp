// edge_oled_ctl: draw on the OLED through /dev/edge_oled (Step 10-a, kernel/edge_oled).
//
// The driver owns the I2C transfers; this program only hands it a frame (write) or asks it
// to clear / fill the frame (ioctl, include/edge_oled.h). The pictures are Step 9's
// (ssd1306::test_picture), so the panel can be compared with Step 9's baseline.
//
// Usage: edge_oled_ctl [--dev PATH] clear|fill 0xNN|pixel|pattern|edge
//   clear    ioctl EDGE_OLED_IOC_CLEAR: all pixels off
//   fill N   ioctl EDGE_OLED_IOC_FILL: every frame byte = N (0xff all on, 0x55 stripes)
//   pixel / pattern / edge   one 1024-byte write() of that picture
// Exit status: 0 = done, 1 = open / write / ioctl failed, 2 = usage.
#include <cerrno>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fcntl.h>
#include <sys/ioctl.h>
#include <unistd.h>

#include "edge_oled.h"
#include "ssd1306.h"

static_assert(EDGE_OLED_FRAME_SIZE == sizeof(ssd1306::Frame), "frame layout = GDDRAM");

namespace {

int usage(const char *argv0)
{
    std::fprintf(stderr, "usage: %s [--dev PATH] clear|fill 0xNN|pixel|pattern|edge\n", argv0);
    return 2;
}

}  // namespace

int main(int argc, char **argv)
{
    const char *dev = "/dev/edge_oled";
    int i = 1;
    if (i < argc && !std::strcmp(argv[i], "--dev")) {
        if (i + 1 >= argc)
            return usage(argv[0]);
        dev = argv[i + 1];
        i += 2;
    }
    if (i >= argc)
        return usage(argv[0]);
    const char *cmd = argv[i++];
    long fill = -1;
    if (!std::strcmp(cmd, "fill")) {
        char *end = nullptr;
        if (i >= argc)
            return usage(argv[0]);
        errno = 0;
        fill = std::strtol(argv[i], &end, 0);
        if (errno || end == argv[i] || *end || fill < 0 || fill > 0xFF)
            return usage(argv[0]);
        ++i;
    } else if (std::strcmp(cmd, "clear") && std::strcmp(cmd, "pixel") &&
               std::strcmp(cmd, "pattern") && std::strcmp(cmd, "edge")) {
        return usage(argv[0]);
    }
    if (i != argc)
        return usage(argv[0]);

    int fd = open(dev, O_WRONLY);
    if (fd < 0) {
        std::fprintf(stderr, "open %s: %s\n", dev, std::strerror(errno));
        return 1;
    }
    int ret;
    const char *what;
    if (!std::strcmp(cmd, "clear")) {
        what = "ioctl CLEAR";
        ret = ioctl(fd, EDGE_OLED_IOC_CLEAR);
    } else if (fill >= 0) {
        what = "ioctl FILL";
        __u8 v = static_cast<__u8>(fill);
        ret = ioctl(fd, EDGE_OLED_IOC_FILL, &v);
    } else {
        what = "write";
        ssd1306::Frame f = ssd1306::test_picture(cmd);
        ssize_t n = write(fd, f.data(), f.size());
        ret = n == static_cast<ssize_t>(f.size()) ? 0 : -1;
        if (n >= 0 && ret)
            errno = EIO;   // short write: the driver takes whole frames only
    }
    if (ret < 0) {
        // No ACK from the OLED (unplugged) arrives here as EREMOTEIO from the driver.
        std::fprintf(stderr, "%s %s: %s\n", what, dev, std::strerror(errno));
        close(fd);
        return 1;
    }
    close(fd);
    std::printf("%s: %s on %s\n", cmd, what, dev);
    return 0;
}
