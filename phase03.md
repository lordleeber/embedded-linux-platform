# Phase 3 — INA219 I2C Driver

> Parent roadmap: `ROADMAP.md`

## 目的

開始寫真正的 device-specific Linux driver。

硬體直接使用：

```text
Waveshare UPS Power Module (C)
        │
       INA219
        │
       I2C
        │
Jetson Orin Nano
```

## 第一步

先從 userspace 理解硬體：

```bash
i2cdetect -l
i2cdetect -y X
i2cget
i2cset
```

先確認：

```text
INA219 address
register map
bus voltage
shunt voltage
current
power
```

## 第二步

自己寫：

```text
edge_ina219.c
```

不要一開始看 Linux upstream driver。

實作：

```c
struct i2c_driver

probe()
remove()

i2c_smbus_read_word_data()
i2c_smbus_write_word_data()
```

Device Tree：

```dts
ina219@40 {
    compatible = "edge,ina219";
    reg = <0x40>;
};
```

## 第三步

加入：

```text
Linux hwmon
```

讓 userspace 可以從：

```text
/sys/class/hwmon/hwmonX/
```

讀取：

```text
voltage
current
power
```

## 完成標準

不用 Python sample，也可以：

```bash
cat /sys/class/hwmon/hwmonX/in1_input
cat /sys/class/hwmon/hwmonX/curr1_input
cat /sys/class/hwmon/hwmonX/power1_input
```

取得真實 UPS 資料。

---

<!-- STEP_PLAN_START -->
## Step 規劃

### Step 6-a — 讀懂廠商範例 `ina219.py`（Waveshare UPS Power Module (C)）

**目標**

自己動手讀 register 之前，先把廠商附的 Python 範例逐行讀懂：它對 INA219 寫了什麼、讀了什麼、怎麼換算成電壓 / 電流 / 功率 / 電量百分比。這份範例是之後 Step 6-b（自己的 raw 工具）和 Step 7（kernel driver）的對照組。

**實作範圍**

- 把 `~/UPS_Power_Module_C/ina219.py` 原樣複製進 `third_party/waveshare_ups_c/`（SHA-256 釘住、不修改）
- 用假的 `smbus` 模組重播它的 register 讀寫，把章裡的每個說法寫成測試；實機測試讀真的 INA219
- 驗收腳本：bus 掃描、實機測試、範例輸出、拔掉 UPS 的 DC adapter 看電流

<!-- STEP_DETAIL_START -->
### 這一步到底要做什麼

拆分紀錄：原 Step 6（手動 `i2cget` / `i2cset`、C++ raw 工具）移到 6-b。使用者指出廠商範例 `python3 ina219.py` 已經能直接讀到數值，先把它讀懂，6-b 再拿掉 Python library 自己做。

誰和誰互動：

```text
ina219.py ── python3-smbus ── /dev/i2c-7（i2c-dev）── i2c-tegra（c250000.i2c）
                                                          │ SCL / SDA = header pin 5 / 3
                                                          ▼
                                    UPS Power Module (C) 上的 INA219（7-bit 位址 0x41）
```

- controller：Jetson 的 `c250000.i2c`（Linux `i2c-7`）；target：INA219，位址 0x41（類別預設 0x40，`__main__` 傳 0x41）
- 資料流：啟動時寫 Calibration（0x05 = 26868）再寫 Config（0x00 = 0x0EEF），之後每 2 秒讀 Bus Voltage / Current / Power（Shunt Voltage 也讀，但輸出那行被註解掉），每個 register 是 MSB 先送的 16-bit
- 用到的 API：`smbus.SMBus.read_i2c_block_data` / `write_i2c_block_data`（底層是 i2c-dev 的 `I2C_SMBUS` ioctl，I2C block 傳輸）

### 實作決策（Step 6-a 落地時裁決）

