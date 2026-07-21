"""
============================================================
  動態多智能體元沙盤推演系統 - 數據結構定義 (Pydantic v2)
  Dynamic Multi-Agent Meta-Simulation Platform - Data Schemas
  
  v2 改進：動態 Metric 系統
  - 每個場景可自訂環境指標（不再固定 5 個 0-1 float）
  - 指標帶真實單位（dB, HKD, 人/m², %）、data.gov.hk baseline
  - 內部歸一化 + 外部真實單位雙層表示
============================================================
"""

from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any, Tuple
from enum import Enum
from datetime import datetime


# ============================================================
#  第零部分：動態環境指標系統 (Dynamic Metric System)
#  v2 核心改進：取代舊版 5 個固定 0-1 float
# ============================================================

class Metric(BaseModel):
    """
    單個環境指標的完整定義
    
    每個 Metric 有三層表示：
    1. real_value: 真實世界單位（如 65 dB, HK$1,500/天）
    2. normalized: 內部 0.0~1.0（方便 LLM 理解和計算）
    3. display: 人類可讀的格式化字串
    
    使用範例：
        noise = Metric(
            id="noise_db", name="噪音水平", unit="dB(A)",
            real_range=(30, 100), baseline=65,
            description="環境噪音分貝數，深水埗夜市基準約 65dB",
            data_source="EPD 各區噪音投訴統計"
        )
        noise.real_to_norm(65)  # → 0.5
        noise.norm_to_real(0.8) # → 86.0 dB
        noise.format(0.6)       # → "72.0 dB(A) (baseline: 65, +7.0)"
    """
    id: str = Field(..., description="唯一 ID，如 'noise_db', 'vendor_revenue_hkd'")
    name: str = Field(..., description="中文名稱，如 '噪音水平'")
    unit: str = Field(..., description="真實單位，如 'dB(A)', 'HKD/天', '人/m²', '%'")
    
    # 真實世界範圍與基準
    real_min: float = Field(default=0.0, description="真實世界最小值")
    real_max: float = Field(default=100.0, description="真實世界最大值")
    baseline: float = Field(default=50.0, description="data.gov.hk 校準的基準值")
    
    # 內部歸一化範圍
    norm_min: float = Field(default=0.0)
    norm_max: float = Field(default=1.0)
    
    # 描述與來源
    description: str = Field(default="", description="給 LLM 的指標解釋")
    data_source: str = Field(default="", description="校準數據來源 URL 或名稱")
    
    # 影響關係
    affected_by: List[str] = Field(default_factory=list, description="哪些 action_type 影響此指標")
    higher_is_better: bool = Field(default=True, description="數值越高越好？(影響 LLM 判斷)")
    
    # === 轉換方法 ===
    
    def real_to_norm(self, real_value: float) -> float:
        """真實單位 → 0.0~1.0 歸一化"""
        if self.real_max == self.real_min:
            return 0.5
        ratio = (real_value - self.real_min) / (self.real_max - self.real_min)
        return max(0.0, min(1.0, ratio))
    
    def norm_to_real(self, norm_value: float) -> float:
        """0.0~1.0 歸一化 → 真實單位"""
        return self.real_min + norm_value * (self.real_max - self.real_min)
    
    def format(self, real_value: float) -> str:
        """人類可讀的格式化輸出"""
        delta = real_value - self.baseline
        sign = "+" if delta >= 0 else ""
        return f"{real_value:.1f}{self.unit} (Δ{sign}{delta:.1f})"
    
    def format_delta(self, old_real: float, new_real: float) -> str:
        """格式化變化"""
        delta = new_real - old_real
        direction = "↑" if delta > 0 else "↓" if delta < 0 else "→"
        return f"{old_real:.1f} → {new_real:.1f} {self.unit} ({direction}{abs(delta):.1f})"


# ============================================================
#  場景感知的 Metric 模板庫
#  每個場景類型有自己的一組環境指標
#  由 Creator Agent 根據用戶輸入自動選擇
# ============================================================

