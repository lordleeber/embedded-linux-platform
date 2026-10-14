# Phase 4 — OLED Driver

> Parent roadmap: `ROADMAP.md`

## 目的

從「讀 sensor」進一步練習「控制 peripheral」。

假設 OLED controller 是：

```text
SSD1306
```

或相似控制器。

硬體：

```text
Jetson
   │
  I2C
   │
 OLED
```

## 實作內容

自己處理：

```text
OLED initialization sequence
command mode
data mode
screen buffer
pixel drawing
character rendering
```

建立 driver：

```text
edge_oled.c
```

## 初期不必追求 framebuffer subsystem

可以先做簡單 API：

```text
/sys/.../text
```

或：

```text
/dev/edge_oled
```

userspace：

```bash
echo "EDGE" > /dev/edge_oled
```

## 完成標準

OLED 顯示：

```text
EDGE

BAT: 87%
V: 11.9V
I: 1.8A
P: 21W
```

資料來源使用上一階段 INA219。

---

<!-- STEP_PLAN_START -->
## Step 規劃

### Step 9 — OLED userspace protocol proof

**目標**

先證明 SSD1306 command/data sequence 與 I2C 通訊正確。

**實作範圍**

- initialization sequence
- clear screen
- draw pixel
- 顯示固定字串
- userspace prototype


<!-- STEP_DETAIL_START -->
### 這一步到底要做什麼

在寫 OLED kernel driver 前，先用 userspace 確認這片 OLED 到底是不是 SSD1306 相容、I2C address 是多少、初始化 sequence 是否正確。

userspace prototype 要能：

1. `i2cdetect` 找到 OLED
2. 送 display off/on command
3. 設定 addressing mode
4. clear display RAM
5. 畫單一 pixel / pattern
6. 顯示固定圖案或固定字串

要理解 SSD1306 I2C 傳輸中：

```text
control byte
command byte(s)
data byte(s)
```

不是單純把 ASCII `"HELLO"` 寫進 I2C 就會顯示。

### 實作決策（Step 9 落地時裁決）

- 誰和誰互動：`oled_probe` → `ioctl(I2C_RDWR)` → i2c-dev → i2c-tegra（`c240000.i2c` = `i2c-1`，controller）→ SSD1306（target，0x3C）。只寫不讀：SSD1306 在 I2C 模式下不能讀回 display RAM，畫面由人眼確認
- 接線：OLED（128x64 I2C 模組）VCC → pin 17（3.3 V）、GND → pin 20、SDA → pin 27、SCL → pin 28。pin 3/5（`i2c-7`）已經插著 UPS 的線，所以改用 pin 27/28；這條 bus 上還有板載的 fusb301（0x25）與 ina3221（0x40），位址不衝突
- 每個 I2C message = control byte（`0x00` command / `0x40` data）+ stream；一個 message 一個 `I2C_RDWR`，沒有 `I2C_SLAVE`（Step 10-a 的 driver 綁定 0x3C 之後工具仍可開 bus，不會 `EBUSY`）
- 協定 byte 全放在無 I/O 的 `tools/ssd1306.h`（init sequence、framing、GDDRAM 版面、只含 `D` `E` `G` 與空白的 5x7 glyph），由 `tests/test_ssd1306.cpp` 的 datasheet 向量檢查；完整字型是 Step 10-b
- 每次執行都送完整 init → window 指令 → 8 個 page → Display ON（`0xAF` 最後送，避免上電後的亂碼閃一下）
- 「不依賴前一次狀態」的驗法有兩個：用 `i2ctransfer`（獨立工具）把晶片打亂成反白 / 鏡像 / vertical addressing / contrast 0 再跑；以及整片 OLED 拔下再接上（插回後先確認螢幕全黑，證明真的經過上電 reset）
- 只拔 VCC 不算斷電（實測：螢幕變暗但 EDGE 還在、照樣 ACK），驗收改成四條線全拔

### 預期檔案

```text
tools/oled_probe.cpp
tools/ssd1306.h（協定 byte，無 I/O）
tests/test_ssd1306.cpp、tests/test_oled_probe.py
scripts/verify_oled_probe.sh
docs/ssd1306-notes.md
```

