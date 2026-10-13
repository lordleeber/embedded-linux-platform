// Test vectors for tools/ssd1306.h (Step 9), run by tests/test_oled_probe.py.
//
// The expected bytes come from the SSD1306 datasheet (Rev 1.1: 8.1.5.1 I2C write,
// 9 command table, 10.1.3 page addressing, Figure 8-14 / 10-2 GDDRAM layout and the
// charge-pump application note) and from the classic 5x7 font table, not from the
// header itself. Exit status: 0 = all checks passed, 1 = a check failed.
#include <cstdint>
#include <cstdio>
#include <vector>

#include "../tools/ssd1306.h"

namespace {

int failures = 0;

#define CHECK_EQ(actual, expected)                                                         \
    do {                                                                                   \
        long long a_ = (actual), e_ = (expected);                                          \
        if (a_ != e_) {                                                                    \
            std::printf("FAIL %s:%d %s = %lld, expected %lld\n", __FILE__, __LINE__,      \
                        #actual, a_, e_);                                                  \
            ++failures;                                                                    \
        }                                                                                  \
    } while (0)

void check_bytes(const char *what, const std::vector<std::uint8_t> &got,
                 const std::vector<std::uint8_t> &want)
{
    if (got == want)
        return;
    std::printf("FAIL %s: got", what);
    for (auto b : got)
        std::printf(" %02X", b);
    std::printf("\n     want");
    for (auto b : want)
        std::printf(" %02X", b);
    std::printf("\n");
    ++failures;
}

void test_control_bytes()
{
    // Control byte = Co | D/C# | 000000. Co = 0: only data bytes follow (a stream).
    // D/C# = 0: the stream is commands; D/C# = 1: the stream goes to GDDRAM.
    CHECK_EQ(ssd1306::kControlCommand, 0x00);
    CHECK_EQ(ssd1306::kControlData, 0x40);
    check_bytes("command frame", ssd1306::command_frame({0xAE, 0x8D, 0x14}),
                {0x00, 0xAE, 0x8D, 0x14});
    const std::uint8_t data[3] = {0xFF, 0x00, 0x81};
    check_bytes("data frame", ssd1306::data_frame(data, 3), {0x40, 0xFF, 0x00, 0x81});
}

void test_init_sets_every_register_it_depends_on()
{
    // Every setting the frame layout relies on is written, so nothing depends on what a
    // previous run (or a reset) left behind. Display ON (0xAF) is not here: it is sent
    // after the first frame so the old RAM content never flashes.
    check_bytes("init", ssd1306::init_sequence(),
                {
                    0xAE,              // display off
                    0xD5, 0x80,        // clock divide / oscillator: reset value
                    0xA8, 0x3F,        // multiplex ratio: 64 rows
                    0xD3, 0x00,        // display offset 0
                    0x40,              // display start line 0
                    0x8D, 0x14,        // charge pump on (internal VCC from 3.3 V)
                    0x20, 0x00,        // horizontal addressing mode
                    0xA1,              // segment remap: column 127 -> SEG0 (not mirrored)
                    0xC8,              // COM scan from COM[N-1]: page 0 at the top
                    0xDA, 0x12,        // COM pins: alternative, no left/right remap (128x64)
                    0x81, 0xCF,        // contrast
                    0xD9, 0xF1,        // pre-charge for the internal charge pump
                    0xDB, 0x40,        // VCOMH deselect level
                    0x2E,              // scrolling off (it would move the frame)
                    0xA4,              // output follows RAM (not all-on)
                    0xA6,              // normal, not inverse
                });
    CHECK_EQ(ssd1306::kDisplayOn, 0xAF);
    CHECK_EQ(ssd1306::kDisplayOff, 0xAE);
}

void test_pixel_layout_is_page_column_bit()
{
    // GDDRAM: 8 pages of 128 bytes; byte (page, x) holds rows 8*page .. 8*page+7,
    // bit 0 = top row of the page.
    ssd1306::Frame f{};
    CHECK_EQ(f.size(), 1024);
    CHECK_EQ(ssd1306::set_pixel(f, 0, 0), true);
    CHECK_EQ(f[0], 0x01);
    CHECK_EQ(ssd1306::set_pixel(f, 3, 9), true);
    CHECK_EQ(f[128 + 3], 0x02);
    CHECK_EQ(ssd1306::set_pixel(f, 127, 63), true);
    CHECK_EQ(f[1023], 0x80);
    CHECK_EQ(ssd1306::set_pixel(f, 0, 7), true);
    CHECK_EQ(f[0], 0x81);
}

void test_pixel_out_of_range_is_ignored()
{
    ssd1306::Frame f{};
    CHECK_EQ(ssd1306::set_pixel(f, -1, 0), false);
    CHECK_EQ(ssd1306::set_pixel(f, 0, -1), false);
    CHECK_EQ(ssd1306::set_pixel(f, 128, 0), false);
    CHECK_EQ(ssd1306::set_pixel(f, 0, 64), false);
    int lit = 0;
    for (auto b : f)
        lit += b != 0;
    CHECK_EQ(lit, 0);
}

void test_glyphs_are_the_classic_5x7_columns()
{
    // One byte per column, bit 0 = top row (the same orientation as a GDDRAM byte).
    const std::uint8_t *e = ssd1306::glyph('E');
    const std::uint8_t *d = ssd1306::glyph('D');
    const std::uint8_t *g = ssd1306::glyph('G');
    const std::uint8_t want_e[5] = {0x7F, 0x49, 0x49, 0x49, 0x41};
    const std::uint8_t want_d[5] = {0x7F, 0x41, 0x41, 0x22, 0x1C};
    const std::uint8_t want_g[5] = {0x3E, 0x41, 0x49, 0x49, 0x7A};
    if (!e || !d || !g) {
        std::printf("FAIL glyph table misses E, D or G\n");
        ++failures;
        return;
    }
    for (int i = 0; i < 5; ++i) {
        CHECK_EQ(e[i], want_e[i]);
        CHECK_EQ(d[i], want_d[i]);
        CHECK_EQ(g[i], want_g[i]);
    }
    CHECK_EQ(ssd1306::glyph('Z') == nullptr, true);
}

void test_text_at_scale_1_lands_in_page_0()
{
    ssd1306::Frame f{};
    CHECK_EQ(ssd1306::draw_text(f, 0, 0, "EDGE", 1), true);
    const std::uint8_t want[23] = {0x7F, 0x49, 0x49, 0x49, 0x41, 0,     // E + gap
                                   0x7F, 0x41, 0x41, 0x22, 0x1C, 0,     // D
                                   0x3E, 0x41, 0x49, 0x49, 0x7A, 0,     // G
                                   0x7F, 0x49, 0x49, 0x49, 0x41};       // E
    for (int i = 0; i < 23; ++i)
        CHECK_EQ(f[i], want[i]);
    for (int i = 23; i < 1024; ++i)
        if (f[i]) {
            std::printf("FAIL byte %d = %02X after the text\n", i, f[i]);
            ++failures;
            break;
        }
    CHECK_EQ(ssd1306::text_width("EDGE", 1), 23);
    CHECK_EQ(ssd1306::text_width("EDGE", 4), 92);
}

void test_text_scale_2_spans_two_pages()
{
    // 'E' column 0 is 0x7F (rows 0..6); doubled it covers rows 0..13 of columns 0..1.
    ssd1306::Frame f{};
    CHECK_EQ(ssd1306::draw_text(f, 0, 0, "E", 2), true);
    CHECK_EQ(f[0], 0xFF);
    CHECK_EQ(f[1], 0xFF);
    CHECK_EQ(f[128], 0x3F);
    CHECK_EQ(f[129], 0x3F);
    // column 2..3 is 0x49: rows 0, 3, 6 -> scaled rows 0-1, 6-7, 12-13
    CHECK_EQ(f[2], 0xC3);
    CHECK_EQ(f[128 + 2], 0x30);
}

void test_unsupported_character_is_refused()
{
    ssd1306::Frame f{};
    CHECK_EQ(ssd1306::draw_text(f, 0, 0, "EDGE?", 1), false);
}

void test_frame_writes_reset_the_window_then_stream_8_pages()
{
    // The window command makes every frame write start at (page 0, column 0) whatever
    // address pointer a previous run left; the data then goes out one page per message.
    ssd1306::Frame f{};
    for (std::size_t i = 0; i < f.size(); ++i)
        f[i] = static_cast<std::uint8_t>(i);
    auto msgs = ssd1306::frame_writes(f);
    CHECK_EQ(msgs.size(), 9);
    if (msgs.size() != 9)
        return;
    check_bytes("window", msgs[0], {0x00, 0x21, 0x00, 0x7F, 0x22, 0x00, 0x07});
    std::vector<std::uint8_t> all;
    for (std::size_t m = 1; m < msgs.size(); ++m) {
        CHECK_EQ(msgs[m].size(), 129);
        CHECK_EQ(msgs[m][0], 0x40);
        all.insert(all.end(), msgs[m].begin() + 1, msgs[m].end());
    }
    CHECK_EQ(all.size(), 1024);
    for (std::size_t i = 0; i < all.size() && i < f.size(); ++i)
        if (all[i] != f[i]) {
            std::printf("FAIL streamed byte %zu = %02X, frame %02X\n", i, all[i], f[i]);
            ++failures;
            break;
        }
}

}  // namespace

int main()
{
    test_control_bytes();
    test_init_sets_every_register_it_depends_on();
    test_pixel_layout_is_page_column_bit();
    test_pixel_out_of_range_is_ignored();
    test_glyphs_are_the_classic_5x7_columns();
    test_text_at_scale_1_lands_in_page_0();
    test_text_scale_2_spans_two_pages();
    test_unsupported_character_is_refused();
    test_frame_writes_reset_the_window_then_stream_8_pages();
    std::printf("%s (%d failure(s))\n", failures ? "FAILED" : "OK", failures);
    return failures ? 1 : 0;
}
