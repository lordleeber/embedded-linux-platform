// edge_test_cli: read or set the edge_test module's 32-bit value via ioctl (Step 3).
//
//   edge_test_cli [--device PATH] get
//   edge_test_cli [--device PATH] set VALUE      (VALUE: decimal 0..4294967295)
//
// Exit status: 0 = success, 1 = device or ioctl error, 2 = usage error.
#include <cerrno>
#include <cstdint>
#include <cstring>
#include <fcntl.h>
#include <iostream>
#include <optional>
#include <string>
#include <sys/ioctl.h>
#include <unistd.h>
#include <vector>

#include "edge_test_ioctl.h"

namespace {

constexpr const char *kDefaultDevice = "/dev/edge_test";

int usage(const std::string &why)
{
    std::cerr << "edge_test_cli: " << why << "\n"
              << "usage: edge_test_cli [--device PATH] get\n"
              << "       edge_test_cli [--device PATH] set VALUE   (decimal 0..4294967295)\n";
    return 2;
}

// Strict decimal parse: digits only, no sign, no hex, must fit in 32 bits.
std::optional<__u32> parse_u32(const std::string &s)
{
    if (s.empty() || s.size() > 10)
        return std::nullopt;
    uint64_t v = 0;
    for (char c : s) {
        if (c < '0' || c > '9')
            return std::nullopt;
        v = v * 10 + static_cast<uint64_t>(c - '0');
    }
    if (v > UINT32_MAX)
        return std::nullopt;
    return static_cast<__u32>(v);
}

int fail(const std::string &what, const std::string &path)
{
    std::cerr << "edge_test_cli: " << what << " " << path << ": " << std::strerror(errno) << "\n";
    return 1;
}

}  // namespace

int main(int argc, char **argv)
{
    std::vector<std::string> args(argv + 1, argv + argc);
    std::string device = kDefaultDevice;
    if (args.size() >= 2 && args[0] == "--device") {
        device = args[1];
        args.erase(args.begin(), args.begin() + 2);
    }
    if (args.empty())
        return usage("missing command");

    const std::string &cmd = args[0];
    std::optional<__u32> value;
    if (cmd == "get") {
        if (args.size() != 1)
            return usage("get takes no value");
    } else if (cmd == "set") {
        if (args.size() != 2)
            return usage("set needs exactly one VALUE");
        value = parse_u32(args[1]);
        if (!value)
            return usage("invalid VALUE '" + args[1] + "'");
    } else {
        return usage("unknown command '" + cmd + "'");
    }

    int fd = open(device.c_str(), O_RDWR);
    if (fd < 0)
        return fail("cannot open", device);

    int rc = 0;
    if (cmd == "get") {
        __u32 v = 0;
        if (ioctl(fd, EDGE_TEST_GET_VALUE, &v) == 0)
            std::cout << v << "\n";
        else
            rc = fail("EDGE_TEST_GET_VALUE failed on", device);
    } else {
        __u32 v = *value;
        if (ioctl(fd, EDGE_TEST_SET_VALUE, &v) != 0)
            rc = fail("EDGE_TEST_SET_VALUE failed on", device);
    }
    close(fd);
    return rc;
}
