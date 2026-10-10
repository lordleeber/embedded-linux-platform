# Phase 10 — Jetson Orin Nano + Yocto + meta-tegra 實戰線

> Parent roadmap: `ROADMAP.md`

## 目的

前面的 Phase 1～9 是在現成 Jetson Linux / Ubuntu 環境中理解：

```text
Kernel
Driver
Device Tree
systemd
Userspace
C++ application
```

這一階段開始把它們全部收回到：

```text
Yocto / OpenEmbedded
        ↓
meta-tegra
        ↓
meta-edge
        ↓
自訂 Jetson Linux image
```

目標不是「會下 BitBake 指令」，而是做到：

> 換一顆全新的 SSD / SD card，也能從 source + metadata 重新產生相同的 Jetson 系統。

`platform-app` 是這個 repo 自己建立的 userspace 驗證程式，不是從其他專案整合進來。

---

## 架構

```text
x86-64 Linux Build Host
        │
        ▼
Yocto / OpenEmbedded
        │
        ├── BitBake
        ├── OE-Core
        ├── meta-openembedded
        ├── meta-tegra
        │      │
        │      └── NVIDIA Jetson BSP / kernel / firmware / drivers
        │
        └── meta-edge
               ├── kernel modules
               ├── Device Tree
               ├── platform-app
               ├── systemd services
               └── edge-image
        │
        ▼
Jetson image
        │
        ▼
Flash
        │
        ▼
Jetson Orin Nano
```

這裡最重要的觀念：

```text
Yocto 不取代 NVIDIA driver
```

而是：

```text
Yocto
  +
meta-tegra
  +
NVIDIA Jetson BSP
```

由 `meta-tegra` 把 NVIDIA Jetson 平台需要的 BSP、kernel、firmware、driver 與 Yocto build system 接起來。

---

## Step 1 — 先成功 build 官方 / reference image

先不要建立自己的 distro。

先使用 OE4T 的 reference setup，目標 machine 依你的開機裝置選擇，例如 NVMe：

```text
jetson-orin-nano-devkit-nvme
```

先完成：

```text
clone Yocto / OE4T reference build
        ↓
設定 MACHINE
        ↓
BitBake image
        ↓
產生 flash artifact
        ↓
Jetson recovery mode
        ↓
flash
        ↓
boot
```

第一個 image 以 minimal / base image 為主，不要一開始加入：

```text
Desktop
CUDA
TensorRT
YOLO
GStreamer plugins 全家桶
大量 Python packages
```

先確認最基本系統。

### 完成標準

Jetson 可以：

```text
Power On
   ↓
Bootloader / UEFI
   ↓
Linux Kernel
   ↓
rootfs
   ↓
systemd
   ↓
Ethernet
   ↓
SSH
```

---

## Step 2 — 理解 BitBake / Recipe / Layer

至少要真正理解：

```text
.bb
.bbappend
.conf
.inc
class
layer
recipe
package
image
```

以及：

```text
source
  ↓
do_fetch
  ↓
do_unpack
  ↓
do_patch
  ↓
do_configure
  ↓
do_compile
  ↓
do_install
  ↓
package
  ↓
rootfs
  ↓
image
```

不要只記：

```bash
bitbake xxx
```

而是要知道：

> 你的 source code 是在哪一個 task 被抓下來、編譯、安裝，最後為什麼會出現在 rootfs 裡。

---

## Step 3 — 建立自己的 meta-edge layer

建立：

```text
meta-edge/
├── conf/
│   └── layer.conf
│
├── recipes-kernel/
│   ├── edge-ina219/
│   └── edge-ctrl/
│
├── recipes-bsp/
│   └── device-tree/
│
├── recipes-apps/
│   └── platform-app/
│
├── recipes-core/
│   └── systemd/
│
└── recipes-images/
    └── edge-image.bb
```

從這一步開始：

```text
不要手動 scp binary
不要手動複製 .ko
不要手動修改 /etc
不要靠 apt install 才能還原系統
```

所有東西都應該逐步搬進 recipe / layer。

---

## Step 4 — 把自己的 Linux driver 放進 Yocto

把前面寫過的：

