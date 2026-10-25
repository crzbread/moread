# 逐筆提交 Review 紀錄

日期：2026-10-25（Asia/Taipei）

## 範圍與流程

依使用者要求，重建原有 6 筆功能提交。每筆先套用到隔離工作目錄的暫存區，由另一位 Herdr 助手 `reader-review`（GPT-6.1-Sol / high）檢查，再由主助手提交。僅檢查可維護性與可讀性；沒有依 review 修改程式、測試或既有文件，也未執行行為／安全稽核。

保留原提交的功能分組與訊息，不宣稱本輪改善了原本的提交邊界。所有新提交皆使用實際操作時間，沒有設定 Git 日期覆寫。原歷史備份：`backup/pre-review-rebuild-20261025`。

本輪到紀錄完成為止；下方改善清單尚未實作，留待下一輪集中修改。

## 新舊提交對照

| 次序 | 原提交 | 重建提交 | 提交前 review |
| --- | --- | --- | --- |
| 1 | `d5e9a33` | `c5d2f4e` | 已完成 REVIEW 1 |
| 2 | `92a4d3e` | `f549078` | 已完成 REVIEW 2 |
| 3 | `d966e0c` | `2856616` | 已完成 REVIEW 3 |
| 4 | `a3fdd27` | `d9dfe97` | 已完成 REVIEW 4 |
| 5 | `abf1af6` | `32ef57b` | 已完成 REVIEW 5 |
| 6 | `4ac7398` | `7203b7c` | 已完成 REVIEW 6 |

## 逐筆發現

### 1. d5e9a33 → c5d2f4e

- **R1.1**：Package.manifest 使用三元素 tuple，建議具名資料結構表達 path、media type、properties。
- **R1.2**：read_toc() 混合 EPUB nav、NCX、映射與備援，建議分離格式解析及集中選擇流程。
- **R1.3**：TextParser / Line 的 size、offset、start/end 單位與邊界缺乏集中說明，應區分文字索引、字素及終端格寬。
- **R1.4**：State.__init__ 混合讀檔、驗證、建立物件，建議抽出位置解析及驗證函式。
- **R1.5**：make_epub fixture 的 XML 長單行難核對，建議多行模板並註明 spine 順序。

### 2. 92a4d3e → f549078

- **R2.1**：Shelf.refresh_books() 混合排序、欄寬、列內容、選取恢復及狀態文字，建議按職責拆小函式。
- **R2.2**：ReaderApp.background()/drain_results() 以六元素 tuple 及泛用 Callable 傳遞訊息，建議具名訊息及回呼型別，說明取消與完成契約。
- **R2.3**：scan_directory() 與 scan_library() 重複 EPUB metadata 讀取，建議共用讀取函式，保留各自目錄探索政策。
- **R2.4**：Settings.compose() 與 Config.validate() 重複主題、寬度限制，建議共用常數。
- **R2.5**：preferred_key 混用路徑、None、__default__，另有 __parent__ 列鍵，建議具名常數與選取恢復規則文件。

### 3. d966e0c → 2856616

無新增發現。OpenCC 設定切換集中，沿用參數化測試及文件，不需額外抽象。

### 4. a3fdd27 → d9dfe97

- **R4.1**：ReaderApp.check_action()/Shelf.update_help() 分別處理 q 可用情境及提示，建議共用具名情境判斷，避免增加輸入元件時漏同步。
- **R4.2**：test_q_exits_outside_inputs() 重複 panic 測試進入 Reading/TOC/Settings 的流程，建議小型情境導覽 helper。

### 5. abf1af6 → 32ef57b

- **R5.1**：Shelf.refresh_books()/update_help()/CSS 的 compact 分別指高度或寬度，斷點散落；屬第2筆第1項延伸，建議區分列密度與提示密度並集中版面規則。
- **R5.2**：Shelf/Loading/Reading/open_entry 重複 panic 按鍵格式化，建議共用小型格式化函式。
- **R5.3**：test_adaptive_shelf_spacing_preserves_rows_progress_and_metadata 同時驗證列高、樣式、提示、捲動、縮放，建議依呈現/導覽/縮放拆分。

### 6. 4ac7398 → 7203b7c

- **R6.1**：tests/test_reader_settings.py 直接從 test_app 匯入 make_app/ready/until，測試檔兼任程式庫；建議專用 helper/fixture。
- **R6.2**：Config.mode 語意已限縮為空白鍵動作，名稱仍泛稱 mode；建議欄位註解或具名存取介面，保留 TOML 相容。
- **R6.3**：Reading.BINDINGS/render_page() 在 binding、寬版及窄版提示各自手寫鍵位描述，建議共用資料來源再組合版面。

## 最終版本對照與去重

- R1.1–R1.5、R2.1–R2.5、R4.1、R5.1–R5.3 在最終版本仍存在；R6.1–R6.3 是最後一筆新增的維護性紀錄。
- R4.2 部分改善：後續新增 `open_reading()`，但 q／panic 測試仍有重複畫面導覽；未結案。
- R5.1 是 R2.1 的延伸，集中改善時合併處理，保留斷點命名與列高規則細節。
- R6.1 與 R4.2 應同批整理測試 helper 與 fixture。
- 未發現先前維護性項目已完整解決；R3 原本無新增發現。

## 下一輪集中改善清單（尚未執行）

1. **書櫃呈現流程**：拆分 `Shelf.refresh_books()`，集中版面斷點及列高規則，說清楚選取狀態與特殊列鍵（R2.1、R2.5、R5.1）。
2. **按鍵與提示的一致來源**：共用退出情境判斷、鍵位／描述與 panic 顯示格式，仍允許各畫面獨立排版（R4.1、R5.2、R6.3）。
3. **設定語意**：共用主題和寬度限制；為 `mode` 補明確語意，保留現有設定檔相容（R2.4、R6.2）。
4. **具名資料與解析責任**：為 manifest、背景工作訊息與回呼建立明確型別；拆分 TOC 格式解析、進度資料驗證（R1.1、R1.2、R1.4、R2.2）。
5. **書庫共用讀取**：抽出 metadata 讀取，維持兩種掃描的探索政策（R2.3）。
6. **位置單位文件**：記錄文字索引、字素與終端格寬及 end/newline 邊界（R1.3）。
7. **測試可讀性**：整理 fixture XML、共用導覽 helper、解除測試檔互相匯入，拆分涵蓋太多情境的測試（R1.5、R4.2、R5.3、R6.1）。

以上為後續評估清單，不應為了抽象而抽象；先維持既有功能，再逐組改善與驗證。

## 本輪驗證

- 六筆重建後、加入本檔案前的 Git tree 與原版完全相同：`97d4672161ac896d20ffc1f240ddc7cf2de34724`。
- `git diff backup/pre-review-rebuild-20261025 7203b7c` 為空。
- 每一對原／新功能提交保留相同快照（由最終核對程序逐對確認）。
- 本輪未重新執行功能測試：程式、測試與依賴檔內容皆未變動，以 Git 快照相等驗證重建完整性。
- 最終相對原版僅新增本 `review.md`；備份分支保留舊歷史，新的功能提交日期皆為 2026-10-25。