### 驗證

至少要做到 power-cycle 後程式仍可重新初始化 OLED，不依賴「前一次剛好留下的狀態」。
<!-- STEP_DETAIL_END -->

**驗收條件**

OLED 穩定顯示固定的 `EDGE`。

### Step 10-a — OLED kernel driver skeleton

**目標**

先把 OLED 從 userspace prototype 移到最小 kernel-facing device path，不處理完整文字排版。

**規模目標**

```text
預估新增 code：250–450 lines
```

**實作範圍**

- `edge_oled.c`
- I2C probe/remove
- OLED init / clear
- 最小 `/dev/edge_oled` 或 sysfs API
- 寫入 raw / fixed-size display buffer
- basic error handling


<!-- STEP_DETAIL_START -->
### 這一步到底要做什麼

把 Step 9 已驗證的 SSD1306 command/data sequence 移到 kernel I2C driver。這一步只建立 transport + device lifecycle，不急著做完整文字 rendering。

driver 要處理：

```text
probe()
  ↓
初始化 display
  ↓
配置 shadow/frame buffer
  ↓
提供最小 userspace entry
  ↓
remove()
```

最小 userspace entry 可以先支援：

```text
clear
fill
raw framebuffer write
```

### 實作重點

- I2C transfer error 要往上回報
- 不要在 probe 裡無限 retry
- buffer ownership 要明確
- remove 時取消 pending work
- display size 128x64/128x32 要固定成你實際硬體
- Step 9 的 `oled_probe` 用 `I2C_RDWR`、不用 `I2C_SLAVE`，所以 driver 綁定 0x3C 後它仍能寫入，會在 driver 底下重新 init、蓋掉 driver 的狀態（Step 9 code review，PR #13）。這一步要讓工具先看 `/sys/bus/i2c/devices/<bus>-003c/driver` 是否存在，有綁定就拒絕，除非加 `--force`

### 實作決策（Step 10-a 落地時裁決）

- 誰和誰互動：`edge_oled_ctl`（userspace）→ `/dev/edge_oled`（misc device）→ `edge_oled.ko`（I2C client driver）→ `i2c_master_send()` → i2c-tegra（`c240000.i2c` = `i2c-1`，controller，100 kHz）→ SSD1306（target，0x3C）。DT 節點 `oled@3c` 掛在 `&gen2_i2c`（同一份 overlay 的 `fragment@5`），compatible `edge,edge-ssd1306`（client 名 `edge-ssd1306`，`modules.alias` 沒有人認領）
- userspace 介面（`include/edge_oled.h`）：`write()` 只收剛好 1024 byte 的完整 frame（GDDRAM 版面，和 Step 9 的 `ssd1306::Frame` 相同），其他大小 `-EINVAL`、frame 不動；`read()` 讀回 driver 保存的 frame（晶片在 I2C 模式下不能讀）；ioctl `EDGE_OLED_IOC_CLEAR = _IO(0xEB, 0x10)`、`EDGE_OLED_IOC_FILL = _IOW(0xEB, 0x11, __u8)`。magic 和 edge_test 共用 0xEB，nr 不重複。裝置 mode 0666（開發板的螢幕，登入的人都能畫）
- 協定 byte 放在 plain C 的 `include/edge_oled_proto.h`，由 `tests/test_edge_oled_proto.cpp` 逐 byte 和 Step 9 的 `tools/ssd1306.h` 比對（同 Step 7 的換算 header 做法）
- buffer ownership：frame 屬於 driver；`write()` 先 `memdup_user()` 到暫存區再上鎖複製，壞指標或錯大小都不會留下半張 frame。所有傳輸都在 mutex 下同步完成，沒有 timer / work，所以 remove 時沒有 pending work 可取消
- 錯誤：傳輸失敗（沒 ACK = `-EREMOTEIO`）只試一次、errno 直接回給呼叫者；同時清掉 `initialized`，下一次寫入會先重送 init sequence（OLED 斷電後晶片回到 reset 狀態，只送 frame 會什麼都看不到）。probe 失敗直接 `dev_err_probe`，不 retry
- lifecycle：結構用 `kzalloc` + `kref`（不是 `devm_`），開著的檔案各持一個 reference；remove 先 `misc_deregister()`、送 Display OFF、把 `client` 設成 NULL，之後還開著的檔案 write / read / ioctl 都得到 `-ENODEV`
- 測試圖（pixel / pattern / edge）從 `oled_probe.cpp` 的 `draw()` 搬到 `ssd1306.h` 的 `test_picture()`，`oled_probe` 與 `edge_oled_ctl` 共用，畫面可和 Step 9 基線直接比對（只用 Step 9 那三個字的 glyph，不是 font table）
- `oled_probe` 先讀 `<sysfs>/bus/i2c/devices/<bus>-00<addr>/driver`，有綁定就結束碼 1 並提示 `--force`；測試用 `OLED_PROBE_SYSFS` 換掉 `/sys`
- 規模：新增約 1220 行非空白（driver 245、其餘產品碼約 270、測試與驗收腳本約 715），超過 800 行上限，也遠超這裡原估的 250–450 行；動工前沒有重新估算。使用者決定保留不拆，記錄在 `docs/baseline.md`

