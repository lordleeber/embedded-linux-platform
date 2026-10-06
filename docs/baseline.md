# 驗收基線與踩坑紀錄

## Step 1：可重複的開發環境

- 驗收主機：Jetson Orin Nano Engineering Reference Developer Kit Super，Ubuntu 22.04.5 LTS，JetPack 套件 `6.2.1+b38`，L4T R36 revision 4.7，kernel `5.15.148-tegra`，aarch64。完整原始輸出見 [jetson-version.txt](jetson-version.txt)。
- 對照方法：在同一台 Jetson 執行 `bash scripts/check_host_env.sh`；逐項核對 board model、L4T release、kernel headers 和 8 個必需指令皆為 `PASS`。版本字串不設數值容差；kernel release / headers 路徑應一致。升級後先更新快照，再評估後續 module 相容性。
- 自動測試：`python3 -m unittest discover -s tests -v`，5 個案例通過，涵蓋全部可用、缺少 `dtc`、缺少 `v4l2-ctl` 時仍產生版本快照、缺少板型 / L4T 資料，以及 headers 目錄缺失時快照明確記錄 `no`。
- 教材檢查：`python3 scripts/check_book.py docs`。
- 硬體：尚未接線；接線驗收與 bus 通訊均未實測。

### 踩坑

- 原本以為有 `/lib/modules/$(uname -r)/build` 連結就能代表 headers 完全可用；腳本目前只驗證目錄可達，真正的 module build 須留待 Step 2 驗證。
- 原本以為 L4T release 可以直接代表已安裝的 JetPack 套件版本；這台機器兩者分開記錄，避免日後只看到 L4T 便推定 JetPack 版本。
- 原本以為快照中的 headers 路徑能代表目錄存在；路徑即使不存在也會被寫出。快照現在另記 `Kernel headers present: yes/no`，和 stdout 的檢查使用相同判斷。

## Step 2：最小 character device `/dev/edge_test`

- 驗收主機：同 Step 1（kernel `5.15.148-tegra`，L4T R36.4.7）。module 以 `/lib/modules/5.15.148-tegra/build` 編譯，`modinfo -F vermagic` 為 `5.15.148-tegra SMP preempt mod_unload modversions aarch64`，與 `uname -r` 一致。Step 1 留下的「headers 目錄存在不代表能編 module」這一項就此結案：實際 build 與 `insmod` 都成功了。
- 對照方法：`sudo bash scripts/verify_edge_test.sh 3`。實測 3 個 load/unload 循環 × 5 項檢查都 PASS；major 號 489（動態配置，換機或載入順序不同時可以不一樣，不設容差，只比對 `/proc/devices` 與節點的 major 是否一致）；`dmesg` 裡的 `registered` / `unregistered` 必須正好等於循環數，而且沒有 Oops / BUG / WARNING。
- 自動測試：`tests/test_edge_test_device.py` 共 12 個案例，涵蓋 round trip、EOF、分段讀、`O_TRUNC`、只讀開啟不清空、同一次 open 連續寫、剛好 256 bytes、超過容量時先 short write 再 `ENOSPC`、無效 pointer 回 `EFAULT` 且內容不變、shell `echo`/`cat`、shell 寫入超過容量會報錯，以及節點權限 0666。module 沒載入時這些案例會 skip，所以沒載入時 `python3 -m unittest discover -s tests` 是 `OK (skipped=12)`。
- 教材檢查：`python3 scripts/check_book.py docs` 加上新的 `python3 scripts/check_test_counts.py docs`（用 unittest loader 核對章裡 `data-tests` 宣稱的案例數，自身有 4 個測試）。
- 編譯時的 `warning: the compiler differs from the one used to build the kernel` 只是 gcc 套件的修訂號不同（`11.4.0-1ubuntu1~22.04` vs `~22.04.3`），屬於預期中的雜訊，不是失敗。
- 硬體：這一步不用外接硬體。

### 踩坑

- 原本以為 `copy_from_user()` 失敗時目的端完全不會被動到；實際上它會把沒複製成功的那段**清成 0**（`include/linux/uaccess.h` 的 `_copy_from_user` 有 `memset(to + (n - res), 0, res)`）。第一版直接把 kernel buffer 當目的端，結果一次 `EFAULT` 寫入就把原有的 `safe` 變成 4 個 `\0`。現在先複製到 stack 上的暫存區，成功才 `memcpy` 進去。之後的 driver 只要直接 copy 進共用狀態，都要留意這個變體。
- 原本以為 `python3 -m unittest tests.test_xxx` 可以直接跑；`tests/` 沒有 `__init__.py`，要用 `discover -s tests -p <file>`。
- 原本以為用 `sudo` 跑驗收腳本沒什麼影響；但如果用 root 身分 `make`，會在 tree 裡留下 root 所有的 `.o` / `.cmd` 檔，之後一般使用者就 `make clean` 不掉。現在腳本改用 `sudo -u "$SUDO_USER" make`。
- `class_create(THIS_MODULE, name)` 是 5.15 的簽名；Linux 6.4 起拿掉了 owner 參數。之後若升級 kernel（例如 Yocto 換 BSP），這裡會編譯失敗。
- 原本以為教材的程式碼節錄「抄的時候對照過」就不會錯；`uaccess.h` 那段的起始行號寫成 152（實際是 153），全書檢查和冷讀都沒抓到，因為冷讀只能拿我寫的起始行號往下推算。最後是用一段腳本把每個 `figure.listing` 和原始檔的指定行逐字比對才發現的。這次是首見，先記在這裡；若再發生，就把那段比對寫成 `scripts/` 裡的正式檢查。**（結案：Step 3 再次發生，已寫成 `scripts/check_listings.py`。）**