METRIC_TEMPLATES: Dict[str, List[Metric]] = {
    "night_market": [
        Metric(
            id="noise_db", name="噪音水平", unit="dB(A)",
            real_min=30, real_max=100, baseline=65,
            description="環境噪音分貝數。夜市叫賣聲、人聲、音樂聲。EPD 夜間標準為 55dB。",
            data_source="EPD 各區噪音投訴統計",
            affected_by=["trade", "complain", "enforce"],
            higher_is_better=False,
        ),
        Metric(
            id="crowd_density", name="人群密度", unit="人/m²",
            real_min=0, real_max=5, baseline=1.2,
            description="每平方米人數。深水埗夜市高峰期約 1.5-2.0 人/m²。",
            data_source="運輸署行人流量統計",
            affected_by=["move", "trade", "interact"],
            higher_is_better=False,
        ),
        Metric(
            id="vendor_daily_revenue", name="小販日收入", unit="HKD/天",
            real_min=0, real_max=10000, baseline=1500,
            description="每位小販每日平均營業額。深水埗魚蛋檔約 HK$1,200-2,000/天。",
            data_source="C&SD 零售業統計 + 食環署小販數據",
            affected_by=["trade", "complain", "enforce"],
            higher_is_better=True,
        ),
        Metric(
            id="complaint_count", name="投訴量", unit="件/天",
            real_min=0, real_max=50, baseline=3,
            description="每日收到的噪音/衛生投訴數量。EPD 深水埗月均約 80-100 件。",
            data_source="EPD 各區噪音投訴統計",
            affected_by=["complain", "observe"],
            higher_is_better=False,
        ),
        Metric(
            id="policy_tightness", name="政策執法力度", unit="巡查次數/天",
            real_min=0, real_max=20, baseline=2,
            description="食環署/城管每日巡查次數。常規約 1-2 次，嚴打期可達 8-10 次。",
            data_source="食環署年報",
            affected_by=["complain", "enforce"],
            higher_is_better=False,
        ),
        Metric(
            id="resident_satisfaction", name="居民滿意度", unit="%",
            real_min=0, real_max=100, baseline=60,
            description="居民對居住環境的滿意度百分比。低於 40% 可能觸發集體行動。",
            data_source="區議會民意調查",
            affected_by=["complain", "interact", "observe"],
            higher_is_better=True,
        ),
        Metric(
            id="tourist_count", name="遊客數量", unit="人/晚",
            real_min=0, real_max=5000, baseline=800,
            description="每晚到訪夜市的遊客估計人數。",
            data_source="旅發局訪港旅客統計",
            affected_by=["move", "trade", "interact"],
            higher_is_better=True,
        ),
    ],
    "traffic": [
        Metric(
            id="traffic_flow", name="車流量", unit="輛/小時",
            real_min=0, real_max=5000, baseline=1200,
            description="主要道路每小時車流量。",
            data_source="運輸署交通流量數據",
            affected_by=["move", "enforce"],
            higher_is_better=False,
        ),
        Metric(
            id="congestion_index", name="擁堵指數", unit="指數",
            real_min=0, real_max=10, baseline=4.5,
            description="交通擁堵程度，0=暢通，10=完全堵塞。",
            data_source="運輸署即時交通數據",
            affected_by=["move"],
            higher_is_better=False,
        ),
        Metric(
            id="pedestrian_flow", name="行人流量", unit="人/分鐘",
            real_min=0, real_max=200, baseline=45,
            description="主要路口每分鐘行人通過量。",
            data_source="運輸署行人流量統計",
            affected_by=["move", "interact"],
            higher_is_better=True,
        ),
        Metric(
            id="accident_rate", name="事故率", unit="件/週",
            real_min=0, real_max=20, baseline=3,
            description="每週交通事故數量。",
            data_source="警務處交通報告",
            affected_by=["move"],
            higher_is_better=False,
        ),
        Metric(
            id="air_quality", name="空氣質素", unit="AQI",
            real_min=0, real_max=500, baseline=80,
            description="空氣質素健康指數。100+ 為高風險。",
            data_source="環保署空氣質素數據",
            affected_by=["move"],
            higher_is_better=False,
        ),
        Metric(
            id="public_satisfaction", name="公眾滿意度", unit="%",
            real_min=0, real_max=100, baseline=55,
            description="市民對交通狀況的滿意度。",
            data_source="運輸署公眾意見調查",
            affected_by=["complain", "interact"],
            higher_is_better=True,
        ),
    ],
    "housing": [
        Metric(
            id="rent_per_sqft", name="租金", unit="HKD/呎",
            real_min=10, real_max=80, baseline=35,
            description="每平方呎月租。深水埗私樓約 HK$30-40/呎。",
            data_source="差餉物業估價署租金指數",
            affected_by=["trade", "complain"],
            higher_is_better=False,
        ),
        Metric(
            id="waiting_years", name="公屋輪候時間", unit="年",
            real_min=1, real_max=10, baseline=5.5,
            description="公屋平均輪候時間。2024 年香港約 5.5 年。",
            data_source="房屋署公屋輪候數字",
            affected_by=["complain"],
            higher_is_better=False,
        ),
        Metric(
            id="vacancy_rate", name="空置率", unit="%",
            real_min=0, real_max=30, baseline=5,
            description="住宅空置率。",
            data_source="差餉物業估價署",
            affected_by=["trade"],
            higher_is_better=True,
        ),
        Metric(
            id="new_supply", name="新樓供應", unit="單位/年",
            real_min=0, real_max=50000, baseline=15000,
            description="每年新落成住宅單位數量。",
            data_source="運輸及房屋局",
            affected_by=["enforce"],
            higher_is_better=True,
        ),
        Metric(
            id="affordability_ratio", name="供樓負擔比率", unit="%",
            real_min=20, real_max=80, baseline=55,
            description="樓價與收入中位數比率。>50% 為嚴重難以負擔。",
            data_source="C&SD + 差估署",
            affected_by=["trade", "complain"],
            higher_is_better=False,
        ),
        Metric(
            id="resident_satisfaction", name="居民滿意度", unit="%",
            real_min=0, real_max=100, baseline=50,
            description="居民對居住條件的滿意度。",
            data_source="房屋署居民調查",
            affected_by=["complain", "interact"],
            higher_is_better=True,
        ),
    ],
    "tourism": [
        Metric(
            id="visitor_arrivals", name="訪港旅客", unit="萬人次/月",
            real_min=0, real_max=500, baseline=300,
            description="每月訪港旅客總數。2018 年高峰約 500 萬/月。",
            data_source="旅發局訪港旅客統計",
            affected_by=["move", "trade", "interact"],
            higher_is_better=True,
        ),
        Metric(
            id="hotel_occupancy", name="酒店入住率", unit="%",
            real_min=0, real_max=100, baseline=80,
            description="酒店平均入住率。",
            data_source="旅發局酒店統計",
            affected_by=["trade"],
            higher_is_better=True,
        ),
        Metric(
            id="avg_spending", name="人均消費", unit="HKD/天",
            real_min=0, real_max=5000, baseline=2000,
            description="旅客每日人均消費。",
            data_source="旅發局旅客消費調查",
            affected_by=["trade"],
            higher_is_better=True,
        ),
        Metric(
            id="overcrowding_complaints", name="過度旅遊投訴", unit="件/月",
            real_min=0, real_max=500, baseline=50,
            description="居民對過度旅遊的投訴數量。",
            data_source="區議會 + 民政事務署",
            affected_by=["complain"],
            higher_is_better=False,
        ),
        Metric(
            id="local_satisfaction", name="居民滿意度", unit="%",
            real_min=0, real_max=100, baseline=55,
            description="居民對旅遊業影響的滿意度。",
            data_source="旅發局社區意見調查",
            affected_by=["complain", "interact"],
            higher_is_better=True,
        ),
        Metric(
            id="retail_revenue", name="零售收入", unit="億HKD/月",
            real_min=0, real_max=50, baseline=30,
            description="每月零售業總收入。",
            data_source="C&SD 零售業銷貨額統計",
            affected_by=["trade"],
            higher_is_better=True,
        ),
    ],
}