### 預期檔案

```text
kernel/edge_oled/edge_oled.c、Makefile
include/edge_oled.h（userspace 介面）、include/edge_oled_proto.h（協定 byte）
apps/edge_oled_ctl.cpp
dts/edge-gpio-overlay.dts（fragment@5）
tools/oled_probe.cpp（--force）、tools/ssd1306.h（test_picture）
tests/test_edge_oled_proto.cpp、tests/test_edge_oled_static.py、tests/test_edge_oled_device.py
scripts/verify_edge_oled.sh
```

### 這一步不做

- 不實作 font table
- 不顯示 battery telemetry
<!-- STEP_DETAIL_END -->

**驗收條件**

kernel driver 載入後，可以從 userspace 觸發 clear screen 與固定 pattern 顯示。

### Step 10-b — OLED text buffer + font rendering

**目標**

只處理文字 rendering，不同時加入 telemetry policy。

**規模目標**

```text
預估新增 code：300–550 lines
```

**實作範圍**

- text buffer
- minimal bitmap font
- character rendering
- line / column positioning
- clipping / invalid character handling


<!-- STEP_DETAIL_START -->
### 這一步到底要做什麼

這一步只做「字元如何轉成 OLED pixel」。把 rendering 和 I2C transport 分開，避免 driver 變成一個巨大混合物。

建立最小 bitmap font，例如：

```text
5x7 或 6x8 ASCII
```

需要定義：

```text
draw_pixel(x, y)
draw_char(x, y, c)
draw_string(x, y, text)
clear()
```

要處理：

- x/y 超出範圍
- 不支援字元
- newline
- 一行太長
- framebuffer → OLED page layout 的 mapping

### 驗證

使用固定測試字串：

```text
ABCDEFGHIJKLMNOPQRSTUVWXYZ
0123456789
EDGE
```

確認字元不左右顛倒、上下顛倒、跨 page 錯位。

### 從 Step 10-a 帶過來的

- `edge_oled` 只在傳輸**失敗**後重送 init。OLED 在兩次寫入之間斷電又接回（中間沒人寫）時，下一次寫入會 ACK、只送 frame，螢幕仍是黑的（依 reset 狀態推論，未實測）。Step 10-c 會週期刷新，等於長時間顯示，這裡要決定：每次 flush 都送 init（約 27 byte，100 kHz 下約 2.5 ms），或其他偵測方式；先寫重現步驟（寫入之間四條線全拔再接回）再改
- **結案（Step 10-b）**：先寫重現步驟進 `scripts/verify_edge_oled_text.sh`，舊 driver 實測重現（接回後寫入成功、螢幕全黑）；改成每次 flush 都送設定，再跑一次通過。

### 實作決策（Step 10-b 落地時裁決）

