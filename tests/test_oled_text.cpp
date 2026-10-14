// Test vectors for apps/oled_text.h (Step 10-b): the 5x7 font and text drawn into the frame.
//
// Expected bytes come from the classic 5x7 column font (one byte per column, bit 0 = top row,
// the table most HD44780-style and SSD1306 libraries carry) and from the GDDRAM layout
// Step 9 checked on the panel: frame[page * 128 + x], bit n = row 8 * page + n. Step 9's
// three glyphs (tools/ssd1306.h) are the cross-check that EDGE still looks the same.
// Exit status: 0 = all checks passed, 1 = a check failed.
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <set>
#include <vector>

#include "../apps/oled_text.h"

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

int lit_bytes(const ssd1306::Frame &f)
{
    int n = 0;
    for (auto b : f)
        n += b != 0;
    return n;
}

void check_columns(const ssd1306::Frame &f, int at, const std::vector<std::uint8_t> &want)
{
    for (std::size_t i = 0; i < want.size(); ++i)
        CHECK_EQ(f[at + i], want[i]);
}

void test_font_covers_printable_ascii_only()
{
    for (int c = 0x20; c <= 0x7E; ++c)
        if (!oled_text::glyph(static_cast<char>(c))) {
            std::printf("FAIL no glyph for 0x%02X\n", c);
            ++failures;
        }
    for (int c : {0x00, 0x09, 0x0A, 0x1F, 0x7F, 0x80, 0xE9, 0xFF})
        CHECK_EQ(oled_text::glyph(static_cast<char>(c)) == nullptr, true);
}

void test_glyphs_fit_seven_rows_and_differ()
{
    // Row 7 (bit 7) is the gap between text lines: no glyph may use it.
    std::set<std::vector<std::uint8_t>> seen;
    for (int c = 0x20; c <= 0x7E; ++c) {
        const std::uint8_t *g = oled_text::glyph(static_cast<char>(c));
        if (!g)
            continue;
        std::vector<std::uint8_t> cols(g, g + 5);
        int lit = 0;
        for (auto b : cols) {
            if (b & 0x80) {
                std::printf("FAIL glyph 0x%02X uses row 7\n", c);
                ++failures;
            }
            lit += b != 0;
        }
        CHECK_EQ(lit == 0, c == ' ');
        if (!seen.insert(cols).second) {
            std::printf("FAIL glyph 0x%02X is a copy of an earlier one\n", c);
            ++failures;
        }
    }
}

void test_known_glyphs_from_the_classic_table()
{
    struct { char c; std::uint8_t cols[5]; } want[] = {
        {'A', {0x7E, 0x11, 0x11, 0x11, 0x7E}}, {'L', {0x7F, 0x40, 0x40, 0x40, 0x40}},
        {'N', {0x7F, 0x04, 0x08, 0x10, 0x7F}}, {'Z', {0x61, 0x51, 0x49, 0x45, 0x43}},
        {'0', {0x3E, 0x51, 0x49, 0x45, 0x3E}}, {'1', {0x00, 0x42, 0x7F, 0x40, 0x00}},
        {'7', {0x01, 0x71, 0x09, 0x05, 0x03}}, {'a', {0x20, 0x54, 0x54, 0x54, 0x78}},
        {'!', {0x00, 0x00, 0x5F, 0x00, 0x00}}, {'.', {0x00, 0x60, 0x60, 0x00, 0x00}},
    };
    for (auto &w : want) {
        const std::uint8_t *g = oled_text::glyph(w.c);
        if (!g) {
            std::printf("FAIL no glyph for '%c'\n", w.c);
            ++failures;
            continue;
        }
        for (int i = 0; i < 5; ++i)
            if (g[i] != w.cols[i]) {
                std::printf("FAIL '%c' column %d = %02X, expected %02X\n", w.c, i, g[i], w.cols[i]);
                ++failures;
            }
    }
}

void test_edge_letters_are_step9s()
{
    for (char c : {'D', 'E', 'G'}) {
        const std::uint8_t *a = oled_text::glyph(c), *b = ssd1306::glyph(c);
        CHECK_EQ(a && b && !std::memcmp(a, b, 5), true);
    }
}

void test_orientation_not_mirrored_not_upside_down()
{
    // 'L' at (0, 0): the upright stroke is the LEFT column (x = 0, rows 0..6 = 0x7F) and the
    // foot is the BOTTOM row (row 6 = bit 6) of columns 1..4; column 5 is the gap.
    ssd1306::Frame f{};
    CHECK_EQ(oled_text::draw_char(f, 0, 0, 'L'), true);
    check_columns(f, 0, {0x7F, 0x40, 0x40, 0x40, 0x40, 0x00});
    CHECK_EQ(lit_bytes(f), 5);
}