def get_metric_template(scenario_type: str) -> List[Metric]:
    """根據場景類型獲取對應的 Metric 模板"""
    return METRIC_TEMPLATES.get(scenario_type, METRIC_TEMPLATES["night_market"])


def detect_scenario_type(scenario_text: str) -> str:
    """從場景描述自動檢測場景類型"""
    keywords = {
        "night_market": ["夜市", "小販", "攤檔", "排檔", "叫賣", "熟食", "魚蛋", "大排檔"],
        "traffic": ["交通", "塞車", "行人", "馬路", "車輛", "巴士", "地鐵", "隧道", "天橋", "斑馬線", "道路"],
        "housing": ["房屋", "租金", "公屋", "居屋", "置業", "樓價", "輪候", "住屋", "蝸居", "劏房"],
        "tourism": ["旅遊", "遊客", "景點", "酒店", "消費", "購物", "觀光", "打卡"],
    }
    scores = {}
    for stype, kws in keywords.items():
        scores[stype] = sum(1 for kw in kws if kw in scenario_text)
    
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "night_market"


# ============================================================
#  第一部分：智能體定義
# ============================================================

class EmotionState(str, Enum):
    NEUTRAL = "neutral"
    HAPPY = "happy"
    ANXIOUS = "anxious"
    ANGRY = "angry"
    FEARFUL = "fearful"
    EXCITED = "excited"


