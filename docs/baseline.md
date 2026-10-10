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

## Step 4-a：userspace GPIO output（C++ GPIO v2 uAPI）

- 拆分紀錄：原 Step 4（kernel driver + DT）在實機驗收時發現 LED 不亮，問題在 pad 而不在 driver；加上原 Step 4 已累積約 930 行，超過 800 行上限，所以拆成 4-a（userspace 先把電路、pad、GPIO line 分層驗證）與 4-b（原 kernel 版）。
- 驗收主機：同 Step 1–3。接線：pin 29 → 330 Ω → 紅色 LED → pin 30（見 [hardware-wiring.md](hardware-wiring.md)）。
- 對照方法：`sudo bash scripts/verify_edge_gpio_blink.sh`。實測 `=== 0 failure(s)`：
  - pad 關閉（`0x458`）：pinconf `pull=2 tristate=1 enable-input=1`；`edge_gpio_blink` 執行中 debugfs 讀到 `hi` → `lo`；**LED 不亮（人眼）**。
  - pad 開啟（`0x400`）：pinconf `pull=0 tristate=0 enable-input=0`；debugfs `hi` → `lo`；**LED 閃爍（人眼，取樣 5 次 + 兩個實機測試各 5 次，約 15 次）**；line 105 結束後 `unused`；pad 還原成開始時的值。
  - 時序容差：程式固定 500 ms on / 500 ms off；腳本在看到 consumer 後 0.2 s 取 `hi`、再 0.5 s 取 `lo`，兩點各離切換點至少 200 ms。
- 自動測試：`tests/test_pad_pin29.py` 8 個案例（假的 `/dev/mem` 稀疏檔：解碼、open/close、保留其他 bit、剛開機 bit 10 為 0 也能 open、不認得的值含全 0 一律拒寫、用法錯誤）；`tests/test_edge_gpio_blink.py` 3 個實機案例（`EDGE_GPIO_HW=1` 才跑、也才建置：閃完釋放 line；執行中 `gpioinfo` 顯示 `"edge_gpio_blink"` output，第二個程式拿到 busy、結束碼 1；亮燈中送 SIGINT / SIGTERM，1 秒內結束、結束碼 1、印 `interrupted`、line 已釋放）。沒有 `EDGE_GPIO_HW` 時全套 `OK (skipped=16)`。
- 紅燈紀錄：兩支測試在程式不存在時都紅過（pad 腳本 9 個 failure，blink 測試在 CMake 找不到 target 時 error）。變異測試：output 改 input、改 consumer 名稱、改錯誤訊息、拿掉低位元組檢查、漏清 pull、整個暫存器清 0、不裝 SIGTERM handler、不印 `interrupted`，各自都讓測試失敗。code review（PR #4）後補的三個案例（全 0 拒寫、bit 10 規則、signal）也是先紅再修。
- 尚未涵蓋：程式結束時 pin 是否為 low，自動化看不到（line 釋放後 debugfs 不再列出），只靠人眼看到 LED 最後熄滅。精簡版沒有參數，chip 不存在 / line 超出範圍 / 寫入失敗的錯誤路徑沒有測試（寫入失敗無法從外部觸發）。SIGKILL 或 crash 時 LED 仍可能留在亮的狀態。
- 已知限制（`pad_pin29.py` 開頭有寫）：暫存器的讀改寫走 Python memoryview，CPython 不保證是單一一次 32-bit 匯流排存取（實測正常）；讀與寫之間 kernel 的 pinctrl driver 也可能改同一個暫存器。這支是實驗工具，4-b 改用 DT pinctrl 後就不再需要。

### 踩坑

- 原本以為 `gpioinfo` 和 `/sys/kernel/debug/gpio` 顯示 output `hi`，就代表腳位有 3.3 V；它們讀的是 GPIO controller 的 output 暫存器。JP6 開機時 pin 29 的 pad（`soc_gpio32_pq5`）是 `tristate=1`，暫存器是 1，腳位卻沒有輸出。用 `gpioset`（完全不經過我們的 code）對照也一樣不亮，才確定問題在 pad。驗收若只看軟體層會全部 PASS，必須人眼看 LED，並檢查 pinconf。
- 原本以為 header pin 的 GPIO 像 JP5 教學那樣開機就能用；JP6 要靠 pinmux（jetson-io、DT overlay 或 devmem）先把 pad 打開。網路上的 Python 範例「直接能用」，多半是 JP5 時代寫的，或作者先跑過 jetson-io（它產生的就是 pinmux overlay）。
- pinmux 暫存器位址 `0x02430068` 不是從 TRM 查來的，而是先只讀、比對低位元組 `0x58` 拆成 pull=up / tristate / input，和 debugfs 完全一致後才寫入。`pad_pin29.py` 把這個保護寫死：低位元組不是 `0x58` 或 `0x00` 就拒寫。
- 原本以為暫存器 bit 10 意義不明，所以保留不動；這次實測顯示 bit 10 為 1 時 pinconf 都是 `gpio-mode=1`，而開機後、任何程式請求 line 之前量到的是 `gpio-mode=0`。推論 bit 10 是 GPIO/SFIO 選擇，在 line 第一次被請求時由 GPIO 這一側設定（實測推論，未對照 TRM）。
- 原本以為 `gpioset --mode=time` 結束後 LED 會熄；Tegra 的 GPIO driver 釋放 line 時不會把輸出改回 0，pad 開著時 LED 會一直亮。程式（以及 4-b 的 driver）都要在釋放前自己寫 0。
- 原本以為 debugfs `pinconf-groups` 一個 group 一行；實際是 group 名稱一行，每個設定各一行。第一版用 `grep` 只抓到名稱那行，造成兩個假 FAIL；改用 awk 收到下一個 group 為止。4-b 的 `verify_edge_gpio.sh` 有同樣的寫法，回到 4-b 時要一起改。
- 原本以為「低位元組 `0x00`」就足以認定 pad 已開啟；code review 指出很多不相干的位址讀出來就是全 0，位址一旦錯了，`close` 會把 `0x58` 寫進不認識的暫存器。現在「已開啟」要求低位元組 `0x00` 且 bit 10 為 1（實測值 `0x400`），全 0 一律拒寫。代價：剛開機還沒人請求過 line 時 `open` 會得到 `0x000`，之後要先跑過一次 GPIO 程式，`close` 才會被接受。
- 原本以為程式迴圈最後一次寫 0 就保證 LED 熄滅；code review 指出兩個漏洞：寫入的 ioctl 沒檢查回傳值（全失敗也回 0），以及 Ctrl-C / `kill` 落在亮燈時會直接結束，留下亮著的 LED（正是上一條 Tegra 不歸零的坑）。現在每次寫入都檢查，SIGINT / SIGTERM 只設旗標，迴圈結束後一律寫 0 再釋放。4-b 的 driver 在 `remove()` 也要注意同一件事。
- 原本以為驗收腳本把 unittest 輸出寫到 `/tmp/<name>.$$` 沒問題；但重新導向是 root 的 shell 做的，檔名可猜，別的使用者可以預先放 symlink（Ubuntu 預設的 `fs.protected_symlinks` 會擋下大部分情況）。本步的腳本改用 `mktemp`；Step 2/3 的 `verify_edge_test.sh` 和 4-b 的 `verify_edge_gpio.sh` 有同樣寫法，排進 4-b 一起修。
- 板子上原裝的 Jetson.GPIO 一 import 就 `Could not determine Jetson model`（不認得 Super 型號），改用 `python3-libgpiod` 做 Python 對照實驗；入庫的 C++ 版直接用 kernel 的 GPIO v2 uAPI，不依賴 libgpiod。