void test_glyph_across_a_page_boundary()
{
    // y = 4: rows 4..10. Rows 0..3 of the glyph go to bits 4..7 of page 0, rows 4..6 to
    // bits 0..2 of page 1, same column.
    ssd1306::Frame f{};
    oled_text::draw_char(f, 0, 4, 'L');
    check_columns(f, 0, {0xF0, 0x00, 0x00, 0x00, 0x00});
    check_columns(f, 128, {0x07, 0x04, 0x04, 0x04, 0x04});
    CHECK_EQ(lit_bytes(f), 6);
}

void test_clipping_at_every_edge()
{
    ssd1306::Frame f{};
    oled_text::draw_char(f, -3, 0, 'L');       // only columns 3, 4 land, at x = 0, 1
    check_columns(f, 0, {0x40, 0x40});
    CHECK_EQ(lit_bytes(f), 2);

    f = {};
    oled_text::draw_char(f, 126, 0, 'L');      // only columns 0, 1, at x = 126, 127
    check_columns(f, 126, {0x7F, 0x40});
    CHECK_EQ(lit_bytes(f), 2);

    f = {};
    oled_text::draw_char(f, 0, 60, 'L');       // rows 0..3 at y = 60..63; the foot is cut
    check_columns(f, 7 * 128, {0xF0, 0x00});
    CHECK_EQ(lit_bytes(f), 1);

    f = {};
    oled_text::draw_char(f, 0, -7, 'L');       // completely above: nothing
    oled_text::draw_char(f, 128, 0, 'L');      // completely right of the panel
    oled_text::draw_char(f, 0, 64, 'L');       // completely below
    CHECK_EQ(lit_bytes(f), 0);
}

void test_clip_count_at_the_exact_edges()
{
    // A glyph is 5x7: x = 123 and y = 57 end exactly on the last column / row.
    ssd1306::Frame f{};
    CHECK_EQ(oled_text::draw_string(f, 123, 57, "A").clipped, 0);
    CHECK_EQ(oled_text::draw_string(f, 124, 0, "A").clipped, 1);
    CHECK_EQ(oled_text::draw_string(f, 0, 58, "A").clipped, 1);
    CHECK_EQ(oled_text::draw_string(f, -1, 0, "A").clipped, 1);
    CHECK_EQ(oled_text::draw_string(f, 0, -1, "A").clipped, 1);
}

void test_unsupported_character_draws_a_box_and_is_counted()
{
    ssd1306::Frame f{};
    CHECK_EQ(oled_text::draw_char(f, 0, 0, '\t'), false);
    check_columns(f, 0, {0x7F, 0x41, 0x41, 0x41, 0x7F});

    f = {};
    auto r = oled_text::draw_string(f, 0, 0, "A\tB\xE9");
    CHECK_EQ(r.unsupported, 2);
    CHECK_EQ(r.clipped, 0);
    check_columns(f, 6, {0x7F, 0x41, 0x41, 0x41, 0x7F});    // the box keeps the cell
    CHECK_EQ(f[12], oled_text::glyph('B')[0]);              // B stays in column 2
}

void test_unsupported_off_the_panel_is_only_clipped()
{
    // PR #15 review: nothing of it is drawn, so no box is drawn either.
    ssd1306::Frame f{};
    auto r = oled_text::draw_string(f, 0, 64, "\t");
    CHECK_EQ(r.clipped, 1);
    CHECK_EQ(r.unsupported, 0);
    r = oled_text::draw_string(f, 126, 0, "\t");     // partly on the panel: a box sliver shows
    CHECK_EQ(r.clipped, 1);
    CHECK_EQ(r.unsupported, 1);
    r = oled_text::draw_text_at(f, 0, 22, "\t");     // column 22 starts at x = 132
    CHECK_EQ(r.unsupported, 0);
}

void test_newline_returns_to_the_starting_x()
{
    ssd1306::Frame f{};
    auto r = oled_text::draw_string(f, 12, 8, "AB\nC");
    CHECK_EQ(r.unsupported + r.clipped, 0);
    CHECK_EQ(f[128 + 12], oled_text::glyph('A')[0]);
    CHECK_EQ(f[128 + 18], oled_text::glyph('B')[0]);
    CHECK_EQ(f[2 * 128 + 12], oled_text::glyph('C')[0]);
    CHECK_EQ(f[2 * 128 + 18], 0);
}

void test_long_line_is_clipped_not_wrapped()
{
    // 21 cells of 6 px = 126 px; the 22nd character starts at x = 126 and shows 2 columns.
    ssd1306::Frame f{};
    auto r = oled_text::draw_string(f, 0, 0, "AAAAAAAAAAAAAAAAAAAAAAA");   // 23 characters
    CHECK_EQ(r.clipped, 2);
    CHECK_EQ(oled_text::kColumns, 21);
    check_columns(f, 120, {0x7E, 0x11, 0x11, 0x11, 0x7E, 0x00, 0x7E, 0x11});
    for (int i = 128; i < 1024; ++i)
        if (f[i]) {
            std::printf("FAIL byte %d lit: the long line wrapped\n", i);
            ++failures;
            break;
        }
}

