# Repository instructions for coding agents

這個 repository 是 Jetson Orin Nano、STM32、Linux driver 與 Yocto 的逐步實作教材。`ROADMAP.md` 是 Phase 索引；實作前先讀對應的 `phaseNN.md` Step 區塊、`docs/baseline.md`，並參照 `CLAUDE.md` 的架構與文件慣例。不要把規劃中的指令當成已實作功能。

## 工作單位

- 一個 Step 使用一個 `step-N` 分支和一個 PR；拆分的 Step 用 `step-10a` 這類名稱。一次完成、驗證並送出一個 Step，再進入下一步。
- Step 的「這一步不做」是範圍邊界。若預估新增 code 會明顯超過 800 行，先拆 Step，並更新 `ROADMAP.md` 與對應 Phase 文件。
- 描述實作時交代互動雙方、controller/master、target/slave、資料流、元件與 API、驗收方式及範圍外項目。
- 先建立能失敗的測試或硬體驗收 checklist，再實作並讓驗收通過。對無法在目前硬體上執行的項目，清楚標示未實測。

## 每個 Step 的交付

1. 實作與必要測試通過後，在同一個 PR 加入一章 `docs/stepNN.html`（拆分 Step 帶字尾）。章節採單檔自足的深色主題，從最近一章延伸。
2. 更新 `docs/index.html` 的章節順序；新章上線時更新前一章頂部與底部導覽。執行 `python3 scripts/check_book.py docs`。
3. 在 `docs/baseline.md` 追加實測值、比較方式、容差和踩坑紀錄；PR 描述列出驗收證據，區分已實測與未實測。
4. 修改教材引用的函式或檔案時，搜尋 `docs/*.html` 並同步受影響章節。範圍外缺陷記入後續 Step，不順手擴大當前 PR。

若工作環境提供 `/step-execution`、`/incremental-html-textbook` 或 `cold-read` 等技能，依 `CLAUDE.md` 使用；沒有提供時，仍按上述交付與驗收規則完成工作，不假設工具存在。

## 目前可執行的指令

```bash
bash scripts/check_host_env.sh
python3 -m unittest discover -s tests -v
python3 scripts/check_book.py docs
```

要更新這台 Jetson 的版本快照，明確執行 `bash scripts/check_host_env.sh --record docs/jetson-version.txt`。目前硬體尚未接線；接線狀態與待確認的 pin mapping 見 `docs/hardware-wiring.md`。Jetson 是 target，Yocto image 預計在 x86-64 Ubuntu host 建置。Kernel module 應對照 `docs/jetson-version.txt` 的 L4T 和 kernel headers。
