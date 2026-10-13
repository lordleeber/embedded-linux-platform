// SSD1306 protocol bytes for a 128x64 I2C OLED (Step 9): framing, init sequence,
// GDDRAM layout and the few glyphs the fixed string needs. No I/O here, so the bytes are
// checked by tests/test_ssd1306.cpp against the datasheet without hardware.
//
// On the wire every I2C write is: address, control byte, then a stream. Control byte
// 0x00 says the stream is commands, 0x40 says it is display RAM data. ASCII written to
// the chip shows nothing: text has to be drawn into the frame as pixels first.
#pragma once

#include <array>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <vector>

namespace ssd1306 {

constexpr int kWidth = 128;
constexpr int kHeight = 64;
constexpr int kPages = kHeight / 8;

// Control byte: bit 7 Co (0 = no more control bytes, only a stream follows),
// bit 6 D/C# (0 = commands, 1 = GDDRAM data).
constexpr std::uint8_t kControlCommand = 0x00;
constexpr std::uint8_t kControlData = 0x40;

constexpr std::uint8_t kDisplayOff = 0xAE;
constexpr std::uint8_t kDisplayOn = 0xAF;

// GDDRAM image: byte (page, x) = frame[page * 128 + x], bit n = row 8 * page + n.
using Frame = std::array<std::uint8_t, kWidth * kPages>;

inline std::vector<std::uint8_t> command_frame(const std::vector<std::uint8_t> &cmds)
{
    std::vector<std::uint8_t> out{kControlCommand};
    out.insert(out.end(), cmds.begin(), cmds.end());
    return out;
}

inline std::vector<std::uint8_t> data_frame(const std::uint8_t *data, std::size_t n)
{
    std::vector<std::uint8_t> out{kControlData};
    out.insert(out.end(), data, data + n);
    return out;
}

// Writes every setting the frame layout depends on, so a run never relies on what the
// previous one (or power-on reset) left. Display ON is sent separately, after the frame.
inline std::vector<std::uint8_t> init_sequence()
{
    return {
        kDisplayOff,
        0xD5, 0x80,  // display clock divide ratio / oscillator frequency (reset value)
        0xA8, 0x3F,  // multiplex ratio: 64 rows
        0xD3, 0x00,  // display offset 0
        0x40,        // display start line 0
        0x8D, 0x14,  // charge pump on: the panel voltage is made from VCC
        0x20, 0x00,  // horizontal addressing: column, then page, wraps to (0, 0)
        0xA1,        // segment remap: column 127 -> SEG0 (as the module is wired)
        0xC8,        // COM scan direction remapped: page 0 at the top
        0xDA, 0x12,  // COM pins: alternative configuration (128x64)
        0x81, 0xCF,  // contrast
        0xD9, 0xF1,  // pre-charge period (internal charge pump)
        0xDB, 0x40,  // VCOMH deselect level
        0x2E,        // scrolling off
        0xA4,        // pixels follow RAM (0xA5 would light all)
        0xA6,        // normal (0xA7 = inverse)
    };
}

// false when (x, y) is off the panel; the frame is left unchanged.
inline bool set_pixel(Frame &f, int x, int y)
{
    if (x < 0 || x >= kWidth || y < 0 || y >= kHeight)
        return false;
    f[(y / 8) * kWidth + x] |= static_cast<std::uint8_t>(1u << (y % 8));
    return true;
}

// 5x7 glyphs, one byte per column, bit 0 = top row. Only what the fixed string needs;
// the full font is Step 10-b's job.
inline const std::uint8_t *glyph(char c)
{
    static const std::uint8_t kSpace[5] = {0, 0, 0, 0, 0};
    static const std::uint8_t kD[5] = {0x7F, 0x41, 0x41, 0x22, 0x1C};
    static const std::uint8_t kE[5] = {0x7F, 0x49, 0x49, 0x49, 0x41};
    static const std::uint8_t kG[5] = {0x3E, 0x41, 0x49, 0x49, 0x7A};
    switch (c) {
    case ' ': return kSpace;
    case 'D': return kD;
    case 'E': return kE;
    case 'G': return kG;
    default: return nullptr;
    }
}

// Each glyph is 5 columns plus a 1-column gap, all multiplied by scale; no trailing gap.
inline int text_width(const char *s, int scale)
{
    int n = static_cast<int>(std::strlen(s));
    return n ? (n * 6 - 1) * scale : 0;
}

// Draws s with its top-left corner at (x, y); pixels off the panel are clipped.
// false (and nothing drawn) if s has a character the table lacks.
inline bool draw_text(Frame &f, int x, int y, const char *s, int scale)
{
    for (const char *p = s; *p; ++p)
        if (!glyph(*p))
            return false;
    for (const char *p = s; *p; ++p, x += 6 * scale) {
        const std::uint8_t *g = glyph(*p);
        for (int col = 0; col < 5; ++col)
            for (int row = 0; row < 7; ++row)
                if (g[col] >> row & 1)
                    for (int dx = 0; dx < scale; ++dx)
                        for (int dy = 0; dy < scale; ++dy)
                            set_pixel(f, x + col * scale + dx, y + row * scale + dy);
    }
    return true;
}

// The messages that put a whole frame on the panel: first the window (columns 0..127,
// pages 0..7, which also moves the address pointer to (0, 0) whatever a previous write
// left), then one data message per page.
inline std::vector<std::vector<std::uint8_t>> frame_writes(const Frame &f)
{
    std::vector<std::vector<std::uint8_t>> msgs;
    msgs.push_back(command_frame({0x21, 0x00, kWidth - 1, 0x22, 0x00, kPages - 1}));
    for (int page = 0; page < kPages; ++page)
        msgs.push_back(data_frame(&f[page * kWidth], kWidth));
    return msgs;
}

// The acceptance pictures (Step 9's oled_probe, Step 10-a's edge_oled_ctl). Each one shows
// at a glance whether the panel is mirrored or upside down. Anything else is blank.
//   pixel    the four corners and the centre
//   pattern  1-pixel border and a diagonal from the top-left corner
//   edge     "EDGE", 4x scaled, centred
inline Frame test_picture(const char *mode)
{
    Frame f{};
    if (!std::strcmp(mode, "pixel")) {
        set_pixel(f, 0, 0);
        set_pixel(f, kWidth - 1, 0);
        set_pixel(f, 0, kHeight - 1);
        set_pixel(f, kWidth - 1, kHeight - 1);
        set_pixel(f, kWidth / 2, kHeight / 2);
    } else if (!std::strcmp(mode, "pattern")) {
        for (int x = 0; x < kWidth; ++x) {
            set_pixel(f, x, 0);
            set_pixel(f, x, kHeight - 1);
        }
        for (int y = 0; y < kHeight; ++y) {
            set_pixel(f, 0, y);
            set_pixel(f, kWidth - 1, y);
            set_pixel(f, y, y);
        }
    } else if (!std::strcmp(mode, "edge")) {
        const int scale = 4;
        draw_text(f, (kWidth - text_width("EDGE", scale)) / 2, (kHeight - 7 * scale) / 2,
                  "EDGE", scale);
    }
    return f;
}

}  // namespace ssd1306
