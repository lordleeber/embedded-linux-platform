// telemetry_display: the INA219's battery values on the OLED (Step 10-c).
//
//   INA219 -> edge_ina219 (Step 8) -> /sys/class/hwmon/hwmonN/{in1,curr1,power1}_input
//          -> this program (telemetry.h lays out the text, oled_text.h draws it)
//          -> write(1024) -> /dev/edge_oled (Step 10-a/b) -> SSD1306
//
// Every interval it reads the three values, draws BAT / V / I / P and a status line, and
// writes the whole frame. Nothing here is fatal: a missing sensor shows NO SENSOR, a value that
// cannot be read is shown until it is older than --stale-ms and then as --.--, an OLED write
// that fails is retried at the next refresh. The hwmon directory is looked up by name
// (edge_ina219) and again whenever it disappears: unbind / bind gives it a new number.
// SIGINT / SIGTERM / SIGHUP: write a blank frame (no old numbers left on the panel), exit.
// SIGPIPE is ignored: a closed stdout (`| head`) must not kill the display.
//
// Usage: telemetry_display [--hwmon-root DIR] [--dev PATH] [--interval-ms N] [--stale-ms N]
//                          [--count N]
//   defaults: /sys/class/hwmon, /dev/edge_oled, 1000, 3000, 0 (= until a signal)
//   --count N stops after N refreshes and leaves the last picture (for tests).
// stdout: one line per refresh, "#N V=<mV> I=<mA> P=<uW> oled=ok" ('-' = not read).
// Exit status: 0 = stopped, last OLED write went through; 1 = it failed; 2 = usage.
#include <cerrno>
#include <csignal>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <ctime>
#include <dirent.h>
#include <fcntl.h>
#include <string>
#include <unistd.h>

#include "oled_text.h"
#include "telemetry.h"

namespace {

const char *const kChannels[3] = {"in1_input", "curr1_input", "power1_input"};

int usage(const char *argv0)
{
    std::fprintf(stderr, "usage: %s [--hwmon-root DIR] [--dev PATH] [--interval-ms N] "
                         "[--stale-ms N] [--count N]\n", argv0);
    return 2;
}

bool parse_count(const char *s, long long min, long long &out)
{
    char *end = nullptr;
    errno = 0;
    out = std::strtoll(s, &end, 10);
    return !errno && end != s && !*end && out >= min;
}

long long now_ms()
{
    timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return ts.tv_sec * 1000LL + ts.tv_nsec / 1000000;
}

// The whole file, or false with errno set.
bool read_file(const std::string &path, std::string &out)
{
    int fd = open(path.c_str(), O_RDONLY);
    if (fd < 0)
        return false;
    char buf[64];
    ssize_t n = read(fd, buf, sizeof(buf));
    int err = errno;
    close(fd);
    if (n < 0) {
        errno = err;
        return false;
    }
    out.assign(buf, n);
    return true;
}

// One whole frame, or false with errno set (a short write counts as EIO).
bool write_frame(int fd, const ssd1306::Frame &f)
{
    ssize_t n = write(fd, f.data(), f.size());
    if (n >= 0 && n != static_cast<ssize_t>(f.size()))
        errno = EIO;
    return n == static_cast<ssize_t>(f.size());
}

// The name is read on every refresh, not only after a failed read: hwmon numbers are reused,
// so a vanished hwmonN may come back as some other sensor whose files read fine.
bool is_sensor(const std::string &dir)
{
    std::string name;
    return read_file(dir + "/name", name) && name == "edge_ina219\n";
}

// hwmonN under root whose name is edge_ina219; "" if none.
std::string find_sensor(const std::string &root)
{
    std::string found;
    if (DIR *d = opendir(root.c_str())) {
        while (dirent *e = readdir(d))
            if (!std::strncmp(e->d_name, "hwmon", 5) && is_sensor(root + "/" + e->d_name)) {
                found = root + "/" + e->d_name;
                break;
            }
        closedir(d);
    }
    return found;
}

}  // namespace

