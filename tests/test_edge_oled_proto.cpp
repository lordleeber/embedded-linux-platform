// Step 10-a: the kernel driver's SSD1306 bytes (include/edge_oled_proto.h) and its userspace
// interface (include/edge_oled.h) against Step 9's tools/ssd1306.h, which the real panel
// accepted (docs/baseline.md, Step 9). Both headers are plain C so edge_oled.ko includes them;
// here they are compiled as C++ and compared byte by byte.
// Exit status: 0 = all vectors pass, 1 = a mismatch.
#include <cstdio>
#include <cstring>
#include <linux/ioctl.h>
#include <vector>

#include "edge_oled.h"
#include "edge_oled_proto.h"
#include "edge_test_ioctl.h"
#include "../tools/ssd1306.h"

namespace {

int failures = 0;

void check(bool ok, const char *what)
{
    if (!ok) {
        std::printf("FAIL %s\n", what);
        ++failures;
    }
}

std::vector<std::uint8_t> bytes(const std::uint8_t *p, std::size_t n)
{
    return std::vector<std::uint8_t>(p, p + n);
}

int bits_set(const ssd1306::Frame &f)
{
    int n = 0;
    for (auto b : f)
        n += __builtin_popcount(b);
    return n;
}

bool lit(const ssd1306::Frame &f, int x, int y)
{
    return f[(y / 8) * ssd1306::kWidth + x] >> (y % 8) & 1;
}

}  // namespace

int main()
{
    // Geometry: the panel on this board is 128x64; the frame is GDDRAM's own layout.
    check(EDGE_OLED_WIDTH == ssd1306::kWidth && EDGE_OLED_HEIGHT == ssd1306::kHeight, "128x64");
    check(EDGE_OLED_PAGES == ssd1306::kPages, "8 pages");
    check(EDGE_OLED_FRAME_SIZE == sizeof(ssd1306::Frame) && EDGE_OLED_FRAME_SIZE == 1024,
          "frame size 1024 = Step 9's Frame");

    // Control bytes and the two display commands.
    check(EDGE_OLED_CONTROL_CMD == ssd1306::kControlCommand, "control byte: commands 0x00");
    check(EDGE_OLED_CONTROL_DATA == ssd1306::kControlData, "control byte: data 0x40");
    check(EDGE_OLED_CMD_DISPLAY_OFF == ssd1306::kDisplayOff, "display off 0xAE");
    check(EDGE_OLED_CMD_DISPLAY_ON == ssd1306::kDisplayOn, "display on 0xAF");

    // The init sequence the panel took in Step 9, every byte, in order.
    check(bytes(edge_oled_init_seq, sizeof edge_oled_init_seq) == ssd1306::init_sequence(),
          "init sequence = Step 9's init_sequence()");

    // The window command = Step 9's first frame message without its control byte.
    ssd1306::Frame blank{};
    auto msgs = ssd1306::frame_writes(blank);
    std::vector<std::uint8_t> window(msgs[0].begin() + 1, msgs[0].end());
    check(msgs[0][0] == EDGE_OLED_CONTROL_CMD &&
              bytes(edge_oled_window, sizeof edge_oled_window) == window,
          "window = Step 9's frame_writes()[0]");

    // ioctl numbers: fixed-size argument, magic shared with edge_test but no number reused.
    check(_IOC_TYPE(EDGE_OLED_IOC_CLEAR) == EDGE_TEST_IOC_MAGIC, "CLEAR magic 0xEB");
    check(_IOC_DIR(EDGE_OLED_IOC_CLEAR) == _IOC_NONE, "CLEAR takes no argument");
    check(_IOC_DIR(EDGE_OLED_IOC_FILL) == _IOC_WRITE && _IOC_SIZE(EDGE_OLED_IOC_FILL) == 1,
          "FILL writes one byte");
    const unsigned long numbers[] = {EDGE_OLED_IOC_CLEAR, EDGE_OLED_IOC_FILL, EDGE_TEST_GET_VALUE,
                                     EDGE_TEST_SET_VALUE};
    for (int i = 0; i < 4; ++i)
        for (int j = i + 1; j < 4; ++j)
            check(_IOC_NR(numbers[i]) != _IOC_NR(numbers[j]), "ioctl numbers are distinct");

    // Test pictures moved from oled_probe into ssd1306.h (shared with edge_oled_ctl).
    auto pixel = ssd1306::test_picture("pixel");
    check(bits_set(pixel) == 5 && lit(pixel, 0, 0) && lit(pixel, 127, 0) && lit(pixel, 0, 63) &&
              lit(pixel, 127, 63) && lit(pixel, 64, 32),
          "pixel: four corners and the centre");
    auto pattern = ssd1306::test_picture("pattern");
    // Border 2 x 128 + 2 x 62 = 380, diagonal (y, y) for y = 1..62 adds 62 (its ends are on the border).
    check(bits_set(pattern) == 380 + 62 && lit(pattern, 10, 10) && !lit(pattern, 117, 10),
          "pattern: border and a diagonal from the top-left");
    auto edge = ssd1306::test_picture("edge");
    ssd1306::Frame want{};
    ssd1306::draw_text(want, 18, 18, "EDGE", 4);
    check(edge == want, "edge: EDGE x4 at (18, 18)");
    check(bits_set(ssd1306::test_picture("clear")) == 0 && bits_set(ssd1306::test_picture("x")) == 0,
          "clear / unknown: blank");

    std::printf("%s (%d failure(s))\n", failures ? "FAILED" : "OK", failures);
    return failures ? 1 : 0;
}