- 誰和誰互動：`edge_oled_ctl text` / `font`（userspace，`apps/oled_text.h` 把字畫進 frame）→ `write()` 1024 byte → `/dev/edge_oled` → `edge_oled.ko` → `i2c_master_send()` → i2c-tegra（`i2c-1`，controller）→ SSD1306（target，0x3C）。**字型與排版全在 userspace**，driver 仍然只收整張 frame（不加 text ioctl），`test_still_no_font_in_the_driver` 守著
- 字型：古典 5x7（每字 5 個 column byte，bit 0 在上，和 GDDRAM byte 同方向），涵蓋 `' '`..`'~'`（0x20–0x7E，95 字）；D / E / G 和 Step 9 的 `ssd1306::glyph()` 逐 byte 相同。字格 6x8，128x64 = 21 欄 x 8 行，`y = 8 * line` 時一行剛好落在一個 page
- API（`oled_text::`）：`clear()`、`draw_pixel()`、`draw_char()`、`draw_string()`（`'\n'` 回到起始 x、往下 8 px）、`draw_text_at(line, column)`；回傳 `Result{clipped, unsupported}`
- 一行太長：**截斷不換行**（之後 Step 10-c 的版面不會因為數字變長而整個往下移）；部分在面板上的字照像素裁切，計入 `clipped`。不支援的字元（控制字元、DEL、UTF-8 的 byte）畫成空心方框，保留字格位置，計入 `unsupported`。`edge_oled_ctl` 把兩個計數印到 stderr、結束碼仍是 0
- phase04 的 `ABCDEFGHIJKLMNOPQRSTUVWXYZ` 是 26 字、一行只放得下 21 字，字型表（`kFontSheet`）拆成 `A..M` / `N..Z` 兩行，另外加小寫與標點兩行，每個可印字元都出現一次
- Step 10-a 的帶過來項目：每次 flush 都送 init sequence（已經亮著時跳過開頭的 Display OFF，刷新才不會閃黑），frame 之後每次都送 Display ON。SSD1306 在 I2C 模式下讀不回狀態，沒有別的偵測方式。代價：每張 frame 多 2 個訊息、線上 29 byte（約 2.6 ms），實測 96.4 → 99.2 ms
- 規模：非空白新增約 813 行（產品碼 243：`oled_text.h` 183、`edge_oled_ctl` 29、driver 29、CMake 2；測試 436；驗收腳本 134），動工前估 650，略超 800 行上限

### 預期檔案（Step 10-b）

```text
apps/oled_text.h（5x7 font、draw_*）、apps/edge_oled_ctl.cpp（text / font）
kernel/edge_oled/edge_oled.c（每次 flush 都送設定）
tests/test_oled_text.cpp、tests/test_edge_oled_text.py
scripts/verify_edge_oled_text.sh
```

### 這一步不做

- 不讀 INA219
- 不做 periodic timer
<!-- STEP_DETAIL_END -->

**驗收條件**

可以顯示多行文字：

```text
EDGE
LINE 2
123456
```

### Step 10-c — INA219 telemetry display app

**目標**

把前一階段 hwmon 資料接到 OLED，但不再修改 OLED driver 核心。

**規模目標**

```text
預估新增 code：200–400 lines
```

**實作範圍**

- 讀取 hwmon voltage/current/power
- format telemetry
- periodic refresh
- stale/error display
- clean shutdown


<!-- STEP_DETAIL_START -->
### 這一步到底要做什麼

建立一個 userspace telemetry application，把 hwmon 資料格式化後送到 OLED。這一步刻意放在 userspace，避免把「電池顯示策略」塞進 kernel driver。

資料流：

```text
INA219
  ↓
edge_ina219 kernel driver
  ↓
hwmon sysfs
  ↓
telemetry_display app
  ↓
/dev/edge_oled
  ↓
OLED
```

建議畫面：

```text
V: 11.92 V
I:  1.84 A
P: 21.93 W
```

app 要處理：

- 固定 refresh interval，例如 500 ms 或 1 s
- sysfs read failure
- stale value
- OLED write failure
- SIGINT/SIGTERM clean shutdown

### 從 Step 10-b 帶過來的

