/* Step 12-b: debounce for the button on PA1, without any hardware access.
 *
 * main.c's SysTick interrupt calls debounce_tick() once per millisecond with the raw pin level
 * (nonzero = pressed, i.e. the pin is low). The debounced state changes only after the raw
 * level has held for DEBOUNCE_MS ticks in a row; each change to pressed adds one to presses,
 * which wraps at 256. Tested on the host by tests/test_debounce.cpp.
 */
#ifndef DEBOUNCE_H
#define DEBOUNCE_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define DEBOUNCE_MS 20

struct debounce {
    uint8_t pressed; /* debounced state */
    uint8_t raw;     /* last raw sample */
    uint8_t held;    /* ticks the raw level has held, up to DEBOUNCE_MS */
    uint8_t presses;
};

void debounce_init(struct debounce *d);
void debounce_tick(struct debounce *d, int raw_pressed);

#ifdef __cplusplus
}
#endif

#endif
