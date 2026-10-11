# INA219 register map 筆記（UPS Power Module (C)，`i2c-7` 位址 0x41）

Step 6-b 實測。來源：TI INA219 datasheet（SBOS448）與 `build/ina219_raw`、`i2cget` 的讀值。之後 Step 7 的 kernel driver 以這份為對照。

## 傳輸

- 每個 register 16 bit，**MSB 先送**（big-endian）。讀 = 寫 1 byte 的 register pointer → repeated start → 讀 2 byte；寫 = pointer + MSB + LSB。
- `i2cget -y 7 0x41 <reg> w` 用的是 SMBus「read word」，SMBus 規定**低位 byte 先送**，所以印出的值是反的：Config `0x0EEF` 顯示成 `0xef0e`。`i2cset ... w` 同理，要寫 `0x68F4` 得給 `0xf468`。
- `tools/ina219_raw.cpp` 用 `I2C_RDWR` 一次送兩個 message，自己用 `be16()` 組值，不依賴 host byte order。

## Register

| 位址 | 名稱 | R/W | 實測值（2026-10-11） | 解讀 |
|---|---|---|---|---|
| 0x00 | Configuration | R/W | `0x0EEF` | BRNG=0（16 V）、PG=01（/2，±80 mV）、BADC=SADC=1101（12-bit、32 次平均，17.02 ms）、MODE=111（shunt + bus 連續）。上電預設 `0x399F`；這個值是廠商範例寫的 |
| 0x01 | Shunt Voltage | R | `0x0000` | 有號（二補數），10 µV/bit |
| 0x02 | Bus Voltage | R | `0x6092` | bit 15..3 × 4 mV = 3090 × 4 = 12.360 V；bit 1 CNVR（轉換完成，讀 Power 會清掉）、bit 0 OVF（溢位）、bit 2 不用 |
| 0x03 | Power | R | `0x0000` | 無號，Power_LSB = 20 × Current_LSB |
| 0x04 | Current | R | `0x0000` | 有號，Current_LSB = 0.04096 / (Cal × R_shunt) |
| 0x05 | Calibration | R/W | `0x68F4`（26868） | 上電預設 0：這時 Current / Power 恆為 0。值是廠商範例寫的 |

## 換算（R_shunt 取 0.01 Ω，廠商範例註解的假設，未量測）

- Current_LSB = 0.04096 / (26868 × 0.01) = 152.45 µA；Power_LSB = 3.049 mW。範例用的是四捨五入的 0.1524 mA / 3.048 mW。
- 不靠 Calibration 的電流：I = V_shunt / R = shunt_raw × 10 µV / 0.01 Ω = shunt_raw × 1 mA。
- 晶片內部算的是 Current = Shunt × Cal / 4096，所以**同一次轉換**的兩條路徑差在 1 個 Current_LSB 以內。INA219 讀一次只回 pointer 指到的那一個 register，`ina219_raw` 的六個值要分六次讀，可能跨兩次轉換（約 34 ms 一次）；負載變動時兩條路徑可能差更多（未實測）。
- Integer 運算（`tools/ina219_decode.h`）：Current_LSB[µA] = 40960000 / (Cal × R[mΩ])，給 Step 7 的 kernel 用（kernel 不用浮點）。

## 錯誤

- 位址沒有回 ACK（模組拔掉、位址錯）：`ioctl(I2C_RDWR)` 失敗，`errno = EREMOTEIO`（「Remote I/O error」）。實測用不存在的 0x45 模擬；**實際拔線未測**（遠端）。

## 還沒驗證

- 電流方向與大小（DC adapter 接著時電池充飽，shunt 0）：拔掉 adapter 的那一段要在板子旁邊跑 `bash scripts/verify_ina219_raw.sh`。
- R_shunt 是否真的 0.01 Ω。
