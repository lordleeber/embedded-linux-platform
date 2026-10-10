# Build the Step 4 overlay against the running kernel's dt-bindings headers.
#   make            build both polarity variants into $(OUT) (default: here)
#   make clean      remove them
KDIR ?= /lib/modules/$(shell uname -r)/build
OUT ?= .
DTC_CPP := cpp -nostdinc -undef -P -x assembler-with-cpp -I$(KDIR)/include

# cpp | dtc: fail on cpp's exit status too, and never leave a half-built dtbo.
SHELL := /bin/bash
.SHELLFLAGS := -o pipefail -c
.DELETE_ON_ERROR:

all: $(OUT)/edge-gpio-overlay.dtbo $(OUT)/edge-gpio-overlay-active-low.dtbo

$(OUT)/edge-gpio-overlay.dtbo: edge-gpio-overlay.dts
	$(DTC_CPP) $< | dtc -@ -q -I dts -O dtb -o $@ -

$(OUT)/edge-gpio-overlay-active-low.dtbo: edge-gpio-overlay.dts
	$(DTC_CPP) -DEDGE_LED_ACTIVE_LOW $< | dtc -@ -q -I dts -O dtb -o $@ -

clean:
	rm -f $(OUT)/edge-gpio-overlay.dtbo $(OUT)/edge-gpio-overlay-active-low.dtbo

.PHONY: all clean
