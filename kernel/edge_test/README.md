# edge_test：最小 character device（Step 2）+ ioctl 控制通道（Step 3）

`edge_test.ko` 建立 `/dev/edge_test`，背後是一塊 256 bytes 的 kernel buffer。這一步沒有實體硬體：互動的兩端是 userspace 程式（`echo`、`cat`、Python 測試）和這個 module，中間經過 system call 與 VFS。

```text
echo "hello" > /dev/edge_test
  → write(2) → VFS → edge_test_fops.write → edge_test_write() → edge_test_buf[256]
cat /dev/edge_test
  → read(2)  → VFS → edge_test_fops.read  → edge_test_read()  → copy_to_user()
```

## Build / load / unload

```bash
make -C kernel/edge_test               # 對 /lib/modules/$(uname -r)/build 編譯
sudo bash kernel/edge_test/load.sh     # insmod edge_test.ko
echo hello > /dev/edge_test            # 節點為 0666，不需 sudo
cat /dev/edge_test
sudo bash kernel/edge_test/unload.sh   # rmmod edge_test
make -C kernel/edge_test clean
```

## 行為規格

| 操作 | 結果 |
|---|---|
| 以寫入模式加 `O_TRUNC` 開啟（shell 的 `>`） | 清空 buffer |
| `write()` | 從 file position 寫入；超過 256 bytes 的部分截掉，回傳實際寫入數（short write） |
| buffer 已滿時再 `write()` | `-ENOSPC`（shell 顯示 `No space left on device`） |
| `read()` | 回傳 `[pos, 已存長度)` 的內容，讀完回 0（EOF） |
| user pointer 無效 | `-EFAULT`，原有內容不變 |

所有 buffer 存取都在同一個 mutex 底下。

## ioctl 控制通道（Step 3）

`read()`/`write()` 是資料通道；`ioctl()` 是控制通道，讀寫 module 保存的一個 32-bit value。這個 value 和資料 buffer 互不影響，每次載入都從 0 開始。命令定義在 `include/edge_test_ioctl.h`，kernel 和 userspace 共用同一份 header：

| 命令 | 編號 | 行為 |
|---|---|---|
| `EDGE_TEST_GET_VALUE` | `_IOR(0xEB, 0x01, __u32)` = `0x8004EB01` | 把 value 寫到 `*arg` |
| `EDGE_TEST_SET_VALUE` | `_IOW(0xEB, 0x02, __u32)` = `0x4004EB02` | 用 `*arg` 取代 value |
| 其他任何號碼 | — | `-ENOTTY` |
| 指標無效（含 NULL） | — | `-EFAULT`，value 不變 |

C++ userspace 用 CMake 建置（在 repo 根目錄）：

```bash
cmake -S . -B build && cmake --build build
./build/edge_test_cli set 123
./build/edge_test_cli get              # 印出 123
```

`edge_test_cli` 的結束碼：0 成功、1 裝置或 ioctl 錯誤、2 用法錯誤。`set` 只接受十進位 0..4294967295。

## 用到的 kernel API

`alloc_chrdev_region()` → `cdev_init()` / `cdev_add()` → `class_create()` → `device_create()`（devtmpfs 建出 `/dev/edge_test`）；資料搬移用 `copy_from_user()` / `copy_to_user()`，ioctl 的單一數值用 `get_user()` / `put_user()`。`compat_ioctl = compat_ptr_ioctl` 讓 32-bit userspace 走同一個 handler。卸載時依相反順序釋放。

## 驗收

```bash
sudo bash scripts/verify_edge_test.sh 3
```

腳本會 build、核對 vermagic，然後做 3 次 load → 檢查 `/proc/devices` 與節點 → 跑 `tests/test_edge_test_device.py` → 以一般使用者執行 `echo`/`cat` → unload → 確認沒有殘留，最後檢查 `dmesg`。不需 root 時可單獨跑測試（module 已載入才會執行，否則 skip）：

```bash
python3 -m unittest discover -s tests -p test_edge_test_device.py -v
```

## 這一步不做

interrupt、實體硬體控制（Step 4 起）；不建立複雜的 binary protocol。