```text
edge_test.ko
edge_ina219.ko
edge_ctrl.ko
```

加入：

```text
meta-edge
```

讓 BitBake：

```text
source
   ↓
cross compile kernel module
   ↓
package
   ↓
放進 rootfs
   ↓
開機載入
```

同時處理：

```text
modules-load.d
udev rules
sysfs permission
firmware
```

### 完成標準

重新 flash 一台乾淨 Jetson 後：

```bash
lsmod
```

就可以看到自己的 module。

不需要再：

```bash
scp xxx.ko jetson:/...
insmod xxx.ko
```

---

## Step 5 — 把 Device Tree 納入 build

把前面 GPIO / INA219 / STM32 用到的 Device Tree 設定納入 BSP / Yocto build。

例如：

```text
INA219
STM32 I2C slave
GPIO interrupt
OLED
SPI
```

最終做到：

```text
Device Tree source
       ↓
BitBake
       ↓
DTB / DT overlay
       ↓
flash image
       ↓
boot
       ↓
driver probe()
```

### 完成標準

新的 Jetson 完全不用人工修改 Device Tree，就能看到：

```text
probe()
   ↓
device ready
```

---

## Step 6 — 把本 repo 的 platform-app 變成 Yocto package

為：

```text
platform-app
```

建立 recipe。

BitBake 必須可以：

```text
fetch source
    ↓
cmake configure
    ↓
cross compile
    ↓
install binary
    ↓
package
    ↓
加入 image
```

例如最終 rootfs：

```text
/usr/bin/edge-edge
/etc/edge/
/lib/systemd/system/platform-app.service
```

systemd：

```text
boot
 ↓
systemd
 ↓
platform-app.service
 ↓
platform-app
```

### 完成標準

Jetson 開機後不用 SSH 進去手動啟動：

```text
Power On
   ↓
Linux boot
   ↓
platform-app automatically starts
```

---

## Step 7 — 再加入 NVIDIA GPU / Multimedia 元件

前面的 minimal image 穩定後，再逐步加入真正需要的 NVIDIA components。

例如：

```text
CUDA
TensorRT
V4L2
NVENC / NVDEC
GStreamer
camera stack
```

原則是：

```text
需要什麼才加什麼
```

而不是把完整 Desktop / JetPack userspace 全部塞進 image。

這一步也要開始理解：

```text
meta-tegra
     ↓
NVIDIA BSP recipes
     ↓
kernel / out-of-tree modules
     ↓
firmware
     ↓
userspace libraries
```

---

## Step 8 — 做 reproducibility test

這一步非常重要。

不要只測：

```text
我的 Jetson 現在能跑
```

要測：

```text
刪除舊 build output
        ↓
重新 build
        ↓
拿一個乾淨 target storage
        ↓
重新 flash
        ↓
boot
        ↓
driver 自動載入
        ↓
Device Tree 正確
        ↓
network 正常
        ↓
platform-app 自動啟動
```

如果這條線完整成立，才代表你真的建立了：

```text
Custom Linux Distribution
```

而不是只建立了一台「被手動設定過的 Jetson」。

---

## Phase 10 完成標準

最終至少要做到：

```text
git clone project
      ↓
準備 Yocto build environment
      ↓
bitbake edge-image
      ↓
產生 Jetson flash image
      ↓
flash Jetson Orin Nano
      ↓
boot
      ↓
NVIDIA BSP / driver 正常
      ↓
自製 kernel driver 正常
      ↓
Device Tree 正常
      ↓
platform-app 自動啟動
```

到這裡，你前面學的：

```text
Linux Kernel
Device Driver
Device Tree
systemd
C++
Jetson BSP
```

才真正被整合成一個完整 Embedded Linux product workflow。

---

<!-- STEP_PLAN_START -->
## Step 規劃

### Step 23 — Yocto / OE4T reference image bring-up

**目標**

第一次在 x86-64 host 為 Jetson Orin Nano build 並 flash 可開機 image。

**實作範圍**

- 固定 Yocto / OE4T revision
- 設定 Jetson Orin Nano MACHINE
- build base/minimal image
- flash procedure
- serial / SSH bring-up notes


