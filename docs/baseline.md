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
- 原本以為暫存器 bit 10 意義不明，所以保留不動；這次實測顯示 bit 10 為 1 時 pinconf 都是 `gpio-mode=1`，而開機後、任何程式請求 line 之前量到的是 `gpio-mode=0`。推論 bit 10 是 GPIO/SFIO 選擇，在 line 第一次被請求時由 GPIO 這一側設定（實測推論，未對照 TRM）。**（更正：Step 4-b 實測推翻了「請求時設定」，見 Step 4-b 踩坑。）**
- 原本以為 `gpioset --mode=time` 結束後 LED 會熄；Tegra 的 GPIO driver 釋放 line 時不會把輸出改回 0，pad 開著時 LED 會一直亮。程式（以及 4-b 的 driver）都要在釋放前自己寫 0。
- 原本以為 debugfs `pinconf-groups` 一個 group 一行；實際是 group 名稱一行，每個設定各一行。第一版用 `grep` 只抓到名稱那行，造成兩個假 FAIL；改用 awk 收到下一個 group 為止。4-b 的 `verify_edge_gpio.sh` 有同樣的寫法，回到 4-b 時要一起改。**（結案：4-b 已改。）**
- 原本以為「低位元組 `0x00`」就足以認定 pad 已開啟；code review 指出很多不相干的位址讀出來就是全 0，位址一旦錯了，`close` 會把 `0x58` 寫進不認識的暫存器。現在「已開啟」要求低位元組 `0x00` 且 bit 10 為 1（實測值 `0x400`），全 0 一律拒寫。代價：剛開機還沒人請求過 line 時 `open` 會得到 `0x000`，之後要先跑過一次 GPIO 程式，`close` 才會被接受。
- 原本以為程式迴圈最後一次寫 0 就保證 LED 熄滅；code review 指出兩個漏洞：寫入的 ioctl 沒檢查回傳值（全失敗也回 0），以及 Ctrl-C / `kill` 落在亮燈時會直接結束，留下亮著的 LED（正是上一條 Tegra 不歸零的坑）。現在每次寫入都檢查，SIGINT / SIGTERM 只設旗標，迴圈結束後一律寫 0 再釋放。4-b 的 driver 在 `remove()` 也要注意同一件事。
- 原本以為驗收腳本把 unittest 輸出寫到 `/tmp/<name>.$$` 沒問題；但重新導向是 root 的 shell 做的，檔名可猜，別的使用者可以預先放 symlink（Ubuntu 預設的 `fs.protected_symlinks` 會擋下大部分情況）。本步的腳本改用 `mktemp`；Step 2/3 的 `verify_edge_test.sh` 和 4-b 的 `verify_edge_gpio.sh` 有同樣寫法，排進 4-b 一起修。**（結案：4-b 已改。）**
- 板子上原裝的 Jetson.GPIO 一 import 就 `Could not determine Jetson model`（不認得 Super 型號），改用 `python3-libgpiod` 做 Python 對照實驗；入庫的 C++ 版直接用 kernel 的 GPIO v2 uAPI，不依賴 libgpiod。

## Step 4-b：GPIO output + Device Tree（kernel driver `edge_gpio`）

