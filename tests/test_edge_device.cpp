// Regression test for the /dev/edge_test ioctl interface (Step 3).
//
// Talks to the real device. Exit codes: 0 = all passed, 1 = a check failed,
// 77 = skipped because the device is absent (EDGE_TEST_REQUIRE=1 turns the
// skip into a failure; scripts/verify_edge_test.sh sets it after insmod).
#include <cerrno>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <fcntl.h>
#include <iostream>
#include <string>
#include <sys/ioctl.h>
#include <unistd.h>

#include "edge_test_ioctl.h"

// ABI contract: fixed-size argument, and numbers that must never change.
// _IOR/_IOW = dir(2 bits) << 30 | size(14) << 16 | type(8) << 8 | nr(8).
static_assert(sizeof(__u32) == 4, "ioctl argument must be a fixed 32-bit type");
static_assert(EDGE_TEST_IOC_MAGIC == 0xEB, "magic changed");
static_assert(EDGE_TEST_GET_VALUE == 0x8004EB01u, "GET_VALUE number changed");
static_assert(EDGE_TEST_SET_VALUE == 0x4004EB02u, "SET_VALUE number changed");

namespace {

int failures = 0;

void check(bool ok, const std::string &what)
{
    std::cout << (ok ? "PASS " : "FAIL ") << what << '\n';
    if (!ok)
        ++failures;
}

struct Fd {
    int fd;
    explicit Fd(const char *path) : fd(open(path, O_RDWR)) {}
    ~Fd() { if (fd >= 0) close(fd); }
};

bool set_value(int fd, __u32 v) { return ioctl(fd, EDGE_TEST_SET_VALUE, &v) == 0; }

bool get_value(int fd, __u32 &v) { return ioctl(fd, EDGE_TEST_GET_VALUE, &v) == 0; }

int ioctl_errno(int fd, unsigned long cmd, void *arg)
{
    errno = 0;
    return ioctl(fd, cmd, arg) == -1 ? errno : 0;
}

}  // namespace

int main()
{
    const char *path = std::getenv("EDGE_TEST_DEV");
    if (!path)
        path = "/dev/edge_test";
    const bool required = std::getenv("EDGE_TEST_REQUIRE") && std::string(std::getenv("EDGE_TEST_REQUIRE")) == "1";

    Fd dev(path);
    if (dev.fd < 0) {
        std::cout << (required ? "FAIL " : "SKIP ") << "open " << path << ": " << std::strerror(errno) << '\n';
        return required ? 1 : 77;
    }
    const int fd = dev.fd;
    __u32 v = 0;

    for (__u32 want : {123u, 0u, 0xFFFFFFFFu}) {
        bool ok = set_value(fd, want) && get_value(fd, v) && v == want;
        check(ok, "set/get round trip " + std::to_string(want));
    }

    {
        Fd other(path);
        set_value(fd, 456);
        check(other.fd >= 0 && get_value(other.fd, v) && v == 456, "value is shared across open file descriptors");
    }

    check(ioctl_errno(fd, _IO(EDGE_TEST_IOC_MAGIC, 0x7f), nullptr) == ENOTTY, "unknown nr returns ENOTTY");
    check(ioctl_errno(fd, _IOR('E', 0x01, __u32), &v) == ENOTTY, "foreign magic returns ENOTTY");
    check(ioctl_errno(fd, _IOR(EDGE_TEST_IOC_MAGIC, 0x01, __u64), &v) == ENOTTY, "wrong argument size returns ENOTTY");

    set_value(fd, 789);
    check(ioctl_errno(fd, EDGE_TEST_GET_VALUE, nullptr) == EFAULT, "GET with NULL returns EFAULT");
    check(ioctl_errno(fd, EDGE_TEST_GET_VALUE, reinterpret_cast<void *>(1)) == EFAULT, "GET with bad pointer returns EFAULT");
    check(ioctl_errno(fd, EDGE_TEST_SET_VALUE, nullptr) == EFAULT, "SET with NULL returns EFAULT");
    check(ioctl_errno(fd, EDGE_TEST_SET_VALUE, reinterpret_cast<void *>(1)) == EFAULT, "SET with bad pointer returns EFAULT");
    check(get_value(fd, v) && v == 789, "failed SET leaves the value unchanged");

    {
        int wfd = open(path, O_WRONLY | O_TRUNC);
        bool wrote = wfd >= 0 && write(wfd, "abc", 3) == 3;
        if (wfd >= 0)
            close(wfd);
        set_value(fd, 42);
        char buf[8] = {};
        int rfd = open(path, O_RDONLY);
        ssize_t n = rfd >= 0 ? read(rfd, buf, sizeof(buf)) : -1;
        if (rfd >= 0)
            close(rfd);
        check(wrote && n == 3 && std::memcmp(buf, "abc", 3) == 0, "ioctl does not touch the data buffer");
    }

    std::cout << "=== " << failures << " failure(s)\n";
    return failures ? 1 : 0;
}