<!-- STEP_DETAIL_START -->
### 這一步到底要做什麼

第一次不用 NVIDIA 預裝 Ubuntu rootfs，而是在 x86-64 Linux build host 透過 OE4T/meta-tegra 產生可供 Jetson Orin Nano 開機的 image。

要固定：

```text
Yocto release/branch
meta-tegra revision
MACHINE
build host OS
```

不要永遠跟 `master`。

流程要實際走過：

```text
clone manifests/repositories
  ↓
initialize build environment
  ↓
set MACHINE
  ↓
bitbake base image
  ↓
取得 deploy artifacts
  ↓
Jetson recovery mode
  ↓
flash target storage
  ↓
boot
```

### 驗證

新 image 至少有：

```text
serial console
systemd
Ethernet
SSH
```

並保存完整 build/flash command 到文件。

### 這一步不做

- 不加 CUDA
- 不加自製 driver
- 不加 platform-app
<!-- STEP_DETAIL_END -->

**驗收條件**

乾淨 target storage 可以：

```text
boot
systemd
network
SSH
```

### Step 24 — BitBake task / recipe lab

**目標**

不要只會執行 `bitbake`，要看懂 recipe lifecycle。

**實作範圍**

- 建立最小 `hello-edge.bb`
- `do_fetch`
- `do_compile`
- `do_install`
- package
- rootfs inclusion
- task inspection commands 筆記


<!-- STEP_DETAIL_START -->
### 這一步到底要做什麼

建立一個最小 recipe，親手理解 BitBake task pipeline。

例如：

```text
recipes-apps/hello-edge/hello-edge_1.0.bb
```

source 可以只有：

```c
int main() { puts("hello edge"); }
```

但要讓 BitBake 真正走：

```text
do_fetch
do_unpack
do_patch
do_configure
do_compile
do_install
do_package
rootfs
```

要學會查：

```text
bitbake -e
bitbake -c clean
bitbake -c compile
bitbake -c devshell
bitbake-layers show-recipes
```

### 驗證

flash 後 target 上直接存在：

```bash
/usr/bin/hello-edge
```

不是手動 `scp` 過去的。
<!-- STEP_DETAIL_END -->

**驗收條件**

自己的 binary 由 BitBake 編譯並出現在 target rootfs。

### Step 25 — 建立 meta-edge layer

**目標**

建立後續所有客製內容的正式 layer。

**實作範圍**

```text
meta-edge/
├── conf/
├── recipes-kernel/
├── recipes-bsp/
├── recipes-apps/
└── recipes-images/
```

- layer priority
- dependencies
- `edge-image.bb`


<!-- STEP_DETAIL_START -->
### 這一步到底要做什麼

建立自己的 Yocto layer，從此專案客製內容不直接散落修改 `meta-tegra`。

結構至少：

```text
meta-edge/
├── conf/layer.conf
├── recipes-apps/
├── recipes-kernel/
├── recipes-bsp/
└── recipes-images/
```

建立：

```text
edge-image.bb
```

它先只在 reference image 上加入 `hello-edge`。

要理解：

```text
BBFILE_COLLECTIONS
BBFILE_PATTERN
LAYERDEPENDS
LAYERSERIES_COMPAT
```

### 驗證

```bash
bitbake-layers show-layers
```

看得到 `meta-edge`，移除這個 layer 後 `edge-image` 應無法被找到。

### 這一步不做

- 不修改 upstream layer 來偷塞自己的 recipe
<!-- STEP_DETAIL_END -->

**驗收條件**

`bitbake-layers show-layers` 可看到 `meta-edge`，且 `edge-image` 能 build。

### Step 26 — Kernel modules recipe

**目標**

把前面手動編譯 / scp 的 `.ko` 納入 Yocto。

**實作範圍**

- `edge_ina219`
- `edge_ctrl`
- module recipe
- modules-load.d
- package dependencies
- udev rule：`/dev/edge_button` 改成 `root:gpio 0440`（比照 `/dev/gpiochip0` 的 `root:gpio 0660`）。Step 5-b 的 driver 只能設 mode，用 0444 加獨占 open，任何使用者都能開著不放、讓真正的 reader 拿到 `EBUSY`（PR #7 code review 指出，延後到這裡隨 udev rule 一起處理）