- 驗收主機：同前。接線同 4-a（pin 29 → 330 Ω → 紅色 LED → pin 30，active-high）。overlay 以 `scripts/install_edge_gpio_overlay.py` 加進 extlinux.conf 的 DEFAULT label（`JetsonIO`）的 `OVERLAYS`，接在原有 IMX219 overlay 後面；開機後 `/proc/device-tree/edge-led` 有 `compatible`、`led-gpios`（phandle、`0x7d`、flags `0`）、`pinctrl-0`、`pinctrl-names = "default"`，`pinmux@2430000` 底下多了 `edge-led-pins/pin29`。
- 對照方法：`sudo bash scripts/verify_edge_gpio.sh --blink 3`。實測（2026-10-10）`=== 0 failure(s)`：
  - 開機後、insmod 前：`pad_pin29.py show` 讀到 `0x00000058`（tristate；bit 10 為 0）。
  - insmod 後 pinconf `pull=0 tristate=0 enable-input=0 … gpio-mode=0`：pad 由 DT 的 pinctrl "default" 狀態在 probe 前打開，沒有用 devmem。
  - driver 綁定期間 4-a 的 `edge_gpio_blink` 得到 `request line 105: Device or resource busy`、結束碼 1。
  - 3 輪 × 每輪：bound、`/dev/edge_gpio` 出現、`gpioinfo` 顯示 `"led" output active-high`、初始 0 / `lo`、寫 1 → `hi`、寫 0 → `lo`、device unittest 6 個案例、開著檔案時 rmmod 被拒、寫 1 後 rmmod、節點消失、line 釋放。dmesg 3 probe / 3 remove，無 Oops。
  - **LED（人眼）**：第 1 輪 5 次慢閃可見，其餘步驟是快閃。
  - rmmod 後 pinconf 仍是 `tristate=0`（`gpio-mode=1`）：pinctrl 狀態不會在 unbind 時還原。
- 沒有 DT node 的對照（overlay 安裝前，同一支腳本自動切換模式）：insmod 後 driver 註冊在 platform bus、沒有任何 device 綁定、`/dev/edge_gpio` 不存在、line 105 未被動到，10 項 PASS。
- 第一版 overlay（沒有 pinctrl 狀態）的實測：33 項 PASS、只有「pad tristated」FAIL，LED 不亮；這就是拆出 4-a 的原因。
- 自動測試：`tests/test_edge_gpio_static.py` 14 個案例（cpp 出錯時 make 失敗且不留 dtbo；overlay 用 cpp + dtc 實際編譯後反組譯檢查：binding header 的 port Q = 15、兩種極性都編得出來、板型 compatible、節點 compatible、`led-gpios` cell 125 與 flags 0/1、`&gpio` / `&pinmux` 留成 fixup、pinctrl-0 指到設定 `soc_gpio32_pq5` tristate=0 / input=0 的狀態節點、pad 名稱和 NVIDIA 自家 hdr40 overlay 的 pin 29 一致；driver 端 of_match 與 overlay 一致、`devm_gpiod_get(dev, "led", GPIOD_OUT_LOW)`、沒有舊式整數 GPIO API、`suppress_bind_attrs`）；`tests/test_install_overlay.py` 12 個案例（假的 extlinux.conf；含空的 OVERLAYS 行、值有空白時拒改、remove 清掉每個 label、寫入後權限不變不留暫存檔）；`tests/test_edge_gpio_device.py` 6 個案例（裝置不存在時 skip，`EDGE_GPIO_REQUIRE=1` 時 fail）。沒有 module 時全套 `OK (skipped=22)`。
- 紅燈紀錄：靜態與 installer 測試在實作前全紅（11/11、8/8）；pinctrl 的 2 個靜態測試在加 `fragment@1` 前紅；device 測試在 overlay 開機、insmod 前以 `EDGE_GPIO_REQUIRE=1` 跑出 6 個 failure。變異測試：overlay 的 compatible 改錯、port 改成 P、tristate 改回 enable、pad 名稱寫錯、拿掉 `pinctrl-0`，各自都讓測試失敗。
- **只靠人眼**：rmmod 後腳位是否為 low（`remove()` 寫 0）。line 釋放後 debugfs 不再列出它，重新請求又會改到輸出值，自動化驗不到；刪掉 `remove()` 那一行，腳本照樣 PASS。驗收腳本最後會提示看 LED 是否熄滅；review 修正後重跑（2026-10-10）：慢閃 5 下、約 1 秒快閃後 LED 熄滅（人眼確認）。
- **未實測**：active-low。active-low dtbo 的 flags cell = 1 有靜態測試，driver 只用邏輯值 API（`gpiod_set_value_cansleep`、`GPIOD_OUT_LOW`），驗收腳本會從 DT 讀極性自動改預期；但沒有改接線（3.3 V → 電阻 → LED → pin 29）實機驗證。
- 規模：新增約 1090 行（其中測試約 450 行、腳本約 400 行，含 Step 2 腳本的修正），超過約 800 行的上限，而且沒有在實作前處理：4-b 的 kernel code 在決定拆分**之前**就已經寫好，拆分時只估了 4-a，沒有重估 4-b。