int main(int argc, char **argv)
{
    std::string root = "/sys/class/hwmon", dev = "/dev/edge_oled";
    long long interval = 1000, stale_ms = 3000, count = 0;
    for (int i = 1; i < argc; i += 2) {
        if (i + 1 >= argc)
            return usage(argv[0]);
        const char *opt = argv[i], *val = argv[i + 1];
        if (!std::strcmp(opt, "--hwmon-root"))
            root = val;
        else if (!std::strcmp(opt, "--dev"))
            dev = val;
        else if (!std::strcmp(opt, "--interval-ms") ? !parse_count(val, 1, interval)
                 : !std::strcmp(opt, "--stale-ms") ? !parse_count(val, 0, stale_ms)
                 : !std::strcmp(opt, "--count") ? !parse_count(val, 0, count)
                 : true)
            return usage(argv[0]);
    }

    // Blocked, and taken with sigtimedwait() as the wait between refreshes: a signal that
    // arrives at any moment ends the wait at once, with no handler and no race.
    sigset_t stop_set;
    sigemptyset(&stop_set);
    sigaddset(&stop_set, SIGINT);
    sigaddset(&stop_set, SIGTERM);
    sigaddset(&stop_set, SIGHUP);
    sigprocmask(SIG_BLOCK, &stop_set, nullptr);
    signal(SIGPIPE, SIG_IGN);

    std::string dir;
    telemetry::Value values[3];
    bool failing[3] = {}, lost = false, oled_failing = false, stopped = false;
    int fd = -1, rc = 0;
    long long next = now_ms();
    for (long long seq = 1; count == 0 || seq <= count; ++seq) {
        long long t = now_ms();
        if (dir.empty() || !is_sensor(dir))
            dir = find_sensor(root);
        if (dir.empty() && !lost) {
            std::fprintf(stderr, "telemetry_display: no edge_ina219 under %s\n", root.c_str());
            for (bool &f : failing)
                f = false;        // a new failure after it comes back is reported again
        }
        lost = dir.empty();
        std::string shown[3] = {"-", "-", "-"};
        for (int c = 0; c < 3 && !dir.empty(); ++c) {
            std::string path = dir + "/" + kChannels[c], text;
            long long v = 0;
            bool got = read_file(path, text);
            int err = errno;
            bool ok = got && telemetry::parse_value(text, v);
            if (!ok && !failing[c])       // once per failure streak, not every refresh
                std::fprintf(stderr, "telemetry_display: %s: %s\n", path.c_str(),
                             got ? "not a number" : std::strerror(err));
            failing[c] = !ok;
            telemetry::update(values[c], ok, v, t);
            if (ok)
                shown[c] = std::to_string(v);
        }

        auto lines = telemetry::screen(!dir.empty(), values[0], values[1], values[2], t,
                                       stale_ms, static_cast<unsigned>(seq));
        ssd1306::Frame f{};
        for (int n = 0; n < 8; ++n)
            oled_text::draw_text_at(f, n, 0, lines[n].c_str());
        if (fd < 0)
            fd = open(dev.c_str(), O_WRONLY);
        rc = fd >= 0 && write_frame(fd, f) ? 0 : 1;
        int err = errno;
        if (rc && !oled_failing)
            std::fprintf(stderr, "telemetry_display: %s: %s\n", dev.c_str(), std::strerror(err));
        oled_failing = rc;
        if (rc && fd >= 0) {
            close(fd);            // reopen next time: an unbound driver leaves this fd dead
            fd = -1;
        }
        std::printf("#%lld V=%s I=%s P=%s oled=%s\n", seq, shown[0].c_str(), shown[1].c_str(),
                    shown[2].c_str(), rc ? std::strerror(err) : "ok");
        std::fflush(stdout);

        if (count && seq == count)
            break;
        long long now = now_ms();
        next += interval;
        if (next <= now)          // stopped or stalled: start again from now, do not catch up
            next = now + interval;
        long long wait = next - now;
        timespec ts{static_cast<time_t>(wait > 0 ? wait / 1000 : 0),
                    static_cast<long>(wait > 0 ? wait % 1000 * 1000000 : 0)};
        if (sigtimedwait(&stop_set, nullptr, &ts) > 0) {
            stopped = true;
            break;
        }
    }

    if (stopped) {
        ssd1306::Frame blank{};
        if (fd < 0)
            fd = open(dev.c_str(), O_WRONLY);
        rc = fd >= 0 && write_frame(fd, blank) ? 0 : 1;
        if (rc)
            std::fprintf(stderr, "telemetry_display: %s: blank frame: %s\n", dev.c_str(),
                         std::strerror(errno));
    }
    if (fd >= 0)
        close(fd);
    return rc;
}