## Step 3：ioctl 控制通道 + C++ userspace client

- 驗收主機：同 Step 1、2。對照方法沿用同一支 `sudo bash scripts/verify_edge_test.sh 3`，只加不換：迴圈前多一步 CMake build（`edge_test_cli`、`test_edge_device`），每輪多三項：C++ ioctl 測試（root）、CLI 測試（一般使用者）、第 2 輪起檢查 reload 後 value 歸零。實測 3 輪全部 PASS，`=== 0 failure(s)`；Step 2 原有的 5 項檢查與 dmesg 檢查沒有退化（major 仍是 489，load/unload 各 3 筆）。
- 介面：magic `0xEB`，`EDGE_TEST_GET_VALUE = _IOR(0xEB, 1, __u32) = 0x8004EB01`、`EDGE_TEST_SET_VALUE = _IOW(0xEB, 2, __u32) = 0x4004EB02`。這兩個數值用 `static_assert` 釘在 `tests/test_edge_device.cpp` 裡，數值是照 `_IOC` 位元格式手算的，不是從實作抄的。value 是整個 module 共用一份（不是每個 open 各一份），每次載入從 0 開始。
- 自動測試：`tests/test_edge_device.cpp` 13 項（需要裝置，沒裝置時結束碼 77）；`tests/test_edge_test_cli.py` 10 個案例（header 在 C / C++ 都能編譯、header 只用固定大小型別、CLI 用法錯誤回 2、找不到裝置回 1；裝置 set/get 1 個案例在沒裝置時 skip）；`tests/test_check_listings.py` 4 個案例。沒載入 module 時 `python3 -m unittest discover -s tests` 是 `OK (skipped=13)`。
- 紅燈紀錄：對 Step 2 版的 module（沒有 ioctl）跑 C++ 測試，13 項中 9 項 FAIL，CLI 裝置測試 3 個 subtest FAIL。**有 4 項在舊 module 上本來就 PASS、沒有真正紅過**：未知 nr、外來 magic、參數大小不對（三者都預期 `ENOTTY`，而沒有 ioctl 時任何呼叫都回 `ENOTTY`），以及「ioctl 不動資料 buffer」。它們是防止日後退化的守門測試，強度要靠之後的變異測試才能證明。
- 硬體：這一步不用外接硬體。

### 踩坑

- 原本以為 ioctl magic 只要挑一個「看起來沒人用」的字元就好；`'E'` 在這台的 uapi headers 裡已經被 evdev 等用了 36 次。L4T 的 headers 套件也沒附 `Documentation/userspace-api/ioctl/ioctl-number.rst`，最後是搜尋本機 uapi headers，再對照上游 v5.15 的登記表，才選定 `0xEB`。
- 原本以為 ioctl 號碼只由 magic 和 nr 決定；其實參數大小也編進號碼裡，所以 `_IOR(0xEB, 1, __u64)` 是另一個號碼，會落到 `default` 回 `ENOTTY`。這也是 header 只能用 `__u32` 這種固定大小型別的原因：用 `unsigned long` 的話，32-bit 和 64-bit 程式算出的號碼會不同。
- Step 2 的 `copy_from_user` 坑在這裡換了個樣子：`SET` 先 `get_user()` 到區域變數，成功才寫進 `edge_test_value`，壞指標時 value 不變（有測試守著）。
- 原本以為驗收腳本可以直接用 root 跑 CLI 的 Python 測試；但那支測試第一次執行會跑 CMake，用 root 跑就會在 `build/` 留下 root 所有的檔案，是 Step 2「不要 sudo make」那個坑的變體。現在 CLI 測試以 `sudo -u "$SUDO_USER"` 執行。
- 原本以為加 ioctl 不會影響 Step 2 的章；結果 `edge_test.c` 行號整體下移，`step02.html` 的 9 段節錄有 8 段過期，而 `check_book.py` 不檢查這件事。這是 Step 2 那條「節錄行號」坑的第二次發生，所以照當時的約定寫成正式檢查 `scripts/check_listings.py`，並用舊版 `step02.html` 確認它會抓到那 8 段。Step 2 那條紀錄就此結案。