<!-- STEP_DETAIL_START -->
### 這一步到底要做什麼

把前面手動用 Jetson kernel headers 編譯的 `.ko` 變成 Yocto recipe 的產物。

至少 package：

```text
edge_ina219.ko
edge_ctrl.ko
```

要處理：

```text
kernel source/version matching
module compile flags
do_install
kernel-module package
modules-load.d
```

重點是避免：

```text
在 target 上 make
scp .ko
insmod
```

### 驗證

fresh image boot 後：

```bash
modinfo edge_ina219
lsmod
dmesg
```

確認 module 是 image build 出來的，而且版本與 kernel 相容。

### 這一步不做

- 不把 Device Tree 人工 copy 到 `/boot`
- DT 留 Step 27
<!-- STEP_DETAIL_END -->

**驗收條件**

重新 flash 後 driver 已存在，且可以自動載入。

### Step 27 — Device Tree integration

**目標**

把硬體描述正式納入 BSP build。

**實作範圍**

- INA219
- STM32 I2C/SPI
- GPIO/IRQ
- DT / overlay recipe or append
- boot selection


<!-- STEP_DETAIL_START -->
### 這一步到底要做什麼

把 GPIO/I2C/SPI 硬體描述納入 Yocto/BSP build，使 fresh flash 後 driver 就能 probe。

至少包含：

```text
INA219 @ I2C
STM32 @ I2C/SPI
GPIO/IRQ
OLED（若保留）
```

要明確知道你採用的是：

```text
full DT modification
或
DT overlay
```

以及 bootloader 如何選到它。

### 驗證

刻意用全新 target storage：

```text
flash
  ↓
boot
  ↓
dmesg
  ↓
edge_ina219 probe
edge_ctrl probe
```

中間不得 SSH 進去手改 `/boot` 或 copy `.dtbo`。

### 這一步不做

- 不加入 application service
<!-- STEP_DETAIL_END -->

**驗收條件**

乾淨 flash 後不需人工改 DT，driver 可以自動 `probe()`。

### Step 28 — platform-app recipe + systemd

**目標**

把 application 做成 image 的正式 package。

**實作範圍**

- CMake recipe
- runtime dependencies
- config install
- `platform-app.service`
- enable-on-boot


<!-- STEP_DETAIL_START -->
### 這一步到底要做什麼

把 C++ application 從「在 target 上自己 cmake build」改成 Yocto cross-build package。

recipe 要處理：

```text
source revision
CMake configure
compile
install
runtime dependencies
config files
systemd unit
```

systemd unit 要定義：

```text
After/Wants
Restart policy
WorkingDirectory（若需要）
Environment/config
ExecStart
```

不要把 service 寫成：

```text
sleep 30 && /usr/bin/platform-app
```

來掩蓋 dependency 問題。

### 驗證

fresh boot：

```bash
systemctl status platform-app.service
journalctl -u platform-app.service
```

application 自動啟動。

### 這一步不做

- 不加入 CUDA/TensorRT
<!-- STEP_DETAIL_END -->

**驗收條件**

```text
Power On
 ↓
systemd
 ↓
platform-app.service
 ↓
platform-app
```

不需 SSH 手動啟動。

### Step 29-a — NVIDIA compute runtime

**目標**

只加入 AI compute 所需的 NVIDIA runtime。

**規模目標**

```text
預估新增 code/config：200–500 lines
```

**實作範圍**

- CUDA runtime
- TensorRT runtime
- image dependencies
- minimal CUDA functional test
- minimal TensorRT functional test


<!-- STEP_DETAIL_START -->
### 這一步到底要做什麼

先只驗證 NVIDIA compute stack，不和 camera/multimedia 混在一起。

加入 image 的最低需求：

```text
CUDA runtime
必要的 CUDA libraries/tools
TensorRT runtime
```

建立兩個 smoke test：

```text
CUDA：配置 device buffer + 執行極小 kernel
TensorRT：載入/建立極小 engine + 跑一次 inference
```

成功標準不是：

```text
libcudart.so 存在
```