### 踩坑

- 原本以為 driver 的 probe、`gpioinfo`、debugfs 都正常，LED 就會亮；JP6 開機時 pad 是 tristate（4-a 已詳述）。正解是讓 DT 節點帶 `pinctrl-names = "default"` + `pinctrl-0`，指向 pinmux 底下的狀態節點；driver core 在 `probe()` 之前就套用它，driver 的 C code 不用改。
- 原本以為（4-a 的推論）pad 暫存器的 bit 10 在 line 被請求時就會設成 1；實測 kernel driver 持有 line、LED 正常閃爍時 pinconf 顯示 `gpio-mode=0`，rmmod 之後才變成 `gpio-mode=1`。所以 bit 10 不是 GPIO 輸出的必要條件，設定的時機與來源不明（未查 TRM）。4-a 的章、baseline 與 `pad_pin29.py` 的註解已改成只寫實測事實。
- 原本以為 rmmod 後 pad 會回到開機的 tristate；pinctrl 的 "default" 狀態在 driver unbind 後不會被還原，腳位仍由輸出暫存器驅動。這也是 `remove()` 一定要寫 0 的原因（Tegra 釋放 line 時不歸零）。
- 原本以為只能在開機後動態載入 overlay；這台 kernel 有 `CONFIG_OF_OVERLAY=y` 但沒有 `CONFIG_OF_CONFIGFS`，只能寫進 extlinux.conf 的 `OVERLAYS` 由 UEFI 在開機時合併，所以每改一次 overlay 都要重開機。重新執行 jetson-io 會重寫 `JetsonIO` label，可能洗掉我們加的 overlay。
- 原本以為 overlay 可以直接用 dtc 編；`TEGRA234_MAIN_GPIO(Q, 5)` 這類巨集來自 kernel 的 binding header，要先過 C 前處理器（`#include`、`#define`）再交給 dtc。`dts/Makefile` 的 `DTC_CPP` 照 kernel 的做法加了 `-nostdinc -undef -x assembler-with-cpp`，`-undef` 避免 gcc 預先定義的 `linux` 等巨集把 `linux,code` 這類屬性名稱展開掉（照慣例預防，這次沒有實際踩到）。
- DT 和 userspace 的 GPIO 編號不同：DT binding 是 `port × 8 + pin`（PQ.05 = 125），`gpiochip0` 的 line 是依實際腳數累加（105）。
- 寫 0 個 byte（`write(fd, b"", 0)`）也會進到 driver 的 `write()`；`kstrtouint_from_user` 對空字串回 `EINVAL`，device 測試守著這件事。
- 原本以為拆分時只要估新拆出來的那一半；4-b 的程式在拆分前就寫好了，沒有重估，結果超過上限（code review 指出）。教訓：拆分時兩邊都要重估行數，測試和驗收腳本也要算進去（這一步佔了將近一半）；已經寫好的部分也算。
- 原本以為 installer 只要處理 jetson-io 寫出來的那種 OVERLAYS 行；code review 找出四個會弄壞開機設定的情況：空的 `OVERLAYS` 行時 regex 的 `\s+` 吃掉換行、把 dtbo 黏到下一行；值裡有空白時對不上、在同一個 label 再加一行；直接覆寫檔案，寫到一半斷電就截斷；remove 只看 DEFAULT 卻無條件刪 dtbo。現在空白只比對 `[ \t]`、看不懂就拒改、remove 清每個 label 且最後才刪檔、寫入走暫存檔 + fsync + rename。先拿板子上真正的 extlinux.conf 複本做過 install / remove / install，結果和現用檔逐位元組相同。
- 原本以為 `cpp | dtc` 出錯時 make 一定會失敗；pipe 的結束碼只看 dtc，而 cpp 遇到 `#error` 回 1 卻照樣輸出全部內容，dtc 就會編出一個 dtbo。`dts/Makefile` 加了 `pipefail` 與 `.DELETE_ON_ERROR`，測試在 dts 副本加一行 `#error` 守著。（缺 header 這種錯，cpp 會中止、dtc 也會跟著失敗，所以原本的寫法剛好沒出事。）
- 原本以為驗收腳本開頭的「已經載入就 die」不會動到使用者的東西；但它寫在 `trap cleanup EXIT` 之後，die 時 cleanup 會把使用者自己載入的 module rmmod 掉（從 Step 2 的 `verify_edge_test.sh` 照抄來的，兩支都已改成先檢查再裝 trap）。
- 原本以為「driver 載入期間 userspace 拿到 busy」用 `$SUDO_USER` 去測最貼近實際；但該使用者不在 `gpio` 群組時會先拿到 `EACCES`，被誤判成 driver 的問題。這一步改用 root 執行（只跑已建好的程式，不會在 `build/` 留 root 的檔案）。
- 4-a 驗收腳本的兩個坑在這裡同樣存在並已修正：pinconf 的多行格式、root 寫入可猜的 `/tmp/<name>.$$`（`verify_edge_test.sh` 一併改成 `mktemp`）。改 `verify_edge_test.sh` 讓行號下移，step02 / step03 章的行號引用與節錄同步更新。