class ActionThreshold(BaseModel):
    noise_tolerance: float = Field(default=0.7, ge=0.0, le=1.0)
    crowd_pressure_threshold: float = Field(default=0.6, ge=0.0, le=1.0)
    economic_stress_threshold: float = Field(default=0.5, ge=0.0, le=1.0)
    social_interaction_drive: float = Field(default=0.5, ge=0.0, le=1.0)


class AgentPersona(BaseModel):
    agent_id: str
    name: str
    role: str
    background: str
    core_motivation: str
    personality_traits: List[str] = Field(default_factory=list)
    action_thresholds: ActionThreshold = Field(default_factory=ActionThreshold)
    initial_emotion: EmotionState = Field(default=EmotionState.NEUTRAL)
    available_tools: List[str] = Field(default_factory=list)
    initial_memory: Optional[str] = Field(default=None)


# ============================================================
#  第二部分：環境狀態 (v2 - 動態 Metric)
# ============================================================

class WeatherCondition(str, Enum):
    SUNNY = "sunny"
    CLOUDY = "cloudy"
    RAINY = "rainy"
    STORMY = "stormy"
    HOT = "hot"
    COLD = "cold"


class EnvironmentState(BaseModel):
    """
    v2 環境狀態：支援動態 Metric
    
    - metrics: 動態指標字典，key=metric_id, value=真實單位數值
    - metric_definitions: 指標定義（從 SimulationConfig 注入）
    
    向後兼容：保留舊版 legacy 屬性（noise_level, crowd_density 等），
    自動從 metrics 字典中讀寫對應的歸一化值。
    """
    # 時間
    day: int = Field(default=1, ge=1)
    date: str = Field(default="2008-01-01")
    
    # === v2: 動態指標 ===
    metrics: Dict[str, float] = Field(
        default_factory=dict,
        description="動態環境指標，key=metric_id, value=真實單位數值。"
                    "例如: {'noise_db': 65.0, 'vendor_daily_revenue': 1500.0}"
    )
    metric_definitions: Dict[str, Any] = Field(
        default_factory=dict,
        description="指標定義字典，key=metric_id。由 SimulationConfig 注入。"
    )
    
    # === 向後兼容：legacy 屬性 ===
    noise_level: float = Field(default=0.3, ge=0.0, le=1.0, description="[legacy] 噪音歸一化值")
    crowd_density: float = Field(default=0.3, ge=0.0, le=1.0, description="[legacy] 人群歸一化值")
    economic_activity: float = Field(default=0.5, ge=0.0, le=1.0, description="[legacy] 經濟歸一化值")
    social_stability: float = Field(default=0.8, ge=0.0, le=1.0, description="[legacy] 社會穩定歸一化值")
    policy_pressure: float = Field(default=0.2, ge=0.0, le=1.0, description="[legacy] 政策壓力歸一化值")
    
    # 天氣 / 事件
    weather: WeatherCondition = Field(default=WeatherCondition.SUNNY)
    is_holiday: bool = Field(default=False)
    special_event: Optional[str] = Field(default=None)
    domain_context: str = Field(default="")
    
    # === Metric 輔助方法 ===
    
    def get_metric_def(self, metric_id: str) -> Optional[Metric]:
        """獲取指標定義"""
        raw = self.metric_definitions.get(metric_id)
        if raw is None:
            return None
        if isinstance(raw, Metric):
            return raw
        return Metric(**raw) if isinstance(raw, dict) else None
    
    def get_real(self, metric_id: str) -> Optional[float]:
        """獲取指標的真實單位值"""
        return self.metrics.get(metric_id)
    
    def set_real(self, metric_id: str, real_value: float):
        """設定指標的真實單位值"""
        self.metrics[metric_id] = real_value
    
    def get_normalized(self, metric_id: str) -> float:
        """獲取指標的 0.0~1.0 歸一化值"""
        real = self.metrics.get(metric_id)
        if real is None:
            return 0.5
        mdef = self.get_metric_def(metric_id)
        if mdef:
            return mdef.real_to_norm(real)
        return real  # fallback
    
    def apply_delta(self, metric_id: str, delta: float):
        # 限制單日變化幅度避免數值爆炸 (max ±0.2/day)
        delta = max(-0.2, min(0.2, delta))
        """對指標施加變化量（delta 為歸一化值）"""
        mdef = self.get_metric_def(metric_id)
        if mdef:
            current_real = self.metrics.get(metric_id, mdef.baseline)
            current_norm = mdef.real_to_norm(current_real)
            new_norm = max(0.0, min(1.0, current_norm + delta))
            self.metrics[metric_id] = mdef.norm_to_real(new_norm)
    
    def init_metrics_from_definitions(self):
        """根據 metric_definitions 初始化所有 metrics 為 baseline"""
        for mid, raw_def in self.metric_definitions.items():
            mdef = raw_def if isinstance(raw_def, Metric) else Metric(**raw_def)
            if mid not in self.metrics:
                self.metrics[mid] = mdef.baseline
    
    def format_metrics_summary(self) -> str:
        """生成人類可讀的指標摘要"""
        lines = []
        for mid, real_val in sorted(self.metrics.items()):
            mdef = self.get_metric_def(mid)
            if mdef:
                lines.append(f"  {mdef.name}: {mdef.format(real_val)}")
            else:
                lines.append(f"  {mid}: {real_val:.1f}")
        return "\n".join(lines) if lines else "  (無指標)"
    
    # 別名（向後兼容 engine.py）
    def format_for_llm(self) -> str:
        """給 LLM 看的格式（真實單位）"""
        return self.format_metrics_summary()
    
    def format_short(self) -> str:
        """簡短輸出格式"""
        parts = []
        for mid, real_val in sorted(self.metrics.items()):
            mdef = self.get_metric_def(mid)
            if mdef:
                parts.append(f"{mdef.name}={mdef.format(real_val)}")
        return ", ".join(parts[:5]) if parts else "no metrics"
    
    def apply_effect(self, metric_id: str, delta: float):
        """對指標施加歸一化變化量（別名）"""
        self.apply_delta(metric_id, delta)
    
    def format_metrics_delta(self, before: "EnvironmentState") -> str:
        """生成指標變化摘要（與之前比較）"""
        lines = []
        for mid in self.metrics:
            mdef = self.get_metric_def(mid)
            old = before.metrics.get(mid, 0)
            new = self.metrics.get(mid, 0)
            if mdef:
                lines.append(f"  {mdef.name}: {mdef.format_delta(old, new)}")
            else:
                lines.append(f"  {mid}: {old:.1f} → {new:.1f}")
        return "\n".join(lines) if lines else "  (無變化)"


