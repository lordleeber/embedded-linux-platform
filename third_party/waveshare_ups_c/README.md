# Waveshare UPS Power Module (C) — INA219 範例

`ina219.py` 是 Waveshare 隨 UPS Power Module (C) 提供的 Python 範例，從板上的 `~/UPS_Power_Module_C/ina219.py` 原樣複製（檔案日期 2024-10-26），**不修改**：Step 6-a 的教材逐行解說它，`tests/test_ina219_sample.py` 用 SHA-256 釘住內容。

```text
sha256  ceb770e56f2feae3af0b29dc237e94097e12704b555afc5024e3214efca748fb
```

- 執行：`python3 third_party/waveshare_ups_c/ina219.py`（需要 `python3-smbus`、使用者在 `i2c` 群組；每 2 秒印一組，Ctrl-C 結束）
- 它會在啟動時**寫入** INA219 的 Calibration 與 Config register，之後只讀
- 檔案沒有授權聲明；`INA219` 類別的結構與註解和 Adafruit CircuitPython INA219（MIT）的 `set_calibration_*` 相同，推測由它改寫（未查證）
- 自己的工具與 driver 在 Step 6-b 之後另寫，不 import 這個檔案
