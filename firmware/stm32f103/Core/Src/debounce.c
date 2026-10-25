/* Step 12-b: button debounce; see debounce.h. No hardware access here. */
#include "debounce.h"

void debounce_init(struct debounce *d)
{
    d->pressed = 0;
    d->raw = 0;
    d->held = 0;
    d->presses = 0;
}

void debounce_tick(struct debounce *d, int raw_pressed)
{
    uint8_t raw = raw_pressed != 0;

    if (raw != d->raw) {
        d->raw = raw;
        d->held = 1;
    } else if (d->held < DEBOUNCE_MS) {
        d->held++;
    }
    if (d->held >= DEBOUNCE_MS && raw != d->pressed) {
        d->pressed = raw;
        if (raw)
            d->presses++;
    }
}
