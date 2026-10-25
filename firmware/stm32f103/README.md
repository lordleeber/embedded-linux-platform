# STM32F103 I2C target firmware（Step 11、12-a、12-b）

Blue Pill（STM32F103C8T6）用 Standard Peripheral Library 寫成的 I2C target。
Jetson 是 controller，Blue Pill 是 target，位址 **0x42**；register map v1.1（分區、auto-increment、STATUS、版本規則；12-b 加 ADC 與按鍵）定義在 [docs/register-map.md](docs/register-map.md)。

```text
Jetson i2c-1 (c240000.i2c, controller)
  pin 27 SDA ─── PB7 ┐
  pin 28 SCL ─── PB6 ┤ I2C1 (target 0x42) ── i2c_target.c ── PC13 LED（低電位亮）
  GND ────────── GND ┘

Blue Pill 3.3 ──[330 Ω]──┬──[330 Ω]── G      A1 ──[按鍵]── G
                          └── A0（PA0，ADC1 channel 0）   （PA1 內部上拉，SysTick 消抖）
```

## 目錄

| 路徑 | 內容 |
|---|---|
| `Core/Src/i2c_target.c`、`Core/Inc/i2c_target.h` | register protocol（純 C，不碰硬體；host 端由 `tests/test_i2c_target.cpp` 測） |
| `Core/Src/debounce.c`、`Core/Inc/debounce.h` | 按鍵消抖（純 C，1 ms 一個取樣、20 ms 視窗；host 端由 `tests/test_debounce.cpp` 測） |
| `Core/Src/main.c` | SPL 初始化（PC13、I2C1 on PB6 / PB7、ADC1 on PA0、PA1、SysTick）、`I2C1_EV_IRQHandler` / `I2C1_ER_IRQHandler` / `SysTick_Handler`，主迴圈發佈 ADC 值 |
| `Core/Inc/stm32f10x_conf.h` | SPL 設定檔，只 include 用到的五個驅動 |
| `Start/`、`Library/`、`startup/`、`ldscript/` | vendor：CMSIS、SPL V3.5.0（misc / gpio / i2c / rcc / adc）、GCC startup 與 linker script。從使用者的 `STM32_StdPeriph/31_Led_Blink`（commit `eadc71c`）**原樣**複製，SHA-256 在 `vendor.sha256`，不要修改 |

## 建置與燒錄（在 Jetson 上）

PlatformIO Core 裝在 `~/.platformio/penv`（VS Code 的 PlatformIO 擴充也用這個位置）。不指定 `framework`：PlatformIO 的 `framework-spl` 沒有 STM32F1。

```bash
~/.platformio/penv/bin/pio run -d firmware/stm32f103              # 建置
~/.platformio/penv/bin/pio run -d firmware/stm32f103 -t upload    # 建置 + 經 ST-Link (SWD) 燒錄
```

- Jetson 是 aarch64，toolchain 釘在 GCC 12.3.1（`toolchain-gccarmnoneeabi@1.120301.0`）；GCC 7.2.1 沒有 aarch64 版。GCC 12 的 assembler 不收 `-g2`，所以不用 `build_type = debug`。
- ST-Link 第一次插 Jetson 要裝 udev 規則（要 sudo）：
  `sudo cp ~/.platformio/penv/lib/python3.10/site-packages/platformio/assets/system/99-platformio-udev.rules /etc/udev/rules.d/ && sudo udevadm control --reload-rules && sudo udevadm trigger`
- SWD 接不上（`Examination failed`）時：BOOT0 jumper 移到 1、按 RESET，燒錄後 BOOT0 移回 0、再按 RESET。

## 驗收

```bash
bash scripts/verify_stm32_i2c.sh            # 會問 PC13 LED 亮 / 滅（y/n），請人移 A0 的線、按按鍵
bash scripts/verify_stm32_i2c.sh --no-look --no-touch  # 遠端時：不問 LED、不移線、不按按鍵；A0 要接在中點
```

實機測試（`EDGE_STM32_HW=1 python3 -m unittest discover -s tests -p test_stm32_i2c_target.py`）和 `--no-touch` 都假設 A0 接在穩定的電壓（中點）：浮接時 ADC 的兩個實機測試會因雜訊失敗。

手動：

```bash
i2cdetect -y -r 1          # 0x42
i2cget -y 1 0x42 0x00      # 0xed
i2cset -y 1 0x42 0x20 1    # LED 亮
i2cset -y 1 0x42 0x20 0    # LED 滅
i2ctransfer -y 1 w1@0x42 0x00 r4@0x42   # 0xed 0x00 0x03 0x11（auto-increment）
i2ctransfer -y 1 w1@0x42 0x10 r4@0x42   # ADC_LOW ADC_HIGH BUTTON_STATE BUTTON_PRESSES（中點約 0x14 0x08）
i2cget -y 1 0x42 0x30      # STATUS；0x80 = 開機後還沒清過
i2cset -y 1 0x42 0x30 0xff # 清 STATUS（write-1-to-clear）
```

## 進度

- 已實測：Step 11 的四個 register；Step 12-a 的 register map v1.0（PROTOCOL_VERSION、STATUS、auto-increment、讀取不移動 pointer）；Step 12-b 的 v1.1：PA0 的 ADC（GND / 3.3 V / 分壓中點）、同一筆讀取的 LOW / HIGH 來自同一次轉換（A0 浮接跨過 0x800）、PA1 按鍵的狀態與按下次數。
- 只有 host 向量、實機證明不了：20 ms 的消抖視窗（1 ms 的變異版在板子上計數照樣對，見 `docs/baseline.md`）。
- BERR / ARLO / OVR 之後重設 I2C1：重設程序本身實測過（測試用 firmware 每次讀取結束都重設，實機測試全綠），**真正的 bus error 沒有重現過**。
- 還沒做：watchdog（Phase 6）、SPI、DMA、Jetson kernel driver（Step 13）。