## Step 5-b：GPIO IRQ + blocking read（kernel driver `edge_button`）

- 拆分紀錄：驗收通過、寫教材時使用者指出這一步也能完全在 userspace 做（GPIO uAPI 的 edge event），kernel 版是為了教學親手寫 IRQ / wait queue。原 Step 5 因此改名為 5-b，另補 5-a（userspace 版）。這次拆分是教學上的考量，不是行數；5-b 本身仍超過上限（見下方「規模」）。

- 驗收主機：同前。接線（2026-10-10）：header pin 33（GPIO13 = PH.00，gpiochip0 line 43，DT cell 56）→ 四腳按鍵（對角兩腳）→ pin 34（GND）；pin 33 另經 **330 Ω** 上拉到 pin 1（3.3 V）。LED 在驗收前因材料不夠拆除；拆除前跑過 `sudo bash scripts/verify_edge_gpio.sh --blink 3`：`0 failure(s)`，人眼確認慢閃 5 下、最後熄滅（Step 4-b 回歸）。
- overlay：同一份 `dts/edge-gpio-overlay.dts` 加 `fragment@2`（`edge-button` 節點，`button-gpios = <&gpio TEGRA234_MAIN_GPIO(H, 0) GPIO_ACTIVE_LOW>`）與 `fragment@3`（`soc_gpio21_ph0`：pull-up、tristate、enable-input）；dtbo 由 999 bytes 變成 1589 bytes。開機後 `/proc/device-tree/edge-button` 有 `button-gpios compatible name pinctrl-0 pinctrl-names`。
- 對照方法：`sudo bash scripts/verify_edge_button.sh`。實測：
  - 沒有節點（overlay 重裝前的那次開機）：driver 註冊、不綁定、沒有 `/dev/edge_button`、line 43 沒被動到、dmesg 0 probe / 0 remove，10 項 PASS。
  - 有節點（2026-10-10，最後一次）`=== 0 failure(s)`：bound、`/dev/edge_button` 0444、line 43 `"button" input active-low [used]`、`/proc/interrupts` 有 `2200000.gpio 43 Edge edge_button`（IRQ 278）、pinconf `pull=2 tristate=1 enable-input=1`、放開時 pin `hi`、device unittest 8 個案例、reader 睡 3 秒 **0 個 CPU tick**、wchan `edge_button_read`、reader 卡住時 rmmod 被拒、SIGTERM 讓 reader 印 `interrupted` 結束碼 1、rmmod 後節點 / line / IRQ 都釋放、dmesg 無 Oops。
  - 按一下：`seq=1 pressed` → 0.188 s 後 `seq=2 released`，之後 2 秒內沒有多餘事件；原始 IRQ 4 次（前一輪是 2 次），debounce 後 2 筆事件。
  - 長按：pressed 與 released 相隔 2.85 s（前一輪 1.70 s），中間沒有事件。
  - 快速連按 6 秒：讀到 32 筆，pressed / released 交替、seq 連續、`dropped=0`；`event_count` 多了 34，差的 2 筆發生在 reader 被 timeout 結束後（關著時照設計不排事件）。全程 `irq_count=40 event_count=38 dropped=0`。
  - 容差：長按判定「held ≥ 1.0 s」（人按的時間不固定）；快速連按判定「≥ 4 筆、交替、seq 無跳號，或有 dropped 時 seq 跳號 = dropped」。debounce 20 ms、佇列 16 筆是常數，沒有測到佇列滿（人手按不到 16 筆 / 20 ms 以內）。