- 範例原樣入庫（`third_party/waveshare_ups_c/ina219.py`），教材的程式碼節錄要能被 `check_listings.py` 核對，不能只指向板上的家目錄
- 範例的註解和程式不一致（註解寫 Cal 13434、Current LSB 100 µA、Power LSB 2 mW；程式是 26868、0.1524 mA、3.048 mW），以程式為準，測試把兩者都釘住
- 實機上 `i2cdetect -y 7` 看不到 0x41：Tegra 的 i2c 不支援 SMBus Quick Write，0x30–0x37、0x50–0x5f 以外的位址都被跳過；要用 `-r`
- 不需要 root：使用者在 `i2c` 群組

### 預期檔案

```text
third_party/waveshare_ups_c/ina219.py
third_party/waveshare_ups_c/README.md
tests/test_ina219_sample.py
scripts/verify_ina219_sample.sh
```

### 這一步不做

- 不改範例、不寫自己的工具（Step 6-b）
- 不手動 `i2cget` / `i2cset`（Step 6-b）
- 不寫 kernel driver、不用 hwmon（Step 7、8）
<!-- STEP_DETAIL_END -->

**驗收條件**

`python3 ina219.py` 讀到合理的電池電壓；章裡對每個 register 值、換算公式的說法都有測試核對；拔掉 DC adapter 時電流不再是 0。

### Step 6-b — INA219 userspace bring-up

**目標**

在寫 driver 前先證明硬體、bus、address、register map 都正確。

**實作範圍**

- `i2cdetect`
- `i2cget` / `i2cset`
- register map 筆記
- endian conversion 驗證
- voltage/current raw value 小工具


<!-- STEP_DETAIL_START -->
### 這一步到底要做什麼

在寫 INA219 kernel driver 前，先證明「線有接對、I2C bus 找得到裝置、register 讀出來是合理的」。

先找 Jetson 上是哪一條 I2C bus：

```bash
i2cdetect -l
```

再掃描：

```bash
i2cdetect -y <bus>
```

INA219 常見 7-bit address 是 `0x40`，但要以你的模組 A0/A1 接法為準。

至少手動讀：

```text
Configuration register
Shunt Voltage
Bus Voltage
Current
Power
Calibration
```

要理解 INA219 register 是 big-endian 16-bit value，不能直接假設 host byte order。

### 實作決策（Step 6-b 落地時裁決）

- 誰和誰互動：`ina219_raw` ── `ioctl(I2C_RDWR)` ── `/dev/i2c-7`（i2c-dev）── i2c-tegra（`c250000.i2c`，controller）── INA219（target，0x41）。每個 register 一次 transaction：寫 1 byte pointer、repeated start、讀 2 byte
- 不用 `I2C_SMBUS` / libi2c 的 read word：SMBus word 是低位 byte 先送，`i2cget ... w` 讀到的 Config 是 `0xef0e`；工具自己用 `be16()` 組值，驗收腳本把 `i2cget` 的值對調後和工具比對
- 工具**只讀不寫**（唯一寫出的 byte 是 pointer）；Calibration 是 0 時印 `n/a`。`i2cset` 的練習只把剛讀到的 Calibration 原值寫回去，不改設定
- 換算放在 `tools/ina219_decode.h`，只用整數（mV / µV / µA / µW），Step 7 搬進 kernel 時同一套算式；電流同時印「V_shunt / R」與「Current register × Current_LSB」兩條路徑
- R_shunt 取 0.01 Ω（廠商範例註解的假設，未量測）
- bus 由 `i2cdetect -l` 的 controller 名稱 `c250000.i2c` 找，不寫死 `7`
- 「拔掉 INA219 回報 I/O error」以不存在的位址 0x45 模擬（`EREMOTEIO`）；實際拔線未測（UPS 同時在供電給 Jetson）

### 預期產物

建立小型 userspace tool：

```text
tools/ina219_raw.cpp
tools/ina219_decode.h
tests/test_ina219_decode.cpp
tests/test_ina219_raw.py
scripts/verify_ina219_raw.sh
docs/ina219-registers.md
```

可輸出：