- `edge_oled` 每次 flush 都在面板亮著時重送整份設定（含 `D5` 時脈、`A8` multiplex、`8D 14` charge pump），10-b 只人眼看了 5 次刷新沒閃（PR #15 code review）。這一步會長時間每秒刷新：驗收加一項「連續刷新幾分鐘，看有沒有閃爍或亮度掉」。真的看到時，再考慮刷新只送和 reset 值不同的設定（`20 00`、`A1`、`C8`、`81`、`D9`、`DB`、`8D`），要先查 datasheet 的 reset 值。不能只送 charge pump + Display ON：斷電又接回時晶片會回到 page addressing、`A0` / `C0`，畫面會鏡像、顛倒、排錯
- **結果（Step 10-c）**：每秒刷新，人眼看了 3 分鐘（第一輪，口頭回報）與 30 秒（第二輪，腳本記錄）都沒有閃爍或亮度掉，不改 driver。驗收腳本保留這一項（`--watch-seconds`，預設 30）

### 實作決策（Step 10-c 落地時裁決）

- 誰和誰互動：INA219（target，`i2c-7` 0x41）→ `edge_ina219`（Step 8，hwmon）→ `/sys/class/hwmon/hwmonN/{in1,curr1,power1}_input` → `build/telemetry_display`（userspace）→ `write()` 1024 byte → `/dev/edge_oled` → `edge_oled` → SSD1306（target，`i2c-1` 0x3C）。兩條 I2C 的 controller 都是 Tegra；app 只碰 sysfs 與 `/dev`，**兩個 driver 都沒改**
- 分層：`apps/telemetry.h` 只放「顯示什麼」（解析 sysfs 整數、四捨五入到 0.01、stale 規則、8 行版面），沒有 I/O 和時鐘，C++ 向量直接餵數字與時間；`apps/telemetry_display.cpp` 負責讀檔、寫 frame、等待與訊號。文字由 Step 10-b 的 `oled_text.h` 畫
- 畫面：`BAT: 98.00 %` / `V: 12.53 V` / `I:  0.96 A` / `P: 12.06 W` / 三行空白 / 狀態行（`OK #N`、`STALE I #N`、`NO SENSOR #N`，計數器讓人看得出畫面是活的）。使用者在驗收時要求加百分比：照廠商 `ina219.py` 的公式 `(V − 9) / 3.6 × 100`，夾在 0–100；只是顯示，沒有任何門檻或動作（不是 low-battery policy）。它只看電壓，充電時偏高（Step 6-a 實測）
- 錯誤處理：每個 channel 保留最後一筆好值；讀不到時照樣顯示，超過 `--stale-ms`（預設 3000）才變 `--.--`。錯誤原因寫 stderr，每次連續失敗只寫一次。hwmon 目錄用 `name` = `edge_ina219` 找，目錄消失（unbind / rmmod）就重找，因為重新綁定可能換號（Step 8）。OLED 寫入失敗：關掉 fd、下一秒重開重寫（driver unbind 後舊 fd 永遠 `ENODEV`，Step 10-a），也只報一次
- 時間與訊號：固定間隔（`--interval-ms`，預設 1000，用 CLOCK_MONOTONIC 的絕對時間排下一次；落後時從現在重新起算，不補刷）。SIGINT / SIGTERM / SIGHUP 先被 block，等待本身就是 `sigtimedwait()`：訊號隨時到都立刻結束等待，沒有 handler、沒有競爭。結束前寫一張空白 frame（面板上不留看起來像即時的舊數字）。SIGPIPE 忽略（stdout 被關掉也繼續顯示）。後三項是 PR #16 code review 後加的
- 結束碼：0 = 停止且最後一次 OLED 寫入成功；1 = 最後一次寫入失敗；2 = 用法錯。`--count N`（測試用）跑 N 次就停、保留最後一張畫面
- 規模：非空白新增 798 行（產品碼 278、測試 346、驗收腳本 174），動工前估 720；PR #16 code review 修正後 916 行（產品碼 306、測試 427、驗收腳本 183），**超過 800 行上限**，多出的 118 行有 75 行是 review 項目的測試

### 預期檔案（Step 10-c）

```text
apps/telemetry.h、apps/telemetry_display.cpp
tests/test_telemetry.cpp、tests/test_telemetry_display.py
scripts/verify_telemetry_display.sh
```

### 這一步不做

- 不做 low-battery policy
- 不做 network notification
<!-- STEP_DETAIL_END -->

**驗收條件**

OLED 可持續顯示：

```text
BAT / Voltage / Current / Power
```

<!-- STEP_PLAN_END -->