- 自動測試：`tests/test_edge_button_static.py` 20 個案例，code review 後 26 個（加了初始狀態順序、peek/skip、IRQ 時間戳、named pipe 假裝裝置的格式 / SIGTERM / signal 落在 read 之間）（overlay：兩個 dtbo 都有節點與 compatible、`button-gpios` cell 56 flags 1、fixup 指到 `edge-button`、pad 狀態 pull=2 / tristate=1 / input=1、pad 名稱和 NVIDIA hdr40 overlay 的 pin 33 一致、LED 節點仍在；driver：of_match、`devm_gpiod_get(dev, "button", GPIOD_IN)`、`gpiod_to_irq` + 雙邊緣、hard IRQ handler 不含會睡的呼叫、wait queue 與 `O_NONBLOCK`、`cancel_delayed_work_sync`、無舊式整數 API、`suppress_bind_attrs`、事件格式來自共用 header；header 在 C / C++ 下 16 bytes、offset 0/8/12、只用固定大小型別；`edge_button_wait` 用法錯誤回 2、找不到裝置回 1）；`tests/test_edge_button_device.py` 8 個案例（0444、`O_NONBLOCK` 沒事件回 `EAGAIN`、buffer < 16 回 `EINVAL`、第二個 open 回 `EBUSY`、關掉後能再開、blocking read 1.5 s 不吃 CPU 且被 signal 打斷、打斷後 fd 仍可用、sysfs 三個計數器）。沒有 module 時全套 `OK (skipped=30)`。
- 紅燈紀錄：實作前靜態測試 17 failures + 2 errors、device 測試（`EDGE_BUTTON_REQUIRE=1`）8 failures；「LED 節點仍在」「pad 名稱與 NVIDIA 一致」兩個在實作前就會過，是守門測試。pin 31 改成 pin 33 時，先改期望值看到 3 個 failure 再改 overlay。變異測試：flags 改 HIGH、cell 改錯、tristate 改 DISABLE、pull 改 NONE、pad 名稱寫錯、IRQ handler 裡加 `gpiod_get_value_cansleep`、`cancel_delayed_work_sync` 改成不等待的版本、只留 FALLING、header 的 `seq` 改 `__u64`、`pressed` 改 `unsigned int`，每一種都讓測試失敗。
- 只靠人眼 / 人手：所有按鍵事件（腳本只能請人按）。**未實測**：佇列滿時 `dropped` 與 seq 跳號（人手按不出來，只有程式邏輯）；`EFAULT` 時事件遺失（沒有測試）。
- 規模：新增程式約 1031 行（driver 285、驗收腳本 245、測試 346、C++ 74、其他 81），超過約 800 行上限。實作前估約 775 行，又一次把測試和驗收腳本估低（4-b 記過同一個坑）；發現時已實作完，經使用者決定維持單一 Step。

### 踩坑

