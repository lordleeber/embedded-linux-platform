// edge_gpio_blink: blink header pin 29 five times from userspace with the GPIO v2 uAPI (Step 4-a).
//
// Fixed target: /dev/gpiochip0 line 105 (PQ.05). On JP6 the pad boots
// tristated, so open it first (sudo python3 scripts/pad_pin29.py open).
// Ctrl-C / SIGTERM stop the blinking early; the line is still written low
// before it is released, because Tegra keeps the last value after release.
// Exit status: 0 = five blinks done, 1 = chip/line error or interrupted.
#include <csignal>
#include <cstdio>
#include <cstring>
#include <fcntl.h>
#include <linux/gpio.h>
#include <sys/ioctl.h>
#include <unistd.h>

namespace {

volatile std::sig_atomic_t stop = 0;

void on_signal(int)
{
    stop = 1;  // usleep() returns early with EINTR; the loop then exits
}

}  // namespace

int main()
{
    std::signal(SIGINT, on_signal);
    std::signal(SIGTERM, on_signal);

    int chip = open("/dev/gpiochip0", O_RDWR);
    if (chip < 0) {
        perror("open /dev/gpiochip0");
        return 1;
    }

    gpio_v2_line_request req{};
    req.offsets[0] = 105;                          // PQ.05 = header pin 29
    req.num_lines = 1;
    req.config.flags = GPIO_V2_LINE_FLAG_OUTPUT;   // starts low
    std::strcpy(req.consumer, "edge_gpio_blink");  // shown by gpioinfo
    if (ioctl(chip, GPIO_V2_GET_LINE_IOCTL, &req) < 0) {
        perror("request line 105");                // EBUSY while another user holds it
        close(chip);
        return 1;
    }

    int rc = 0;
    gpio_v2_line_values v{};
    v.mask = 1;                                    // bit 0 = the only requested line
    for (int i = 0; i < 10 && !stop; i++) {
        v.bits = (i % 2 == 0);                     // on, off, on, off, ...
        if (ioctl(req.fd, GPIO_V2_LINE_SET_VALUES_IOCTL, &v) < 0) {
            perror("set line 105");
            rc = 1;
            break;
        }
        usleep(500000);
    }
    v.bits = 0;                                    // always end low, whatever stopped the loop
    if (ioctl(req.fd, GPIO_V2_LINE_SET_VALUES_IOCTL, &v) < 0) {
        perror("set line 105 low");
        rc = 1;
    }
    if (stop) {
        std::fputs("interrupted\n", stderr);
        rc = 1;
    }
    close(req.fd);                                 // release the line
    close(chip);
    return rc;
}
