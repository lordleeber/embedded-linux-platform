// edge_gpio_button: wait for button presses on header pin 33 from userspace (Step 5-a).
//
// No driver of ours: gpiolib-cdev, the kernel's GPIO character device, does the
// IRQ, debounce, queue and wait queue that Step 5-b's edge_button.ko writes by
// hand. We request /dev/gpiochip0 line 43 (PH.00) as an active-low input with
// both edges and a 20 ms debounce, then read() the line request fd.
//
// Usage: edge_gpio_button [count]    count >= 1, default 1
// Same output as edge_button_wait: "seq=3 pressed t=1234.567890123", where seq counts
// the presses/releases printed. A gap in the kernel's own seqno (gpiolib-cdev dropped
// events) is reported on stderr as "lost". A press that starts during the 50 ms settle
// is taken as the initial state, so the first event printed is then its release.
// EDGE_GPIO_CHIP overrides the chip path (tests).
// Exit status: 0 = COUNT events read, 1 = chip/line error or interrupted, 2 = usage.
#include <cerrno>
#include <csignal>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fcntl.h>
#include <linux/gpio.h>
#include <poll.h>
#include <sys/ioctl.h>
#include <unistd.h>

namespace {

volatile std::sig_atomic_t stop = 0;

// No SA_RESTART: a signal inside read() makes it fail with EINTR; one that lands
// elsewhere is kept in the flag, checked before every read().
void on_signal(int)
{
    stop = 1;
}

}  // namespace

int main(int argc, char **argv)
{
    long count = 1;
    if (argc > 2) {
        std::fprintf(stderr, "usage: %s [count]\n", argv[0]);
        return 2;
    }
    if (argc == 2) {
        char *end = nullptr;
        errno = 0;
        count = std::strtol(argv[1], &end, 10);
        if (errno || end == argv[1] || *end || count < 1) {
            std::fprintf(stderr, "usage: %s [count]   (count >= 1)\n", argv[0]);
            return 2;
        }
    }

    struct sigaction sa{};
    sa.sa_handler = on_signal;
    sigaction(SIGINT, &sa, nullptr);
    sigaction(SIGTERM, &sa, nullptr);

    const char *path = std::getenv("EDGE_GPIO_CHIP");
    if (!path)
        path = "/dev/gpiochip0";
    int chip = open(path, O_RDONLY);
    if (chip < 0) {
        std::fprintf(stderr, "open %s: %s\n", path, std::strerror(errno));
        return 1;
    }

    gpio_v2_line_request req{};
    req.offsets[0] = 43;                                   // PH.00 = header pin 33
    req.num_lines = 1;
    req.config.flags = GPIO_V2_LINE_FLAG_INPUT | GPIO_V2_LINE_FLAG_ACTIVE_LOW |
                       GPIO_V2_LINE_FLAG_EDGE_RISING | GPIO_V2_LINE_FLAG_EDGE_FALLING;
    req.config.num_attrs = 1;                              // the debounce applies to line 0
    req.config.attrs[0].mask = 1;
    req.config.attrs[0].attr.id = GPIO_V2_LINE_ATTR_ID_DEBOUNCE;
    req.config.attrs[0].attr.debounce_period_us = 20000;  // same 20 ms as edge_button.c
    std::strcpy(req.consumer, "edge_gpio_button");         // shown by gpioinfo
    if (ioctl(chip, GPIO_V2_GET_LINE_IOCTL, &req) < 0) {
        std::fprintf(stderr, "request line 43: %s\n", std::strerror(errno));  // EBUSY: edge_button.ko
        close(chip);
        return 1;
    }
    close(chip);                                           // the request fd lives on its own

    // Measured on this board: for ~20 ms after the request the line reads "pressed",
    // then settles, and gpiolib reports that as an edge nobody made. Let it settle,
    // drop what arrived meanwhile, and start from the level read afterwards.
    // 30 starts in a row: every one had that edge, none arrived after 50 ms.
    usleep(50000);
    int ignored = 0;
    unsigned int seqno = 0;                                // kernel's, last one read
    pollfd pfd{req.fd, POLLIN, 0};
    while (poll(&pfd, 1, 0) > 0) {
        gpio_v2_line_event junk{};
        if (read(req.fd, &junk, sizeof(junk)) != static_cast<ssize_t>(sizeof(junk)))
            break;
        seqno = junk.seqno;
        ignored++;
    }
    gpio_v2_line_values val{};
    val.mask = 1;
    if (ioctl(req.fd, GPIO_V2_LINE_GET_VALUES_IOCTL, &val) < 0) {
        std::fprintf(stderr, "read line 43: %s\n", std::strerror(errno));
        close(req.fd);
        return 1;
    }
    int last = val.bits & 1;                               // logical: 1 = pressed
    if (ignored)
        std::fprintf(stderr, "ignored %d edge(s) while the line settled\n", ignored);

    int rc = 0;
    long printed = 0;
    while (printed < count) {
        gpio_v2_line_event ev{};
        ssize_t n = stop ? -1 : read(req.fd, &ev, sizeof(ev));   // sleeps until an edge
        if (n != static_cast<ssize_t>(sizeof(ev))) {
            if (stop || (n < 0 && errno == EINTR))
                std::fprintf(stderr, "interrupted\n");
            else
                std::fprintf(stderr, "read line 43: %s\n", n < 0 ? std::strerror(errno) : "short read");
            rc = 1;
            break;
        }
        if (ev.seqno != seqno + 1)                         // the kernel queue overflowed
            std::fprintf(stderr, "lost %u event(s) (kernel seqno %u -> %u)\n",
                         ev.seqno - seqno - 1, seqno, ev.seqno);
        seqno = ev.seqno;
        // Rising = inactive to active; with ACTIVE_LOW that is the press.
        int pressed = ev.id == GPIO_V2_LINE_EVENT_RISING_EDGE;
        if (pressed == last)                               // no state change: not a press or release
            continue;
        last = pressed;
        printed++;
        std::printf("seq=%ld %s t=%llu.%09llu\n", printed, pressed ? "pressed" : "released",
                    static_cast<unsigned long long>(ev.timestamp_ns / 1000000000ULL),
                    static_cast<unsigned long long>(ev.timestamp_ns % 1000000000ULL));
        std::fflush(stdout);
    }
    close(req.fd);
    return rc;
}