```text
raw bus voltage
raw shunt voltage
converted voltage
converted current
```

### 驗證

- UPS 無負載/有負載時數值有合理變化
- register value 不應全是 `0xffff` 或 `0x0000`
- 拔掉 INA219 後程式要明確回報 I/O error

### 附帶（Step 6-a 發現，範圍外）

- ~~修 `docs/step05b.html` 頁首殘留的 Step 4-b `<nav>` 與章首~~（2026-10-11 已在 main 直接修掉，結案）
- 在板子旁邊補跑 `bash scripts/verify_ina219_sample.sh`（不加 `--no-unplug`），記錄拔掉 DC adapter 時的電流與正負號；6-b 的「有負載時數值變化」也靠這個情境

### 這一步不做

- 不寫 kernel driver
- 不用 hwmon
<!-- STEP_DETAIL_END -->

**驗收條件**

不用 Python library，可以從 userspace 讀到合理的 INA219 raw data。

### Step 7 — 自製 INA219 I2C kernel driver

**目標**

用自己的 `i2c_driver` 讀取 INA219。

**實作範圍**

- `struct i2c_driver`
- `probe()` / `remove()`
- SMBus register read/write
- Device Tree binding
- voltage/current/power conversion


<!-- STEP_DETAIL_START -->
### 這一步到底要做什麼

把 Step 6-b 的 userspace register 操作搬到 Linux I2C driver 裡。此時 Jetson 是 I2C controller，INA219 是 I2C target。

driver 要註冊：

```c
struct i2c_driver
```

並透過 Device Tree：

```dts
ina219@40 {
    compatible = "edge,ina219";
    reg = <0x40>;
};
```

觸發：

```text
I2C core
  ↓
match compatible/address
  ↓
probe(struct i2c_client *)
```

在 driver 中建立清楚的 helper：

```text
read_reg16()
write_reg16()
read_bus_voltage()
read_shunt_voltage()
```

要特別處理 INA219 register byte order。

### 預期檔案

```text
kernel/edge_ina219/
├── edge_ina219.c
├── Makefile
└── README.md
```

### 驗證

kernel driver 讀到的 raw value 要和 Step 6-b userspace tool 比較，同一時間量測不能差得離譜。

### 這一步不做

- 不註冊 hwmon
- 先把 device-specific driver logic 做對
<!-- STEP_DETAIL_END -->

**驗收條件**

driver probe 成功，而且能由 kernel path 讀到與 Step 6-b 接近的數值。

### Step 8 — INA219 hwmon integration

**目標**

停止發明 private userspace API，改接 Linux 標準 subsystem。

**實作範圍**

- hwmon registration
- voltage/current/power attributes
- units conversion
- error handling


<!-- STEP_DETAIL_START -->
### 這一步到底要做什麼

把自製 INA219 driver 接到 Linux 標準 `hwmon` subsystem，讓 userspace 不需要知道你 driver 私有 API。

目標 sysfs 類似：

```text
/sys/class/hwmon/hwmonX/
├── in1_input
├── curr1_input
└── power1_input
```

要使用 hwmon 規範的單位，例如 voltage/current/power 對應的 milli/micro unit，不要自行發明「11.9V」字串。

driver 內應把：

```text
INA219 raw register
    ↓
conversion
    ↓
hwmon callback
    ↓
sysfs attribute
```

串起來。

### 驗證

除了 `cat`，還要測：

- 重複讀 1000 次
- I2C error 時回傳 errno，而不是舊值假裝成功
- 裝置拔除/driver unload 不留下 stale node

### 這一步不做

- 不做 OLED
- 不做 application policy
<!-- STEP_DETAIL_END -->

**驗收條件**

```bash
cat /sys/class/hwmon/hwmonX/in1_input
cat /sys/class/hwmon/hwmonX/curr1_input
cat /sys/class/hwmon/hwmonX/power1_input
```

可以取得真實 UPS 數值。
<!-- STEP_PLAN_END -->