# ============================================================
#  第三部分：模擬配置 (v2 - 含 Metric 定義)
# ============================================================

class SimulationConfig(BaseModel):
    simulation_id: str
    title: str
    description: str = ""
    max_days: int = Field(default=30, ge=1, le=365)
    start_date: str = Field(default="2008-01-01")
    
    # === 初始環境 ===
    initial_environment: EnvironmentState = Field(default_factory=EnvironmentState)
    
    # === v2: 場景感知 Metric 定義 ===
    scenario_type: str = Field(
        default="night_market",
        description="場景類型: night_market, traffic, housing, tourism"
    )
    active_metrics: List[str] = Field(
        default_factory=list,
        description="此模擬使用的 metric ID 列表（從模板中選擇）"
    )
    
    # === 智能體 ===
    agents: List[AgentPersona] = Field(default_factory=list)
    global_tools: List[str] = Field(default_factory=list)
    data_sources: List[Dict[str, str]] = Field(default_factory=list)
    
    # === LLM 配置 ===
    llm_model: str = Field(default="deepseek-chat")
    llm_temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    
    def get_metric_definitions(self) -> Dict[str, Metric]:
        """獲取此場景的完整 Metric 定義"""
        template = get_metric_template(self.scenario_type)
        if self.active_metrics:
            return {m.id: m for m in template if m.id in self.active_metrics}
        return {m.id: m for m in template}
    
    def init_metrics(self):
        """初始化環境的 metrics（用 baseline 值 + 注入定義）"""
        mdefs = self.get_metric_definitions()
        self.initial_environment.metric_definitions = {
            mid: m.model_dump() for mid, m in mdefs.items()
        }
        self.initial_environment.init_metrics_from_definitions()
        # 同步 legacy 屬性
        self._sync_legacy_fields(self.initial_environment)
    
    @staticmethod
    def _sync_legacy_fields(env: EnvironmentState):
        """同步 legacy 欄位與 metrics（向後兼容）"""
        legacy_map = {
            "noise_level": ["noise_db", "noise_level", "congestion_index"],
            "crowd_density": ["crowd_density", "pedestrian_flow", "visitor_arrivals"],
            "economic_activity": ["vendor_daily_revenue", "retail_revenue", "avg_spending", "economic_activity"],
            "social_stability": ["resident_satisfaction", "public_satisfaction", "local_satisfaction"],
            "policy_pressure": ["policy_tightness", "complaint_count", "overcrowding_complaints", "enforcement"],
        }
        for legacy_key, candidates in legacy_map.items():
            for c in candidates:
                mdef = env.get_metric_def(c)
                if mdef and c in env.metrics:
                    setattr(env, legacy_key, mdef.real_to_norm(env.metrics[c]))
                    break


# ============================================================
#  第四部分：運行時記錄
# ============================================================

class AgentAction(BaseModel):
    agent_id: str
    day: int
    timestamp: str
    action_type: str
    action_description: str
    duration_minutes: int = Field(default=30, ge=1)
    target_agent_id: Optional[str] = Field(default=None)
    environment_effects: Dict[str, float] = Field(default_factory=dict)
    tool_calls: List[Dict[str, Any]] = Field(default_factory=list)


class DayLog(BaseModel):
    day: int
    date: str
    actions: List[AgentAction] = Field(default_factory=list)
    environment_before: EnvironmentState
    environment_after: EnvironmentState
    notable_events: List[str] = Field(default_factory=list)
    emergent_phenomena: List[str] = Field(default_factory=list)


class SimulationResult(BaseModel):
    simulation_id: str
    total_days_simulated: int
    all_day_logs: List[DayLog] = Field(default_factory=list)
    executive_summary: str = ""
    key_metrics: Dict[str, Any] = Field(default_factory=dict)
    emergent_behaviors: List[str] = Field(default_factory=list)
    agent_final_states: Dict[str, str] = Field(default_factory=dict)
    scenario_type: str = "night_market"
    metric_definitions: Dict[str, Any] = Field(default_factory=dict)
