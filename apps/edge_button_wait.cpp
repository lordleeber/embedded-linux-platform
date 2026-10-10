// edge_button_wait: block on /dev/edge_button and print COUNT button events (Step 5-b).
//
// Usage: edge_button_wait [count]    count >= 1, default 1
// One line per event: "seq=3 pressed t=1234.567890123" (CLOCK_MONOTONIC seconds).
// read() sleeps in the kernel until the driver queues an event, so waiting
// costs no CPU. EDGE_BUTTON_DEV overrides the device path (tests).
// Exit status: 0 = COUNT events read, 1 = device error or interrupted, 2 = usage.
#include <cerrno>
#include <csignal>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fcntl.h>
#include <unistd.h>

#include "edge_button.h"

namespace {

volatile std::sig_atomic_t stop = 0;

// No SA_RESTART: a signal inside read() makes it fail with EINTR. One that lands
// elsewhere (e.g. while printing) is kept in the flag, checked before every read().
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

    const char *path = std::getenv("EDGE_BUTTON_DEV");
    if (!path)
        path = "/dev/edge_button";
    int fd = open(path, O_RDONLY);
    if (fd < 0) {
        std::fprintf(stderr, "open %s: %s\n", path, std::strerror(errno));  // EBUSY: another reader
        return 1;
    }

    int rc = 0;
    for (long i = 0; i < count; i++) {
        edge_button_event ev{};
        ssize_t n = stop ? -1 : read(fd, &ev, sizeof(ev));   // blocks until a press or release
        if (n != static_cast<ssize_t>(sizeof(ev))) {
            if (stop || (n < 0 && errno == EINTR))
                std::fprintf(stderr, "interrupted\n");
            else
                std::fprintf(stderr, "read %s: %s\n", path, n < 0 ? std::strerror(errno) : "short read");
            rc = 1;
            break;
        }
        std::printf("seq=%u %s t=%llu.%09llu\n", ev.seq, ev.pressed ? "pressed" : "released",
                    static_cast<unsigned long long>(ev.timestamp_ns / 1000000000ULL),
                    static_cast<unsigned long long>(ev.timestamp_ns % 1000000000ULL));
        std::fflush(stdout);                     // the acceptance script reads lines as they come
    }
    close(fd);
    return rc;
}
