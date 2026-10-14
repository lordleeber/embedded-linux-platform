// What the telemetry display shows (Step 10-c): hwmon values parsed, rounded and laid out as
// eight text lines, and when a value counts as stale. No I/O and no clock here, so
// tests/test_telemetry.cpp drives it with plain numbers and times.
//
// Units follow the hwmon sysfs ABI that edge_ina219 implements (Step 8): in1_input is the bus
// voltage in mV, curr1_input mA (negative = discharging), power1_input uW.
#pragma once

#include <array>
#include <cerrno>
#include <cstdio>
#include <cstdlib>
#include <string>

namespace telemetry {

// A whole sysfs value: optional '-', digits, optional one '\n', nothing else, within long long
// (strtoll would clamp anything larger, and hundredths() cannot negate LLONG_MIN).
inline bool parse_value(const std::string &text, long long &out)
{
    std::string s = text;
    if (!s.empty() && s.back() == '\n')
        s.pop_back();
    std::size_t i = !s.empty() && s[0] == '-' ? 1 : 0;
    if (i == s.size())
        return false;
    for (std::size_t j = i; j < s.size(); ++j)
        if (s[j] < '0' || s[j] > '9')
            return false;
    errno = 0;
    out = std::strtoll(s.c_str(), nullptr, 10);
    return errno != ERANGE;
}

// value / unit with two decimals, rounded half away from zero, right-aligned to 5 characters
// (" 1.84", "-0.56", "11.92"); a value that rounds to zero has no minus sign.
inline std::string hundredths(long long value, long long unit)
{
    long long step = unit / 100;
    long long mag = value < 0 ? -value : value;
    long long h = (mag + step / 2) / step;
    char num[32], out[40];
    std::snprintf(num, sizeof(num), "%s%lld.%02lld", value < 0 && h ? "-" : "", h / 100, h % 100);
    std::snprintf(out, sizeof(out), "%5s", num);
    return out;
}

// Battery percentage the way the vendor sample computes it (third_party/waveshare_ups_c/
// ina219.py): linear in the bus voltage from 9.0 V (0 %) to 12.6 V (100 %), clamped. It follows
// the voltage only, so it reads high while charging (Step 6-a measured 79 % -> 93 % on plugging
// the adapter in): a display value, nothing decides anything from it.
inline std::string percent(long long mv)
{
    long long x = mv - 9000;                                   // 36 mV per percent
    long long h = x <= 0 ? 0 : x >= 3600 ? 10000 : (x * 50 + 9) / 18;   // hundredths, nearest
    return hundredths(h, 100);
}

// The last good reading of one channel. A failed read keeps it (and its time).
struct Value {
    bool have = false;
    long long value = 0;
    long long at_ms = 0;
};

inline void update(Value &v, bool ok, long long reading, long long now_ms)
{
    if (!ok)
        return;
    v.have = true;
    v.value = reading;
    v.at_ms = now_ms;
}

inline bool stale(const Value &v, long long now_ms, long long stale_ms)
{
    return !v.have || now_ms - v.at_ms > stale_ms;
}

// Eight lines for oled_text::draw_text_at (21 columns each):
//   BAT: 81.22 % / V: 11.92 V / I: -0.56 A / P:  6.53 W / ... / status
// A stale or missing value shows as --.-- (the percentage goes with the voltage). The status
// line says OK, which channels are stale, or that no sensor was found, followed by a refresh
// counter that shows the picture is live.
inline std::array<std::string, 8> screen(bool sensor, const Value &v, const Value &i,
                                         const Value &p, long long now_ms, long long stale_ms,
                                         unsigned seq)
{
    struct Row { const char *label; const Value &val; long long unit; const char *si; };
    const Row rows[] = {{"V", v, 1000, "V"}, {"I", i, 1000, "A"}, {"P", p, 1000000, "W"}};
    std::array<std::string, 8> s;
    std::string stale_names;
    bool v_old = !sensor || stale(v, now_ms, stale_ms);
    s[0] = std::string("BAT: ") + (v_old ? "--.--" : percent(v.value)) + " %";
    for (int n = 0; n < 3; ++n) {
        const Row &r = rows[n];
        bool old = !sensor || stale(r.val, now_ms, stale_ms);
        s[n + 1] = std::string(r.label) + ": " + (old ? "--.--" : hundredths(r.val.value, r.unit)) +
                   " " + r.si;
        if (old)
            stale_names += std::string(" ") + r.label;
    }
    std::string count = " #" + std::to_string(seq % 10000);
    s[7] = !sensor ? "NO SENSOR" + count
                   : stale_names.empty() ? "OK" + count : "STALE" + stale_names + count;
    return s;
}

}  // namespace telemetry