void test_line_and_column_positioning()
{
    ssd1306::Frame a{}, b{};
    oled_text::draw_text_at(a, 2, 3, "X");
    oled_text::draw_string(b, 18, 16, "X");
    CHECK_EQ(a == b, true);
    CHECK_EQ(lit_bytes(a) > 0, true);

    ssd1306::Frame f{};
    CHECK_EQ(oled_text::kLines, 8);
    CHECK_EQ(oled_text::draw_text_at(f, 8, 0, "HI").clipped, 2);    // below the last line
    CHECK_EQ(oled_text::draw_text_at(f, 0, 22, "HI").clipped, 2);   // right of the panel
    // (column 21 starts at x = 126: two columns of it still show, see the long-line test)
    CHECK_EQ(oled_text::draw_text_at(f, -1, 0, "HI").clipped, 2);
    CHECK_EQ(lit_bytes(f), 0);
    // A newline in a line/column call goes back to that column, one line down.
    oled_text::draw_text_at(f, 6, 4, "A\nB");
    CHECK_EQ(f[6 * 128 + 24], oled_text::glyph('A')[0]);
    CHECK_EQ(f[7 * 128 + 24], oled_text::glyph('B')[0]);
    CHECK_EQ(oled_text::draw_text_at(f, 7, 0, "A\nB").clipped, 1);  // B falls off the bottom
}

void test_three_lines_of_the_acceptance_text()
{
    ssd1306::Frame f{};
    const char *lines[] = {"EDGE", "LINE 2", "123456"};
    for (int i = 0; i < 3; ++i)
        oled_text::draw_text_at(f, i, 0, lines[i]);
    check_columns(f, 0, {0x7F, 0x49, 0x49, 0x49, 0x41});        // E, page 0
    check_columns(f, 128, {0x7F, 0x40, 0x40, 0x40, 0x40});      // L, page 1
    check_columns(f, 256, {0x00, 0x42, 0x7F, 0x40, 0x00});      // 1, page 2
    for (int i = 3 * 128; i < 1024; ++i)
        if (f[i]) {
            std::printf("FAIL byte %d lit below line 3\n", i);
            ++failures;
            break;
        }
}

void test_clear()
{
    ssd1306::Frame f;
    f.fill(0xA5);
    oled_text::clear(f);
    CHECK_EQ(lit_bytes(f), 0);
    CHECK_EQ(oled_text::draw_pixel(f, 127, 63), true);
    CHECK_EQ(f[7 * 128 + 127], 0x80);
    CHECK_EQ(oled_text::draw_pixel(f, 128, 0), false);
}

void test_font_sheet_shows_every_glyph()
{
    std::set<char> shown;
    int n = 0;
    for (const char *line : oled_text::kFontSheet) {
        CHECK_EQ(static_cast<int>(std::strlen(line)) <= oled_text::kColumns, true);
        shown.insert(line, line + std::strlen(line));
        ++n;
    }
    CHECK_EQ(n <= oled_text::kLines, true);
    for (int c = 0x21; c <= 0x7E; ++c)
        if (!shown.count(static_cast<char>(c))) {
            std::printf("FAIL font sheet misses '%c'\n", c);
            ++failures;
        }
    // The sheet picture is those lines, one per text line from the top-left corner.
    ssd1306::Frame want{};
    for (int i = 0; i < n; ++i)
        oled_text::draw_text_at(want, i, 0, oled_text::kFontSheet[i]);
    CHECK_EQ(oled_text::font_picture() == want, true);
    CHECK_EQ(std::strncmp(oled_text::kFontSheet[0], "ABCDEFGHIJKLM", 13), 0);
}

}  // namespace

int main()
{
    test_font_covers_printable_ascii_only();
    test_glyphs_fit_seven_rows_and_differ();
    test_known_glyphs_from_the_classic_table();
    test_edge_letters_are_step9s();
    test_orientation_not_mirrored_not_upside_down();
    test_glyph_across_a_page_boundary();
    test_clipping_at_every_edge();
    test_clip_count_at_the_exact_edges();
    test_unsupported_character_draws_a_box_and_is_counted();
    test_unsupported_off_the_panel_is_only_clipped();
    test_newline_returns_to_the_starting_x();
    test_long_line_is_clipped_not_wrapped();
    test_line_and_column_positioning();
    test_three_lines_of_the_acceptance_text();
    test_clear();
    test_font_sheet_shows_every_glyph();
    std::printf("%s (%d failure(s))\n", failures ? "FAILED" : "OK", failures);
    return failures ? 1 : 0;
}
