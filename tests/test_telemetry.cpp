// Test vectors for apps/telemetry.h (Step 10-c): parsing hwmon values, formatting them for the
// OLED, and the stale rule. The units come from the kernel's hwmon sysfs ABI
// (Documentation/hwmon/sysfs-interface.rst: in*_input mV, curr*_input mA, power*_input uW) and
// from Step 8's edge_ina219, which exposes in1 (bus voltage), curr1 and power1.
// Exit status: 0 = all checks passed, 1 = a check failed.
#include <cstdio>
#include <string>

#include "../apps/telemetry.h"

namespace {

int failures = 0;

void check_str(const char *what, const std::string &got, const std::string &want)
{
    if (got != want) {
        std::printf("FAIL %s: got \"%s\", want \"%s\"\n", what, got.c_str(), want.c_str());
        ++failures;
    }
}

void check(bool ok, const char *what)
{
    if (!ok) {
        std::printf("FAIL %s\n", what);
        ++failures;
    }
}

void test_parse_sysfs_integers()
{
    long long v = 0;
    check(telemetry::parse_value("11924\n", v) && v == 11924, "11924\\n");
    check(telemetry::parse_value("-555\n", v) && v == -555, "-555\\n");
    check(telemetry::parse_value("0", v) && v == 0, "0 without newline");
    check(!telemetry::parse_value("", v), "empty");
    check(!telemetry::parse_value("\n", v), "only a newline");
    check(!telemetry::parse_value("12a\n", v), "trailing garbage");
    check(!telemetry::parse_value("-\n", v), "a lone minus");
    check(!telemetry::parse_value("1\n2\n", v), "two lines");
    // PR #16 review: strtoll clamps out-of-range input to LLONG_MIN / MAX (and hundredths()
    // negating LLONG_MIN is undefined). Reject it instead.
    check(telemetry::parse_value("9223372036854775807\n", v) && v == 9223372036854775807LL,
          "LLONG_MAX");
    check(!telemetry::parse_value("9223372036854775808\n", v), "LLONG_MAX + 1");
    check(!telemetry::parse_value("-9223372036854775809\n", v), "LLONG_MIN - 1");
}

void test_hundredths_round_half_away_from_zero()
{
    check_str("11924 mV", telemetry::hundredths(11924, 1000), "11.92");
    check_str("11925 mV", telemetry::hundredths(11925, 1000), "11.93");
    check_str("1840 mA", telemetry::hundredths(1840, 1000), " 1.84");
    check_str("-555 mA", telemetry::hundredths(-555, 1000), "-0.56");
    check_str("-554 mA", telemetry::hundredths(-554, 1000), "-0.55");
    check_str("-4 mA: no negative zero", telemetry::hundredths(-4, 1000), " 0.00");
    check_str("6530000 uW", telemetry::hundredths(6530000, 1000000), " 6.53");
    check_str("21934999 uW", telemetry::hundredths(21934999, 1000000), "21.93");
    check_str("-12345 mA", telemetry::hundredths(-12345, 1000), "-12.35");
    check_str("123456 mV", telemetry::hundredths(123456, 1000), "123.46");
}

void test_screen_with_fresh_values()
{
    telemetry::Value v, i, p;
    telemetry::update(v, true, 11924, 1000);
    telemetry::update(i, true, -555, 1000);
    telemetry::update(p, true, 6530000, 1000);
    auto s = telemetry::screen(true, v, i, p, 1500, 3000, 42);
    check_str("line 0", s[0], "BAT: 81.22 %");
    check_str("line 1", s[1], "V: 11.92 V");
    check_str("line 2", s[2], "I: -0.56 A");
    check_str("line 3", s[3], "P:  6.53 W");
    for (int n = 4; n < 7; ++n)
        check_str("empty line", s[n], "");
    check_str("status", s[7], "OK #42");
}

void test_percentage_is_the_vendor_formula()
{
    // third_party/waveshare_ups_c/ina219.py: p = (bus_voltage - 9) / 3.6 * 100, clamped to
    // 0..100, printed with {:6.2f}. Pairs the sample printed on this board (docs/baseline.md,
    // Step 6-a, and 12.528 V -> 98.00 % on 2026-10-14).
    struct { long long mv; const char *want; } cases[] = {
        {12364, "93.44"}, {12192, "88.67"}, {12208, "89.11"}, {11860, "79.44"},
        {12528, "98.00"}, {9000, " 0.00"}, {8500, " 0.00"}, {12600, "100.00"}, {12650, "100.00"}, {13100, "100.00"},
        {9001, " 0.03"}, {9002, " 0.06"},
    };
    for (auto &c : cases)
        check_str(std::to_string(c.mv).c_str(), telemetry::percent(c.mv), c.want);
}

void test_failed_read_keeps_the_value_until_stale()
{
    telemetry::Value i;
    telemetry::update(i, true, -555, 1000);
    telemetry::update(i, false, 0, 2000);              // failed read: value and time kept
    check(i.have && i.value == -555 && i.at_ms == 1000, "failed read keeps value and time");
    check(!telemetry::stale(i, 4000, 3000), "3000 ms old with a 3000 ms limit: fresh");
    check(telemetry::stale(i, 4001, 3000), "3001 ms old: stale");
    telemetry::Value never;
    check(telemetry::stale(never, 0, 3000), "never read: stale");
    telemetry::update(i, true, -600, 5000);
    check(!telemetry::stale(i, 5000, 3000) && i.value == -600, "a good read refreshes it");
}

void test_screen_marks_stale_channels()
{
    telemetry::Value v, i, p;
    telemetry::update(v, true, 11924, 0);
    telemetry::update(i, true, -555, 0);
    telemetry::update(p, true, 6530000, 4000);
    auto s = telemetry::screen(true, v, i, p, 4000, 3000, 7);
    check_str("stale V", s[1], "V: --.-- V");
    check_str("percentage follows V", s[0], "BAT: --.-- %");
    check_str("stale I", s[2], "I: --.-- A");
    check_str("fresh P", s[3], "P:  6.53 W");
    check_str("status names the stale ones", s[7], "STALE V I #7");
}

void test_no_sensor()
{
    telemetry::Value v, i, p;
    auto s = telemetry::screen(false, v, i, p, 0, 3000, 1);
    check_str("V without a sensor", s[1], "V: --.-- V");
    check_str("status", s[7], "NO SENSOR #1");
}

void test_counter_wraps_and_lines_fit()
{
    telemetry::Value v, i, p;
    telemetry::update(v, true, -99999999, 0);
    telemetry::update(i, true, -99999999, 0);
    telemetry::update(p, true, 999999999999LL, 0);
    auto s = telemetry::screen(true, v, i, p, 0, 3000, 12345);
    check_str("counter mod 10000", s[7], "OK #2345");
    for (auto &line : s)
        check(line.size() <= 21, "every line fits 21 columns");
}

}  // namespace

int main()
{
    test_parse_sysfs_integers();
    test_hundredths_round_half_away_from_zero();
    test_screen_with_fresh_values();
    test_percentage_is_the_vendor_formula();
    test_failed_read_keeps_the_value_until_stale();
    test_screen_marks_stale_channels();
    test_no_sensor();
    test_counter_wraps_and_lines_fit();
    std::printf("%s (%d failure(s))\n", failures ? "FAILED" : "OK", failures);
    return failures ? 1 : 0;
}
