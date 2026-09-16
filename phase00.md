# Phase 0 — 環境準備

> Parent roadmap: `ROADMAP.md`

硬體：

- Jetson Orin Nano
- Waveshare UPS Power Module (C)
- INA219
- STM32F103C8T6
- STM32N657
- IMX219 MIPI CSI camera
- 0.96" I2C OLED
- 麵包板
- 杜邦線
- LED

Yocto build host：

```text
x86-64 PC / Laptop
├── Ubuntu Linux
├── 足夠的 SSD 空間
└── 用來執行 BitBake / 建立 Jetson image
```

> Jetson Orin Nano 主要當作 target machine。Yocto image 建議在 x86-64 Linux host 上建置，再 flash 到 Jetson。

暫時不需要：

- Logic Analyzer
- Oscilloscope
- 額外 development board

軟體工具：

```bash
gcc
g++
make
cmake
git
i2c-tools
v4l-utils
device-tree-compiler

# Yocto 階段會再加入
bitbake
kas
```

並準備對應 Jetson kernel headers。

---

<!-- STEP_PLAN_START -->
## Step 規劃

### Step 1 — 建立可重複的開發環境基線

**目標**

先把後面所有實驗共用的工具、硬體資訊與驗證方式固定下來。

**實作範圍**

- 建立 `scripts/check_host_env.sh`
- 檢查 `gcc`、`g++`、`cmake`、`git`
- 檢查 `i2c-tools`、`v4l-utils`、`device-tree-compiler`
- 記錄 Jetson 型號、JetPack / L4T、kernel version
- 建立硬體接線與 pin mapping 文件
- 建立 `docs/bringup.md`


<!-- STEP_DETAIL_START -->
### 這一步到底要做什麼

這一步不是寫功能，而是先把「這台 Jetson 現在到底是什麼狀態」固定下來。後面 kernel module、Device Tree、Yocto 都會依賴 kernel/L4T/board 資訊；如果這些沒有記錄，之後很容易發生「在另一台機器編譯成功、這台卻不能載入」的問題。

具體要完成：

1. 在 Jetson 上收集並輸出：
   - `uname -a`
   - `/etc/os-release`
   - `/etc/nv_tegra_release`（若存在）
   - `cat /proc/device-tree/model`
   - CPU architecture
   - kernel headers 是否存在
2. 檢查開發工具：
   - `gcc/g++`
   - `cmake`
   - `make`
   - `git`
   - `dtc`
   - `i2cdetect`
   - `v4l2-ctl`
3. 建立硬體接線表，不只寫「接 INA219」，而要寫：
   - Jetson header pin
   - Linux GPIO/I2C/SPI controller
   - signal name
   - voltage
   - 對端 pin
4. 建立 `scripts/check_host_env.sh`，執行一次即可看到 PASS/FAIL。

### 預期檔案

```text
scripts/check_host_env.sh
docs/bringup.md
docs/hardware-wiring.md
docs/jetson-version.txt
```

### 這一步不做

- 不寫 kernel driver
- 不修改 Device Tree
- 不安裝 Yocto
- 不碰 STM32 firmware
<!-- STEP_DETAIL_END -->

**驗收條件**

```text
clone repo
  ↓
run check_host_env.sh
  ↓
清楚知道缺什麼工具
  ↓
Jetson / kernel / board 資訊可被記錄
```

不要在這個 Step 寫 driver。
<!-- STEP_PLAN_END -->
