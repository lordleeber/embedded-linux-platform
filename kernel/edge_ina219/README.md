# edge_ina219：自製 INA219 I2C client driver（Step 7；Step 8 接上 hwmon）

UPS Power Module (C) 上的 INA219 在 header I2C（pin 3 / 5，`c250000.i2c` = `i2c-7`）位址 0x41。Jetson 是 controller，INA219 是 target。

```text
dts/edge-gpio-overlay.dts 的 ina219@41（target = &hdr40_i2c1）
  → 開機時 I2C core 建立 client 7-0041（還沒有 driver）
  → insmod edge_ina219.ko：compatible "edge,edge-ina219" 相符 → edge_ina219_probe()
       讀 Config 確認有 ACK → 寫 Calibration 26868 → 寫 Config 0x0EEF → 讀回比對（不符 -ENODEV）
       → devm_hwmon_device_register_with_info() 建立 hwmonN（7-0041/hwmon/hwmonN）
  → cat /sys/class/hwmon/hwmonN/in1_input
       → hwmon core → edge_ina219_read(hwmon_in, channel 1) → read_bus_voltage()
       → i2c_smbus_read_word_swapped() → i2c-tegra：寫 pointer 0x02、repeated start、讀 2 byte（MSB 先）
```

## Build / load / unload

```bash
make -C dts && sudo python3 scripts/install_edge_gpio_overlay.py install dts/edge-gpio-overlay.dtbo   # 重開機後才有節點
make -C kernel/edge_ina219
sudo insmod kernel/edge_ina219/edge_ina219.ko
hw=$(echo /sys/bus/i2c/devices/7-0041/hwmon/hwmon*)
cat $hw/name $hw/{in0,in1,curr1,power1}_input
sudo rmmod edge_ina219
sudo bash scripts/verify_edge_ina219.sh            # 驗收
```

## 介面（hwmon，Step 8）

`name` 是 `edge_ina219`；hwmonN 的編號看開機順序（這台實測 `hwmon4`），用 `name` 找，不要寫死。

| 檔案（0444） | 內容（hwmon 單位，`Documentation/hwmon/sysfs-interface.rst`） |
|---|---|
| `in0_input` / `in0_label` | Shunt Voltage，mV，有號，四捨五入（register 是 10 µV 一格）；label `shunt` |
| `in1_input` / `in1_label` | Bus Voltage，mV（去掉 CNVR / OVF）；label `bus` |
| `curr1_input` | Current register × Current_LSB，mA，有號，四捨五入；Calibration 為 0 時 `ENODATA` |
| `power1_input` | Power register × 20 × Current_LSB，µW；Calibration 為 0 時 `ENODATA` |

in0 = shunt、in1 = bus 和上游 `ina2xx` 相同。每次讀檔都直接讀晶片，不快取；I2C 失敗時 `read()` 回傳 errno（例如 `EREMOTEIO`），不印舊值。unbind / rmmod 時 hwmonN 一起消失（devm），之前開著的 fd 再讀得到 `ENODEV`。換算在 `include/edge_ina219_conv.h`，和 Step 6-b 的 `tools/ina219_decode.h` 逐值比對過（`build/test_edge_ina219_conv`）。

Step 7 的私有屬性（`registers`、`bus_mv`、`shunt_uv`、`current_ua`、`power_uw`）在 Step 8 拿掉了；要看原始 register 用 `build/ina219_raw`。

## 注意

- compatible 是 `edge,edge-ina219`，不是 `edge,ina219`：I2C core 用 compatible 去掉廠商前綴當 client 名稱，DT 比不到時還會拿名稱比每個 driver 的 `i2c_device_id`；`ina219` 在上游 `ina2xx` 的表裡（`modinfo ina2xx` 有 `alias: i2c:ina219`）。
- driver 綁定後 0x41 屬於 kernel：`i2cdetect` 顯示 `UU`，`i2cget` 不加 `-f` 會得到 `Device or resource busy`（i2c-dev 的 `I2C_SLAVE` 會檢查）。`build/ina219_raw` 用 `I2C_RDWR`，不經這個檢查，仍可讀。
- 換算用 64-bit 除法 `/`，arm64 可以；要搬到 32-bit 平台得改成 `div_s64()`。
- shunt 0.01 Ω 沿用範例註解的假設，未量測。
