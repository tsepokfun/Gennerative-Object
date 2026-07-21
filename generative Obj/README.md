# 動態多智能體元沙盤推演系統

> **Meta-Simulation Platform** — 基於 LangGraph + DeepSeek + ChromaDB 的社會動態模擬系統  
> 2024-2026「18區日夜都繽紛」政策案例 | HKICT 2026 參賽項目

---

## 🎯 一句話描述

輸入一句自然語言場景描述（如「模擬深水埗夜市噪音政策對小販與居民的影響」），
系統自動生成基於真實人口數據的智能體，執行 LangGraph 多智能體模擬，
輸出結構化社會動態分析報告。

---

## 🚀 快速開始

```bash
# 1. 安裝依賴
pip install -r requirements.txt

# 2. 設定 API Key (DeepSeek)
set DEEPSEEK_API_KEY=sk-your-key-here

# 3. 執行互動規劃器
python main.py --plan

# 4. 或一句話快速啟動
python main.py --quick "深水埗夜市新政策對小販生計的影響"
```

---

## 📁 專案結構

```
├── models.py              # Pydantic 數據模型 (Metric 系統 + 4 場景模板)
├── engine.py              # LangGraph 核心引擎 (四層防線)
├── memory_manager.py      # ChromaDB 向量記憶管理器
├── tools.py               # MCP 工具掛載點
├── data_pipeline.py       # data.gov.hk 政府數據管道
├── district_sim.py        # 18 區批量模擬系統
├── live_server.py         # WebSocket 即時儀表板
├── gen_report.py          # HTML 報告生成器
├── main.py                # 互動規劃器 (主要入口)
├── ssp_night_vibes_sim.py # 深水埗深度案例
├── run_report.py          # 單案例 HTML 報告
│
├── GF.py                  # [舊版] 全域變數
├── ObjInfo.py             # [舊版] 智能體資訊
├── ggg.py                 # [舊版] LLM 包裝
├── timeLine.py            # [舊版] 主循環
└── fact.txt               # [舊版] 靜態知識
```

---

## 🏗️ 系統架構

```
用戶輸入 → PopulationProfiler + GovDataPipeline → Creator Agent → LangGraph 引擎 → SimulationResult
               │                        │                │              │
          人口普查約束           data.gov.hk 校準     LLM 生成智能體    perceive→action
          (18區真實數據)         (噪音/收入baseline)   (12個研究角色)   →settle→advance
```

### 核心創新

| 創新 | 說明 |
|:---|:---|
| **動態 Metric 系統** | 每場景自訂指標，真實單位 (dB, HKD, 人/m²)，data.gov.hk 校準 baseline |
| **四層防線** | LLM語義→dict→keyword→empty，確保每個行動都有數字化的環境影響 |
| **ChromaDB 長期記憶** | Agent 從歷史經驗中學習，避免重複同樣錯誤 |
| **18 區人口約束** | Agent 生成受真實人口統計約束（職業/收入/年齡分佈） |
| **互動規劃器** | 分析場景複雜度、推薦規模、預估成本後才執行 |

---

## 📊 可用指令

```bash
# 互動規劃器 (推薦)
python main.py --plan

# 18 區批量模擬
python district_sim.py --all          # 全部 18 區 (~12 分鐘, HK$3)
python district_sim.py --sample 3     # 前 3 區測試

# 深水埗深度案例 (12 智能體 × 14 天)
python ssp_night_vibes_sim.py

# 即時儀表板
python live_server.py                 # 啟動後打開 http://localhost:8765

# HTML 報告
python gen_report.py                  # 從最新 JSON 生成 18 區對比報告

# 快速測試 (2 智能體 × 3 天)
python engine.py
```

---

## 🎮 互動規劃器流程

```
Phase 1: 場景描述 → 輸入自然語言
Phase 2: 規模分析 → 自動推薦最佳規模，顯示 5 種選項及成本
Phase 3: 確認配置 → 調整參數或確認執行
Phase 4: 執行模擬 → LangGraph 每日循環，即時輸出進度
```

---

## 📈 規模選項

| 規模 | 智能體 | 天數 | API 調用 | 時間 | 成本 (HKD) |
|:---|:---|:---|:---|:---|:---|
| 微型 | 3 人 | 3 天 | 14 次 | 21 秒 | $0.05 |
| 小型 | 5 人 | 5 天 | 32 次 | 48 秒 | $0.10 |
| 中型 | 8 人 | 7 天 | 65 次 | 98 秒 | $0.20 |
| 大型 | 12 人 | 14 天 | 184 次 | 276 秒 | $0.55 |
| 最大 | 20 人 | 30 天 | 632 次 | 948 秒 | $2.00 |

---

## 🔧 技術棧

| 層 | 技術 |
|:---|:---|
| 多智能體編排 | **LangGraph** (StateGraph + 條件邊) |
| LLM | **DeepSeek** (deepseek-chat) via LangChain |
| 向量記憶 | **ChromaDB** + Sentence Transformers |
| 數據模型 | **Pydantic v2** |
| 即時推送 | **WebSocket** (websockets) |
| 報告 | Chart.js + 靜態 HTML |
| 數據來源 | 2021 人口普查 + 2024-2026 政策研究 + data.gov.hk |

---

## 📝 環境變數

```bash
# 必須設定
DEEPSEEK_API_KEY=sk-your-key-here

# 可選
DEEPSEEK_MODEL=deepseek-chat        # 預設
DEEPSEEK_BASE_URL=https://api.deepseek.com
```

---

## 📄 授權

本專案為 HKICT 2026 參賽作品，僅供學術展示使用。

---

## 👥 舊版對比

| 舊版 (v1) | 新版 (v2) |
|:---|:---|
| `ObjInfo.py` 三個平行 list | `models.py` Pydantic v2 |
| `ggg.py` 單一 `gR(q)` 函數 | `tools.py` MCP 工具掛載 + ToolRegistry |
| `GF.py` 全域變數 `action[]` | `engine.py` LangGraph StateGraph |
| `fact.txt` 靜態文字 | ChromaDB 向量檢索 + data.gov.hk |
| 硬編碼 `while` 迴圈 | 互動規劃器 + 批量 18 區執行 |
| 固定 5 個 0-1 指標 | 動態 Metric 系統 (真實單位) |