- 原本以為 SoC pad 的內部上拉（DT 的 `nvidia,pull = <TEGRA_PIN_PULL_UP>`）就夠了，像 STM32 的 `GPIO_PULLUP` 一樣；pinconf 確實顯示 `pull=2`，但 pin 33 什麼都不接時讀到 0，第一次驗收按鍵全部沒有反應（`irq_count=0`）。（**Step 5-a 更正**：「什麼都不接時讀到 0」是單次 `gpioget` 的結果，而請求 line 後約 20 ms 內一律讀到 0，這一條不算證據；結論仍成立，靠的是 driver 持有 line 數秒時 debugfs 一直是 `lo`、按了 30 秒 `irq_count=0`。）Orin Nano devkit 載板規格書（SP-11324-001 v1.3，Table 3-3）寫明：除了 I2C 的 pin 3/5/27/28，40-pin header 的 GPIO 都經過 **TI TXB0108** 電平轉換（1.8 V ↔ 3.3 V，Note 3）。TXB 兩側的 buffer 約 4 kΩ（TI 典型值），會「保持」上一次的電位，SoC 的弱上拉在 1.8 V 側拉不動它。
- 原本以為照規格書的「上拉要 > 50 kΩ」選 51 kΩ 就好（第二次建議）；用 4 kΩ 的模型算，放開瞬間 pin 電壓 = 3.3 × 4k/(4k+R)，要超過 TXB 的高電位門檻（約 0.65 × 3.3 ≈ 2.15 V）才會翻回 1：51 kΩ 只有 0.24 V、10 kΩ 0.94 V（和論壇回報的「放開後約 1 V、卡低」一致），2.2 kΩ 2.13 V 在邊緣，1.5 kΩ 2.40 V、1 kΩ 2.64 V、330 Ω 3.05 V 才可靠。最後用手邊的 330 Ω，`gpioget` 放開 1、按下 0，驗收全過。「> 50 kΩ」那條是保護 pin 當**輸出**時的電位，按鍵 pin 只當輸入，所以刻意偏離。這個計算是推論（TI 典型值 + 論壇實測），沒有量測 4 kΩ。
- 原本以為 header 上直接接 SoC 的 I2C pin 可以拿來接按鍵（模組上已有 1.5 k / 2.2 kΩ 上拉）；pin 27/28 是 `i2c-1`（`c240000.i2c`），上面有板上的 `ina3221`（0x40）和 `fusb301`（0x25），不能挪用；pin 3/5 是 `i2c-7`（`c250000.i2c`），目前空著，但 Phase 3 起 INA219、OLED、STM32 都要用它。
- 原本以為挑 pin 看 GPIO 編號就好（第一版選 pin 31 = PQ.06，和 LED 的 PQ.05 同一個 port）；實體上 pin 31 和最近的 GND（pin 34）是斜對角，按鍵沒辦法直接跨上去，使用者提出改成相鄰的 pin 33/34。之後挑 pin 先看實體 header 上旁邊有沒有 GND / 3.3 V。
- 原本以為驗收腳本在「放開時電位不對」之後繼續請人按鍵也無妨；那次 pin 卡在 0，人白按了 30 多秒。現在電位不對就印出原因（外接 330 Ω～1 kΩ、四腳按鍵用對角）並跳過按鍵段。快速連按的提示原本寫 `RAPIDLY … until told to stop`，使用者以為是「快速按一下」，第一次只按了一下而 FAIL；改成「about 10 times」。
- 原本以為 `/proc/interrupts` 的計數從 insmod 開始；第二次驗收一開始就是 8，是上一次載入用同一個 IRQ 號（278）留下的累計。要看這次的中斷數，用 driver 自己的 sysfs `irq_count`。
- 第一次驗收 probe 時 dmesg 就印出 `pressed`（pin 卡低），後來是 `released`：probe 時讀一次初始狀態寫進 log，接線問題在 dmesg 第一行就看得出來。
- code review（PR #7）找出的五個問題，原本都以為沒事：
  - 原本以為空的 signal handler 加上「不設 `SA_RESTART`」就能保證 reader 被叫醒；signal 落在兩次 `read()` 之間（例如程式正在印輸出）時，處理完就沒了，下一次 `read()` 照睡，而驗收腳本的 `timeout` 沒有 `-k`，可能永遠卡住。現在 handler 設旗標、每次 read 前檢查，`timeout -k 2`。測試：stdout 接一個塞滿的 pipe（`F_SETPIPE_SZ` 4096），程式卡在 `write()` 時送 SIGTERM，排空後 3 秒內要結束。
  - 原本以為 baseline 寫的「有 dropped 時 seq 跳號 = dropped」腳本有在檢查；實際那個分支只看 `dropped > 0`。現在加總缺的 seq 數目，要等於 `dropped` 的增量（用範例資料跑過：缺 2 號回報 2；連號卻同狀態時失敗）。
  - 原本以為 probe 時先讀初始狀態再登記 IRQ 沒差；兩者之間按下的話，邊緣沒有中斷、`last` 過期，之後整組 pressed / released 默默消失且 seq 沒有缺口。改成登記 IRQ 之後才讀。
  - 原本以為 `copy_to_user` 失敗丟一筆事件可以接受（註解寫「seq 會顯示缺口」）；改成 `kfifo_peek` → `copy_to_user` → `kfifo_skip`，再用 mutex 讓同一個 fd 的兩個執行緒不會同時夾在 peek 與 skip 之間。這條路徑仍沒有自動測試（要先有一筆事件）。
  - 原本以為時間戳在 work 裡取就好（header 有寫明）；那比按下晚 20 ms 以上。改成 IRQ handler 在一串彈跳的第一個邊緣（`!delayed_work_pending()`）記錄，和 5-a 會用到的 `gpiolib-cdev` 一樣在 IRQ 打時間戳。實測佐證（`CONFIG_HZ=250`）：修正前 14 個時間戳的毫秒數 mod 4 全在 0.022～0.051 ms（work 的計時器只在 4 ms tick 上觸發），修正後 12 個分散在 0.9～4.0 ms。
