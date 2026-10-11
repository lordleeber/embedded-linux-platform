// ina219_raw: read the six INA219 registers straight from /dev/i2c-N (Step 6-b).
//
// No Python library and no driver: i2c-dev hands us the bus, and one I2C_RDWR ioctl per
// register does what the vendor sample's read_i2c_block_data(addr, reg, 2) does on the
// wire: write the register pointer, repeated start, read two bytes (MSB first).
// Read-only: the only byte written is the pointer, so Calibration and Config stay as the
// sample (or i2cset) left them; with Cal = 0 (power-on) the chip reports no current.
//
// Usage: ina219_raw [--bus N] [--addr 0xNN]    default: bus 7, address 0x41 (UPS module C)
// The shunt is taken as 0.01 ohm (the sample's comment; not measured).
// Exit status: 0 = all six registers read, 1 = bus or I/O error, 2 = usage.
#include <cerrno>
#include <cinttypes>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fcntl.h>
#include <linux/i2c-dev.h>
#include <linux/i2c.h>
#include <sys/ioctl.h>
#include <unistd.h>

#include "ina219_decode.h"

namespace {

constexpr std::int32_t kShuntMilliohm = 10;

const char *const kNames[] = {"config", "shunt_voltage", "bus_voltage",
                              "power", "current", "calibration"};

int usage(const char *argv0)
{
    std::fprintf(stderr, "usage: %s [--bus N] [--addr 0x03..0x77]\n", argv0);
    return 2;
}

bool parse(const char *s, long lo, long hi, long *out)
{
    char *end = nullptr;
    errno = 0;
    long v = std::strtol(s, &end, 0);
    if (errno || end == s || *end || v < lo || v > hi)
        return false;
    *out = v;
    return true;
}

// Pointer write + repeated start + 2-byte read, in one transaction.
bool read_reg(int fd, std::uint16_t addr, std::uint8_t reg, std::uint16_t *value)
{
    std::uint8_t buf[2];
    i2c_msg msgs[2]{};
    msgs[0].addr = addr;
    msgs[0].flags = 0;
    msgs[0].len = 1;
    msgs[0].buf = &reg;
    msgs[1].addr = addr;
    msgs[1].flags = I2C_M_RD;
    msgs[1].len = 2;
    msgs[1].buf = buf;
    i2c_rdwr_ioctl_data xfer{msgs, 2};
    if (ioctl(fd, I2C_RDWR, &xfer) != 2)
        return false;
    *value = ina219::be16(buf);
    return true;
}

// A signed micro-unit value printed in milli-units with three decimals (uV -> "1.000 mV").
void print_milli(const char *label, std::int64_t micro, const char *unit, const char *note)
{
    std::int64_t mag = micro < 0 ? -micro : micro;
    std::printf("%-16s %s%" PRId64 ".%03" PRId64 " %s  (%s)\n", label, micro < 0 ? "-" : "",
                mag / 1000, mag % 1000, unit, note);
}

}  // namespace

int main(int argc, char **argv)
{
    long bus = 7, addr = 0x41;
    for (int i = 1; i < argc; i += 2) {
        if (i + 1 >= argc)
            return usage(argv[0]);
        if (!std::strcmp(argv[i], "--bus")) {
            if (!parse(argv[i + 1], 0, 255, &bus))
                return usage(argv[0]);
        } else if (!std::strcmp(argv[i], "--addr")) {
            if (!parse(argv[i + 1], 0x03, 0x77, &addr))
                return usage(argv[0]);
        } else {
            return usage(argv[0]);
        }
    }

    char path[32];
    std::snprintf(path, sizeof path, "/dev/i2c-%ld", bus);
    int fd = open(path, O_RDWR);
    if (fd < 0) {
        std::fprintf(stderr, "open %s: %s\n", path, std::strerror(errno));
        return 1;
    }

    std::uint16_t r[6];
    for (std::uint8_t reg = 0; reg < 6; ++reg) {
        if (!read_reg(fd, static_cast<std::uint16_t>(addr), reg, &r[reg])) {
            // No ACK (module unplugged, wrong address) is EREMOTEIO, "Remote I/O error".
            std::fprintf(stderr, "%s addr 0x%02lx reg 0x%02x: %s\n", path, addr, reg,
                         std::strerror(errno));
            close(fd);
            return 1;
        }
    }
    close(fd);

    std::printf("INA219 on %s at 0x%02lx\n", path, addr);
    std::printf("reg  name           raw\n");
    for (int reg = 0; reg < 6; ++reg)
        std::printf("0x%02X %-14s 0x%04X\n", reg, kNames[reg], r[reg]);

    using namespace ina219;
    const std::uint16_t bus_raw = r[kBusVoltage], cal = r[kCalibration];
    std::printf("%-16s %" PRId32 ".%03" PRId32 " V   (raw %d x 4 mV, CNVR=%d OVF=%d)\n",
                "bus voltage:", bus_mV(bus_raw) / 1000, bus_mV(bus_raw) % 1000, bus_raw >> 3,
                conversion_ready(bus_raw), overflow(bus_raw));
    print_milli("shunt voltage:", shunt_uV(r[kShuntVoltage]), "mV", "10 uV per bit, signed");
    print_milli("current (shunt):", current_uA_from_shunt(r[kShuntVoltage], kShuntMilliohm), "mA",
                "V_shunt / 0.01 ohm");
    if (cal == 0) {
        std::printf("%-16s n/a  (Calibration is 0: the chip computes no current or power)\n",
                    "current (reg):");
    } else {
        print_milli("current (reg):", current_uA(r[kCurrent], cal, kShuntMilliohm), "mA",
                    "Current_LSB = 0.04096 / (Cal x 0.01 ohm)");
        print_milli("power (reg):", power_uW(r[kPower], cal, kShuntMilliohm), "mW",
                    "20 x Current_LSB, unsigned");
    }
    return 0;
}
