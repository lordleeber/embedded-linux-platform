# Out-of-tree build against the running kernel's headers.
#   make            build edge_button.ko
#   make clean      remove build products
obj-m := edge_button.o
ccflags-y := -I$(src)/../../include

KDIR ?= /lib/modules/$(shell uname -r)/build

all:
	$(MAKE) -C $(KDIR) M=$(CURDIR) modules

clean:
	$(MAKE) -C $(KDIR) M=$(CURDIR) clean

.PHONY: all clean
