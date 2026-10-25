// Test vectors for firmware/stm32f103/Core/Src/debounce.c (Step 12-b): the button on PA1, sampled
// once per millisecond by the SysTick interrupt. The state changes only after the raw level has
// held for DEBOUNCE_MS samples in a row; every debounced press adds one to the press counter.
// Exit status: 0 = all checks passed, 1 = a check failed.
#include <cstdio>

#include "../firmware/stm32f103/Core/Inc/debounce.h"

namespace {

int failures = 0;

void check_eq(const char *what, unsigned got, unsigned want)
{
    if (got != want) {
        std::printf("FAIL %s: got %u, want %u\n", what, got, want);
        ++failures;
    }
}

debounce fresh()
{
    debounce d;
    debounce_init(&d);
    return d;
}

void ticks(debounce &d, int raw, int n)
{
    for (int i = 0; i < n; ++i)
        debounce_tick(&d, raw);
}

void test_after_reset()
{
    debounce d = fresh();
    check_eq("released", d.pressed, 0);
    check_eq("no presses", d.presses, 0);
    check_eq("window", DEBOUNCE_MS, 20);
}

void test_press_needs_the_full_window()
{
    debounce d = fresh();
    ticks(d, 1, DEBOUNCE_MS - 1);
    check_eq("one sample short: still released", d.pressed, 0);
    ticks(d, 1, 1);
    check_eq("held for the window: pressed", d.pressed, 1);
    check_eq("counted once", d.presses, 1);
    ticks(d, 1, 500);
    check_eq("holding does not count again", d.presses, 1);
}

void test_release_needs_the_full_window()
{
    debounce d = fresh();
    ticks(d, 1, DEBOUNCE_MS);
    ticks(d, 0, DEBOUNCE_MS - 1);
    check_eq("released one sample short: still pressed", d.pressed, 1);
    ticks(d, 0, 1);
    check_eq("released", d.pressed, 0);
    check_eq("releasing does not count", d.presses, 1);
}

void test_bounce_restarts_the_window()
{
    debounce d = fresh();
    // contact bounce: short pulses never last the window
    for (int i = 0; i < 10; ++i) {
        ticks(d, 1, DEBOUNCE_MS - 1);
        ticks(d, 0, 1);
    }
    check_eq("bouncing: no press", d.pressed, 0);
    check_eq("bouncing: nothing counted", d.presses, 0);
    ticks(d, 1, DEBOUNCE_MS);
    check_eq("settles pressed", d.pressed, 1);
    // bounce on release: a glitch back to pressed does not count a second press
    ticks(d, 0, 5);
    ticks(d, 1, 2);
    ticks(d, 0, DEBOUNCE_MS);
    check_eq("released after a glitch", d.pressed, 0);
    check_eq("one press in total", d.presses, 1);
}

void test_counter_wraps()
{
    debounce d = fresh();
    for (int i = 0; i < 257; ++i) {
        ticks(d, 1, DEBOUNCE_MS);
        ticks(d, 0, DEBOUNCE_MS);
    }
    check_eq("257 presses wrap to 1", d.presses, 1);
}

}  // namespace

int main()
{
    test_after_reset();
    test_press_needs_the_full_window();
    test_release_needs_the_full_window();
    test_bounce_restarts_the_window();
    test_counter_wraps();
    if (failures) {
        std::printf("%d check(s) failed\n", failures);
        return 1;
    }
    std::printf("all debounce vectors passed\n");
    return 0;
}