- review 修正後重跑 `sudo bash scripts/verify_edge_button.sh`（2026-10-10）：`=== 0 failure(s)`；按一下 2 IRQ / 2 事件、長按 2.19 s、快速連按讀到 39 筆（交替、連號、dropped 0，event_count 多 42，差的 3 筆在 reader 結束後）、全程 `irq_count=52 event_count=46 dropped=0`。手動操作（章 5b.10）同樣重跑。
- review 另外指出：0444 加獨占 open 讓任何使用者都能霸佔裝置。kernel 的 misc device 不能設群組，比照 `/dev/gpiochip0`（`root:gpio 0660`）要用 udev rule，已排進 Phase 10 Step 26。seq 在關檔時照算、按住時開檔第一筆是 released，這兩點是設計，已寫進 header 與章。測試裡 `KDIR` / `decompile()` 和 4-b 的靜態測試重複，tests/ 不是 package，這次不抽共用 helper。
- 寫變異測試的輔助函式時用 `git checkout -- <file>` 還原檔案，把**還沒 commit 的** overlay 修改一起洗掉，最後的 `git stash -u` 又把新 driver 收進 stash（已救回）。還原請從自己備份的複本複製，不要用 git 對工作中的檔案做還原。

## Step 5-a：userspace GPIO input + edge event（gpiolib-cdev，不寫 driver）

