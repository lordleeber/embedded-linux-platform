# edge_ctrl：自製 STM32F103 peripheral 的 I2C client driver（Step 13）

Blue Pill（Step 11–12-b 的 firmware，register map v1.1）在 `c240000.i2c` = `i2c-1`（header pin 27 / 28，和 OLED 同一條 bus）位址 0x42。Jetson 是 controller，Blue Pill 是 target。這個 driver 把 register protocol 包起來，application 讀寫檔案就好，不用知道 `/dev/i2c-1`、pointer 與 byte 順序。

```text
dts/edge-gpio-overlay.dts 的 controller@42（fragment@6，target = &gen2_i2c）
  → 開機時 I2C core 建立 client 1-0042（還沒有 driver）
  → insmod edge_ctrl.ko：compatible "edge,edge-ctrl" 相符 → edge_ctrl_probe()
       一次讀 0x00–0x03：DEVICE_ID 要是 0xED、PROTOCOL_VERSION 要是 1.x 且 x ≥ 1，否則 -ENODEV
  → driver core 依 .dev_groups 在 /sys/bus/i2c/devices/1-0042/ 建立屬性檔
  → cat .../adc → adc_show() → read_reg(0x10, 2 byte)
       → i2c_transfer()：寫 pointer 0x10、repeated START、讀 2 byte（LOW、HIGH）→ "2068"
  → echo 1 > .../led → led_store() → 檢查 0 / 1 → write_reg(0x20, 1) → PC13 亮
```

## Build / load / unload

```bash
make -C dts && sudo python3 scripts/install_edge_gpio_overlay.py install dts/edge-gpio-overlay.dtbo   # 重開機後才有節點
make -C kernel/edge_ctrl
sudo insmod kernel/edge_ctrl/edge_ctrl.ko
cd /sys/bus/i2c/devices/1-0042 && grep . device_id firmware_version protocol_version adc button button_presses led status
echo 1 | sudo tee led
sudo rmmod edge_ctrl
sudo bash scripts/verify_edge_ctrl.sh [--no-look] [--no-unplug]   # 驗收
```

## 介面（sysfs 屬性，在 client 目錄 `/sys/bus/i2c/devices/1-0042/` 下）

| 檔案 | 權限 | 內容 | register |
|---|---|---|---|
| `device_id` | 0444 | `0xed` | 0x00 |
| `firmware_version` | 0444 | `0.3`（major.minor） | 0x01–0x02，一次讀 |
| `protocol_version` | 0444 | `1.1` | 0x03 |
| `adc` | 0444 | `0`–`4095`，十進位 | 0x10–0x11，一次讀 2 byte |
| `button` | 0444 | `1` = 按著、`0` = 放開 | 0x12 bit 0 |
| `button_presses` | 0444 | 開機以來按下次數，`0`–`255` 繞回 | 0x13 |
| `led` | 0644 | `0` / `1`；寫入只收 0 和 1，其他值 `EINVAL`，不送到 bus 上 | 0x20 |
| `status` | 0644 | `0x80` 這種兩位 hex；寫入照 write-1-to-clear 轉送（`echo 0x01` 清 RO_WRITE、`echo 0xff` 全清），超過 0xFF 是 `EINVAL` | 0x30 |

每次讀檔都直接讀板子，不快取、不輪詢；I2C 失敗時 `read()` / `write()` 回傳 errno（Blue Pill 斷電時實測 `Remote I/O error`），driver 不記錄「壞掉」的狀態，板子回來後下一次存取就成功，不用 unbind / bind。sysfs 檔不能給 others 寫，所以 `led`、`status` 要 root。

## 為什麼是 sysfs，不是 character device

- phase05 的規劃要的是「read/write attributes」：每個值一個檔、文字格式，`cat` / `echo` 就能用，和 Step 7 的私有屬性同一種做法。
- 這些值都是「現在是多少」的狀態，沒有串流、沒有事件，不需要 `read()` 的位置、`ioctl` 或 blocking。
- 不是 hwmon：ADC 讀的是 Blue Pill A0 上的任意電壓（0–4095 的原始值），按鍵、LED、STATUS 也都不是 hwmon 的類別。
- Step 19 要 `poll()` 等 STM32 的事件，phase08 規劃的是 `/dev/edge_ctrl`（wait queue、event 語意），那時再加 character device；這一步不做 `poll()`、也不做 heartbeat（Step 14）。

## 注意

- compatible 是 `edge,edge-ctrl`（client 名稱 `edge-ctrl`），不是規劃寫的 `edge,controller`：I2C core 用 compatible 去掉廠商前綴當 client 名稱，再拿它比每個 driver 的 `i2c_device_id`（Step 7 的教訓），`controller` 這種通用字比較可能撞名。
- driver 綁定後 0x42 屬於 kernel：`i2cget` 不加 `-f` 會得到 `Device or resource busy`；`i2ctransfer -f` 照樣能讀寫（驗收腳本與 device 測試就是這樣比對）。用 raw 寫入改了 LED 或 STATUS，driver 下次讀就看得到，因為它不快取。
- `read_reg()` 的 pointer 寫入和讀取在同一個 `i2c_transfer()` 裡，adapter 鎖住整筆，同一條 bus 的 `edge_oled` 或 userspace 插不進來移動 firmware 的 pointer。
- register 位址與解碼在 `include/edge_ctrl_regs.h`；firmware 自己的一份在 `firmware/stm32f103/Core/Inc/i2c_target.h`。`build/test_edge_ctrl_regs` 用 driver 的 transaction 驅動 firmware 的 `i2c_target.c`，兩份不會悄悄分歧。