而是 GPU 真的執行。

### 驗證

記錄：

```text
GPU detected
CUDA API return code
TensorRT version
inference result
```

### 這一步不做

- 不碰 GStreamer
- 不碰 camera
<!-- STEP_DETAIL_END -->

**驗收條件**

不是只確認 package 存在，而是 CUDA 與 TensorRT 都有可執行的 smoke test。

### Step 29-b — NVIDIA multimedia runtime

**目標**

加入 video path 需要的 userspace 元件，但先不碰 CSI camera bring-up。

**規模目標**

```text
預估新增 code/config：200–500 lines
```

**實作範圍**

- V4L2 userspace tools
- GStreamer core/plugins
- NVENC / NVDEC runtime
- encode/decode smoke tests


<!-- STEP_DETAIL_START -->
### 這一步到底要做什麼

建立沒有 camera 也能測的 multimedia runtime。

先用：

```text
videotestsrc
或
預先準備的 H264/H265 sample file
```

驗證：

```text
decode
convert
encode
```

目標是分清楚：

```text
GStreamer pipeline 問題
vs
CSI camera 問題
```

要確認 NVENC/NVDEC 相關 plugin/runtime 真的能跑，而不是只有 software fallback。

### 驗證

至少一條：

```text
file → hardware decode → sink
```

以及：

```text
test source → hardware encode → file
```

### 這一步不做

- 不接 IMX219
<!-- STEP_DETAIL_END -->

**驗收條件**

可以用檔案或 test source 驗證 hardware encode/decode pipeline。

### Step 29-c — Jetson camera stack packaging

**目標**

只把後續 IMX219 phase 所需 camera stack 納入 image。

**規模目標**

```text
預估新增 code/config：150–400 lines
```

**實作範圍**

- camera-related BSP/userspace dependencies
- required firmware/runtime
- image feature/dependency cleanup
- package presence + runtime probe test


<!-- STEP_DETAIL_START -->
### 這一步到底要做什麼

把 Phase 11 會用到的 Jetson camera runtime/firmware/package 先放入 Yocto image，但此時不要求 IMX219 成功 streaming。

目的只是確保後面 camera bring-up 不需要：

```text
apt install
scp library
手動 copy firmware
```

要列出 camera stack 所需 package 與來源 layer，避免用一個巨大 packagegroup 把整個 desktop 都拉進來。

### 驗證

fresh image 上確認必要 binary/library/firmware 存在，並能執行基本 camera/media probing command。

### 這一步不做

- 不修改 IMX219 driver
- 不要求 `/dev/videoX`
<!-- STEP_DETAIL_END -->

**驗收條件**

Phase 11 開始前，camera stack dependencies 已由 Yocto image 提供，不需要 target 上手動安裝。

### Step 30 — Reproducible custom image

**目標**

證明這不是一台手工設定的 Jetson，而是一個可重建的 distribution。

**實作範圍**

- clean build procedure
- pinned revisions
- documented build config
- fresh target flash
- boot smoke test
- driver/app auto-start verification


<!-- STEP_DETAIL_START -->
### 這一步到底要做什麼

證明整套系統可以「從 source 重建」，而不是只在目前這台 Jetson 上碰巧可以跑。

建立一份 clean-room procedure：

```text
新的 build directory
  ↓
固定 source revisions
  ↓
bitbake edge-image
  ↓
flash 空白 target storage
  ↓
boot
  ↓
driver probe
  ↓
network
  ↓
platform-app.service
```

要保存：

```text
manifest/revision
MACHINE
DISTRO
image name
local.conf 必要設定
bblayers.conf 來源
build/flash command
```

### 驗證

至少做一次「刪除 tmp/work 或新 build dir」重建，避免只吃到舊 cache 的偶然成功。

### 這一步不做

- 不要求 bit-for-bit reproducible build
- 先要求 functional reproducibility
<!-- STEP_DETAIL_END -->

**驗收條件**

從乾淨 build environment 可以重新產生：

```text
edge-image
  ↓
flash
  ↓
boot
  ↓
drivers probe
  ↓
network
  ↓
platform-app starts
```
<!-- STEP_PLAN_END -->
