# Phase 1 — Linux Kernel Module 基礎

> Parent roadmap: `ROADMAP.md`

## 目的

先真正跨過 userspace / kernel boundary。

不要只寫：

```c
printk("hello\n");
```

而是直接建立：

```text
/dev/edge_test
```

## 實作內容

建立：

```text
edge_kernel_lab/
├── Makefile
└── edge_test.c
```

實作：

```c
module_init()
module_exit()

open()
read()
write()
release()
unlocked_ioctl()
```

userspace 寫一個：

```text
test_edge_device.cpp
```

操作：

```cpp
open()
read()
write()
ioctl()
close()
```

## 必須理解

```text
userspace
    ↓
system call
    ↓
VFS
    ↓
file_operations
    ↓
your driver
```

## 完成標準

可以做到：

```bash
echo "hello" > /dev/edge_test
cat /dev/edge_test
```

並能從 C++ 使用 `ioctl()` 控制 driver。

---

<!-- STEP_PLAN_START -->
## Step 規劃

### Step 2 — 最小 Character Device

**目標**

建立真正可被 userspace `open/read/write` 的 `/dev/edge_test`。

**實作範圍**

- kernel module skeleton
- character device registration
- `open()`
- `read()`
- `write()`
- `release()`
- Makefile
- module load/unload script


<!-- STEP_DETAIL_START -->
### 這一步到底要做什麼

這一步要理解「userspace 對 `/dev/...` 做 `read()`，最後怎麼進到你自己寫的 kernel function」。

建立一個最小 character device：

```text
/dev/edge_test
```

driver 至少要有：

```c
open()
read()
write()
release()
```

建議先用一塊固定大小的 kernel buffer，例如 256 bytes。`write()` 把 userspace 資料複製進 kernel buffer，`read()` 再把內容送回 userspace。

核心 API 要實際碰到：

```text
alloc_chrdev_region()
cdev_init()
cdev_add()
class_create()
device_create()
copy_from_user()
copy_to_user()
```

資料流：

```text
echo "hello" > /dev/edge_test
        ↓
write syscall
        ↓
VFS
        ↓
file_operations.write
        ↓
edge_test_write()
        ↓
kernel buffer
```

### 預期檔案

```text
kernel/edge_test/
├── Makefile
├── edge_test.c
└── README.md
```

### 驗證時要觀察

- `dmesg`
- `/proc/devices`
- `/dev/edge_test`
- module load/unload 後 device node 是否正確建立/消失
- 超過 buffer 長度時是否安全拒絕或截斷

### 這一步不做

- 不做 ioctl
- 不做 interrupt
- 不做真實硬體控制
<!-- STEP_DETAIL_END -->

**驗收條件**

```bash
echo "hello" > /dev/edge_test
cat /dev/edge_test
```

必須能反覆 `insmod` / `rmmod`，不能留下壞掉的 device node。

### Step 3 — ioctl + C++ userspace client

**目標**

建立 kernel/userspace 的 control path。

**實作範圍**

- 定義共享 ioctl header
- 實作至少 2 個 ioctl command
- 建立 `test_edge_device.cpp`
- 錯誤處理
- 基本 regression test


<!-- STEP_DETAIL_START -->
### 這一步到底要做什麼

這一步把「資料 read/write」和「控制命令」分開。`read()/write()` 適合資料流，`ioctl()` 適合設定狀態或查詢控制資訊。

定義共用 header，例如：

```text
include/edge_test_ioctl.h
```

先做兩個 command：

```text
EDGE_TEST_GET_VALUE
EDGE_TEST_SET_VALUE
```

例如 kernel 內保存：

```c
uint32_t value;
```

C++ userspace：

```text
apps/edge_test_cli.cpp
```

提供：

```bash
./edge_test_cli get
./edge_test_cli set 123
```

要實際理解：

```text
_IO()
_IOR()
_IOW()
_IOWR()
```

以及 ioctl number 為什麼不能隨便撞號。

### 資料流

```text
C++ ioctl(fd, EDGE_TEST_SET_VALUE, &value)
        ↓
sys_ioctl
        ↓
file_operations.unlocked_ioctl
        ↓
edge_test_ioctl()
```

### 驗證

至少測：

- 正常 get/set
- invalid command
- null/bad pointer
- module unload/reload 後 state 行為
- 32/64-bit 型別不要使用不固定大小的結構

### 這一步不做

- 不碰 GPIO/I2C
- 不建立複雜 binary protocol
<!-- STEP_DETAIL_END -->

**驗收條件**

```text
C++ app
  ↓ ioctl()
VFS
  ↓
file_operations
  ↓
driver
```

使用者可以從 C++ 控制 driver state。
<!-- STEP_PLAN_END -->
