# edge_ina219：自製 INA219 I2C client driver（Step 7）

UPS Power Module (C) 上的 INA219 在 header I2C（pin 3 / 5，`c250000.i2c` = `i2c-7`）位址 0x41。Jetson 是 controller，INA219 是 target。

```text
dts/edge-gpio-overlay.dts 的 ina219@41（target = &hdr40_i2c1）
  → 開機時 I2C core 建立 client 7-0041（還沒有 driver）
  → insmod edge_ina219.ko：compatible "edge,ina219" 相符 → edge_ina219_probe()
       讀 Config 確認有 ACK → 寫 Calibration 26868 → 寫 Config 0x0EEF
  → cat /sys/bus/i2c/devices/7-0041/bus_mv
       → bus_mv_show() → read_bus_voltage() → i2c_smbus_read_word_swapped()
       → i2c-tegra：寫 pointer 0x02、repeated start、讀 2 byte（MSB 先）
```

## Build / load / unload

```bash
make -C dts && sudo python3 scripts/install_edge_gpio_overlay.py install dts/edge-gpio-overlay.dtbo   # 重開機後才有節點
make -C kernel/edge_ina219
sudo insmod kernel/edge_ina219/edge_ina219.ko
cat /sys/bus/i2c/devices/7-0041/{registers,bus_mv,shunt_uv,current_ua,power_uw}
sudo rmmod edge_ina219
sudo bash scripts/verify_edge_ina219.sh            # 驗收
```

## 介面（Step 7 私有，Step 8 換成 hwmon）

| 屬性（0444） | 內容 |
|---|---|
| `registers` | 六個 register 的原始值，`0x0EEF 0x0000 0x5EBA 0x0000 0x0000 0x68F4` |
| `bus_mv` | Bus Voltage，mV（去掉 CNVR / OVF） |
| `shunt_uv` | Shunt Voltage，µV，有號 |
| `current_ua` | Current register × Current_LSB，µA，有號；Calibration 為 0 時 `ENODATA` |
| `power_uw` | Power register × 20 × Current_LSB，µW；Calibration 為 0 時 `ENODATA` |

每次讀檔都直接讀晶片，不快取。I2C 失敗時 `read()` 回傳 errno（例如 `EREMOTEIO`），不印舊值。換算在 `include/edge_ina219_conv.h`，和 Step 6-b 的 `tools/ina219_decode.h` 逐值比對過（`build/test_edge_ina219_conv`）。

## 注意

- driver 綁定後 0x41 屬於 kernel：`i2cdetect` 顯示 `UU`，`i2cget` 不加 `-f` 會得到 `Device or resource busy`（i2c-dev 的 `I2C_SLAVE` 會檢查）。`build/ina219_raw` 用 `I2C_RDWR`，不經這個檢查，仍可讀。
- 換算用 64-bit 除法 `/`，arm64 可以；要搬到 32-bit 平台得改成 `div_s64()`。
- shunt 0.01 Ω 沿用範例註解的假設，未量測。