- 驗收主機與接線：同 5-b（pin 33 → 按鍵 → pin 34，330 Ω 上拉到 pin 1）。這次開機**沒有載入過** `edge_button.ko`（重開機後直接驗收），所以看到的是開機預設 pad。
- 對照方法：`sudo bash scripts/verify_edge_gpio_button.sh`。實測（2026-10-10）`=== 0 failure(s)`：
  - 開機預設 pad：`pull=1 tristate=1 enable-input=1 … gpio-mode=0`（`pull=1` 是下拉；5-b 的 pinctrl 狀態是 `pull=2` 上拉）。輸入有開，不需要 pad 設定。
  - line 43 由 `"edge_gpio_button" input active-low [used]` 持有；穩定後 debugfs 讀到 `hi`（放開）。
  - reader 睡 3 秒 **0 個 CPU tick**，wchan `do_wait_intr`（gpiolib-cdev 的 wait queue；5-b 是 `edge_button_read`）；第二個 reader `Device or resource busy`；SIGTERM 印 `interrupted` 結束碼 1；line 釋放。
  - 實機 unittest（gpio 群組使用者）通過。
  - 按一下：`seq=2 pressed` → 0.167 s 後 `seq=3 released`（seq=1 是被丟掉的啟動假事件）；之後沒有多餘事件。長按 1.90 s。快速連按 6 秒讀到 24 筆，交替、連號。
  - 與 5-b 對照：同樣的檢查、同樣的輸出格式都通過；差在 5-b 有 `irq_count` / `dropped` 計數可看，5-a 只看得到 kernel 的 `seqno`。
- 自動測試：`tests/test_edge_gpio_button.py` 13 個案例（原始碼契約 6：v2 uAPI、line 43、不用 libgpiod、`INPUT | ACTIVE_LOW | EDGE_RISING | EDGE_FALLING`、debounce 20000 µs、rising → pressed、整筆讀 `gpio_v2_line_event`、signal 旗標且不設 `SA_RESTART`；CLI 2：用法錯誤回 2、chip 不存在回 1；實機 5，`EDGE_GPIO_HW=1` 才跑，不需要按：持有 line 時 gpioinfo 顯示 active-low input、**沒人按時 0.5 秒內不能有事件**、第二個實例 busy、等待時 0 CPU、SIGTERM / SIGINT 結束並釋放 line）。沒有 `EDGE_GPIO_HW` 時全套 `OK (skipped=35)`。
- 紅燈紀錄：程式不存在時原始碼 6 failures、CLI 與實機兩組 error；寫好第一版後實機 3 個 failure，追出啟動假事件；補「沒人按不能有事件」先紅，加穩定期後轉綠。`SA_RESTART` 那條第一版比對到自己的註解（測試寫錯），改成只檢查 `sa_flags`。
- 時間戳：同一次執行中，毫秒的小數部分幾乎固定（0.10～0.18 ms，另一次 0.33 ms），也就是落在 1 ms 的格點上；5-b 修正後是隨機分布、修正前是 4 ms 格點。推測是 Tegra GPIO 的硬體 debounce 以 1 ms 為單位計數、debounce 結束才發中斷，所以時間戳約晚 20 ms（**推論，未查證**）。
- 規模：新增程式約 482 行（C++ 132、驗收腳本約 200、測試約 160），在上限內；實作前估約 430 行。

### 踩坑

- 原本以為請求 line 之後立刻讀到的就是腳位的真實電位；實測（每 2 ms 取樣）前約 20 ms 都是 0，之後才是 1，不管有沒有開 edge detection。開了 edge detection 時，這次上升會被報成一筆 released 事件（請求後約 20.1～21.0 ms）。line 剛被釋放不到約 0.3 s 再請求時不會發生，所以連續重跑時看不到、隔一下就看得到。原因沒有查到，只記事實。
- 同一個現象讓 `gpioget gpiochip0 43` 在放開時也讀到 0（隔 1 秒連跑 4 次都是 0）。Step 5-b 的章（5b.3）和 hardware-wiring.md 寫「放開時 `gpioget` 應該讀到 1」，那次讀到 1 是因為剛好緊接在別的請求之後；本步一併更正。
- 寫測試時把 `proc.communicate()` 放在斷言的訊息參數裡，訊息在斷言前就會先求值，而 `communicate()` 會等程式結束；程式正確地睡著等按鍵，測試就卡住，直到被 120 秒的指令時限打斷。訊息要在確定失敗之後才組。
- 開機預設 pad 是內部**下拉**（`pull=1`），和 5-b pinctrl 設的上拉相反；兩者都被外接 330 Ω 蓋過，所以這個差異在有外接上拉時看不出來。

