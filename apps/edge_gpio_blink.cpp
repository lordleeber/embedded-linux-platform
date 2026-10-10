// edge_gpio_blink: blink header pin 29 five times from userspace with the GPIO v2 uAPI (Step 4-a).
//
// Fixed target: /dev/gpiochip0 line 105 (PQ.05). On JP6 the pad boots
// tristated, so open it first (sudo python3 scripts/pad_pin29.py open).
// Exit status: 0 = success, 1 = cannot open the chip or request the line.
#include <cstdio>
#include <cstring>
#include <fcntl.h>
#include <linux/gpio.h>
#include <sys/ioctl.h>
#include <unistd.h>

int main()
{
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

    gpio_v2_line_values v{};
    v.mask = 1;                                    // bit 0 = the only requested line
    for (int i = 0; i < 5; i++) {
        v.bits = 1; ioctl(req.fd, GPIO_V2_LINE_SET_VALUES_IOCTL, &v); usleep(500000);
        v.bits = 0; ioctl(req.fd, GPIO_V2_LINE_SET_VALUES_IOCTL, &v); usleep(500000);
    }
    close(req.fd);                                 // release the line (ends low)
    close(chip);
    return 0;
}
