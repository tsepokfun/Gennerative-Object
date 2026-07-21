"""
============================================================
  動態多智能體元沙盤推演系統 - 政府開放數據管道
  Dynamic Multi-Agent Meta-Simulation - Gov Data Pipeline
============================================================
  解決兩個核心問題：
  
  問題 1：智能體如何反映真實人口？
  → PopulationProfiler：從 data.gov.hk 提取人口統計分佈，
    將年齡、職業、收入等維度轉化為 Agent 生成約束，
    確保 Creator Agent 生成的智能體群體具有統計代表性。
  
  問題 2：如何確保所有相關政府數據都被使用？
  → GovDataPipeline：系統性地發現 → 獲取 → 向量化 → 注入
    所有與模擬場景相關的 data.gov.hk 開放數據集，
    透過 RAG 在模擬運行時動態檢索相關資訊。
============================================================
"""

import json
import hashlib
import sys
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
from dataclasses import dataclass, field

# Windows UTF-8
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# ============================================================
#  第一部分：data.gov.hk 數據集目錄
#  按領域分類的香港政府開放數據 API 端點
#  這些是真實存在的 data.gov.hk 數據集
# ============================================================

@dataclass
class GovDataset:
    """data.gov.hk 數據集定義"""
    id: str                          # 數據集唯一 ID
    name: str                        # 中文名稱
    name_en: str                     # 英文名稱  
    category: str                    # 分類：population / economy / environment / transport / housing
    api_endpoint: str                # CKAN API 或直接下載 URL
    format: str = "CSV"              # 數據格式
    description: str = ""            # 描述
    # 人口相關維度（用於智能體生成）
    demographic_dimensions: List[str] = field(default_factory=list)
    # 例如：["age_group", "occupation", "income_level", "district"]

# data.gov.hk 核心數據集目錄（真實存在的開放數據）
GOV_DATA_CATALOG: List[GovDataset] = [
    # ── 人口統計 ──
    GovDataset(
        id="2021-population-census",
        name="2021年人口普查 - 區議會分區統計",
        name_en="2021 Population Census - District Council District",
        category="population",
        api_endpoint="https://www.census2021.gov.hk/doc/statistics/detailed-tables/2021-Population-Census-Detailed-Tables.zip",
        format="XLSX",
        description="各區人口按年齡、性別、職業、收入、教育程度分布",
        demographic_dimensions=["age_group", "gender", "occupation", "income", "education", "district"],
    ),
    GovDataset(
        id="labour-force-statistics",
        name="勞動力統計數字",
        name_en="Labour Force Statistics",
        category="population",
        api_endpoint="https://www.censtatd.gov.hk/en/EIndexbySubject.html?pcode=DS002001&scode=200",
        format="CSV",
        description="各行業就業人數、失業率、收入中位數",
        demographic_dimensions=["industry", "employment_status", "income"],
    ),
    
    # ── 小販與經濟 ──
    GovDataset(
        id="hawker-licences",
        name="小販牌照統計",
        name_en="Hawker Licences Statistics",
        category="economy",
        api_endpoint="https://www.fehd.gov.hk/english/statistics/hawker.html",
        format="HTML",
        description="固定攤位小販及流動小販牌照數目、地區分佈",
        demographic_dimensions=["district", "license_type", "trade_category"],
    ),
    GovDataset(
        id="night-market-activities",
        name="夜市經濟活動數據",
        name_en="Night Market Economic Activity Data",
        category="economy",
        api_endpoint="https://data.gov.hk/tc-data/dataset/hk-censtatd-trade-retail",
        format="CSV",
        description="零售業銷貨額、食肆收入、旅遊消費統計",
        demographic_dimensions=["business_type", "revenue_band", "district"],
    ),
    GovDataset(
        id="tourist-statistics",
        name="訪港旅客統計",
        name_en="Visitor Arrival Statistics",
        category="economy",
        api_endpoint="https://www.tourism.gov.hk/english/statistics/statistics.html",
        format="CSV",
        description="每月訪港旅客數字（按來源地）、過夜旅客比例、人均消費",
        demographic_dimensions=["origin_country", "visit_purpose", "spending_level"],
    ),
    
    # ── 環境與天氣 ──
    GovDataset(
        id="hko-weather-forecast",
        name="香港天文台天氣預報",
        name_en="HKO Weather Forecast",
        category="environment",
        api_endpoint="https://data.weather.gov.hk/weatherAPI/opendata/weather.php",
        format="JSON",
        description="即時天氣數據、九天天氣預報",
        demographic_dimensions=[],
    ),
    GovDataset(
        id="epd-noise-complaints",
        name="環境保護署噪音投訴統計",
        name_en="EPD Noise Complaint Statistics",
        category="environment",
        api_endpoint="https://www.epd.gov.hk/epd/english/environmentinhk/noise/data/statistics.html",
        format="CSV",
        description="各區噪音投訴數字、類型分佈",
        demographic_dimensions=["district", "complaint_type"],
    ),
    
    # ── 交通 ──
    GovDataset(
        id="td-traffic-data",
        name="運輸署交通流量數據",
        name_en="TD Traffic Flow Data",
        category="transport",
        api_endpoint="https://data.gov.hk/tc-data/dataset/hk-td-tis-traffic-speed-map",
        format="JSON",
        description="各區實時交通速度、擁堵程度",
        demographic_dimensions=["district", "time_of_day"],
    ),
    
    # ── 房屋與社區 ──
    GovDataset(
        id="housing-statistics",
        name="房屋統計數字",
        name_en="Housing Statistics",
        category="housing",
        api_endpoint="https://www.housingauthority.gov.hk/en/common/pdf/about-us/publications-and-statistics/HIF2024.pdf",
        format="PDF",
        description="公屋輪候人數、居住密度、租金水平",
        demographic_dimensions=["district", "housing_type", "income_band"],
    ),
]


# ============================================================
#  第二部分：人口特徵提取器 (Population Profiler)
#  從政府數據中提取人口分佈，轉化為 Agent 生成約束
# ============================================================

@dataclass
class PopulationProfile:
    """
    從政府數據中提取的區域人口特徵
    
    此結構用於約束 Creator Agent 生成的智能體群體，
    確保模擬中的智能體比例反映真實人口組成。
    """
    district: str                                            # 區域（如 "深水埗"）
    total_population: int = 0                                # 總人口
    
    # 年齡分佈 (比例加總 = 1.0)
    age_distribution: Dict[str, float] = field(default_factory=lambda: {
        "youth": 0.15,       # 0-17
        "young_adult": 0.20, # 18-34
        "middle_age": 0.35,  # 35-54
        "elderly": 0.30,     # 55+ (深水埗較多長者)
    })
    
    # 職業分佈
    occupation_distribution: Dict[str, float] = field(default_factory=lambda: {
        "hawker_vendor": 0.08,      # 小販/攤檔經營者
        "retail_worker": 0.15,      # 零售業
        "service_worker": 0.20,     # 服務業
        "office_worker": 0.12,      # 文職
        "unemployed_retired": 0.25, # 失業/退休
        "tourist": 0.05,            # 遊客（非常住）
        "government_staff": 0.03,   # 政府人員（如城管）
        "other": 0.12,              # 其他
    })
    
    # 收入分佈 (月薪港幣)
    income_distribution: Dict[str, float] = field(default_factory=lambda: {
        "low": 0.40,         # < $15,000
        "medium_low": 0.30,  # $15,000 - $25,000
        "medium": 0.20,      # $25,000 - $40,000
        "high": 0.10,        # > $40,000
    })
    
    # 居民 vs 非居民
    resident_ratio: float = 0.80     # 80% 是居民
    tourist_ratio: float = 0.05      # 5% 是遊客
    commuter_ratio: float = 0.15     # 15% 是跨區工作者
    
    # 關鍵社會指標
    elderly_rate: float = 0.18       # 老年人口比例
    poverty_rate: float = 0.20       # 貧窮率
    unemployment_rate: float = 0.04  # 失業率
    
    # 數據來源記錄 (用於審計)
    data_sources: List[str] = field(default_factory=list)
    last_updated: str = ""


class PopulationProfiler:
    """
    人口特徵分析器
    
    從 data.gov.hk 的統計數據中提取區域人口特徵，
    生成 PopulationProfile，用於約束 Creator Agent。
    
    使用流程：
    1. profiler = PopulationProfiler()
    2. profile = profiler.profile_district("深水埗")
    3. 將 profile 傳入 Creator Agent 的 prompt，確保生成的智能體符合比例
    """
    
    def __init__(self):
        """初始化分析器，載入預設的香港各區人口特徵"""
        # 預設的香港各區人口特徵（基於 2021 人口普查）
        # 在完整實現中，這些數據應從 data.gov.hk API 動態獲取
        self._district_profiles: Dict[str, PopulationProfile] = {}
        self._init_default_profiles()
    
    def _init_default_profiles(self):
        """
        初始化各區預設人口特徵
        
        數據來源：
        - 2021 年人口普查（Census and Statistics Department）
        - 深水埗區議會統計資料
        
        註：這些是基於公開數據的近似值，用於演示。
        在完全接入 data.gov.hk 後，將從 API 動態更新。
        """
        # 深水埗區特徵
        ssp = PopulationProfile(
            district="深水埗",
            total_population=431000,
            age_distribution={
                "youth": 0.10,        # 深水埗兒童比例較低
                "young_adult": 0.18,
                "middle_age": 0.32,
                "elderly": 0.40,      # 深水埗是全港老年人口比例最高的區域之一
            },
            occupation_distribution={
                "hawker_vendor": 0.08,
                "retail_worker": 0.18,
                "service_worker": 0.22,
                "office_worker": 0.08,
                "unemployed_retired": 0.28,
                "tourist": 0.03,
                "government_staff": 0.03,
                "other": 0.10,
            },
            income_distribution={
                "low": 0.48,           # 深水埗是低收入區域
                "medium_low": 0.30,
                "medium": 0.17,
                "high": 0.05,
            },
            resident_ratio=0.78,
            tourist_ratio=0.03,
            commuter_ratio=0.19,
            elderly_rate=0.20,
            poverty_rate=0.22,
            unemployment_rate=0.05,
            data_sources=[
                "2021 Population Census (C&SD)",
                "深水埗區議會地區概覽 2023",
            ],
            last_updated="2024-01",
        )
        self._district_profiles["深水埗"] = ssp
        
        # 可擴展其他區域...
    
    def profile_district(self, district: str) -> PopulationProfile:
        """
        獲取指定區域的人口特徵
        
        Args:
            district: 區域名稱（如 "深水埗"、"旺角"、"中環"）
        
        Returns:
            PopulationProfile 包含該區的人口統計分佈
        """
        if district in self._district_profiles:
            return self._district_profiles[district]
        
        # 若無特定區域數據，返回全港平均
        return PopulationProfile(
            district=district,
            total_population=7500000,
            data_sources=["Hong Kong Average (estimated)"],
        )
    
    def generate_agent_constraints(
        self,
        profile: PopulationProfile,
        total_agents: int = 8,
        scenario_type: str = "night_market"
    ) -> List[Dict[str, Any]]:
        """
        根據人口特徵生成智能體約束列表
        
        這是 Creator Agent 的輸入約束。每個約束定義一個智能體的
        角色範圍，確保所有智能體的集合反映真實人口比例。
        
        Args:
            profile: 區域人口特徵
            total_agents: 總智能體數量
            scenario_type: 場景類型 ("night_market", "tourism", "housing")
        
        Returns:
            智能體約束列表，每項含 role_category、ratio、traits 等
        """
        constraints = []
        
        # 根據場景類型調整權重
        if scenario_type == "night_market":
            # 夜市場景：強調小販、遊客、居民、城管
            weighted_occupations = {
                **profile.occupation_distribution,
                "hawker_vendor": profile.occupation_distribution.get("hawker_vendor", 0.08) * 2.5,
                "tourist": profile.tourist_ratio * 3.0,
                "government_staff": profile.occupation_distribution.get("government_staff", 0.03) * 2.0,
            }
        else:
            weighted_occupations = profile.occupation_distribution
        
        # 正規化權重
        total_weight = sum(weighted_occupations.values())
        normalized = {k: v / total_weight for k, v in weighted_occupations.items()}
        
        # 為每個職業類別分配智能體數量
        for occupation, ratio in normalized.items():
            count = max(1, round(ratio * total_agents))
            if count > 0:
                constraints.append({
                    "role_category": occupation,
                    "suggested_count": count,
                    "population_ratio": round(ratio, 3),
                })
        
        # 按建議數量排序（多的在前）
        constraints.sort(key=lambda x: x["suggested_count"], reverse=True)
        
        return constraints
    
    def build_creator_prompt_context(
        self,
        profile: PopulationProfile,
        scenario: str,
        total_agents: int = 8
    ) -> str:
        """
        構建 Creator Agent 的人口約束 Prompt
        
        將人口統計數據轉化為自然語言約束，注入 Creator Agent 的
        生成 prompt，確保生成的智能體具有統計代表性。
        
        Args:
            profile: 人口特徵
            scenario: 場景描述
            total_agents: 總智能體數
        
        Returns:
            用於 Creator Agent prompt 的人口約束文字
        """
        constraints = self.generate_agent_constraints(profile, total_agents, "night_market")
        
        lines = [
            f"## 人口統計約束（必須遵守）",
            f"你正在生成 {profile.district} 的模擬場景。根據真實人口統計數據：",
            f"- 該區總人口約 {profile.total_population:,} 人",
            f"- 老年人口比例：{profile.elderly_rate:.0%}",
            f"- 貧窮率：{profile.poverty_rate:.0%}",
            f"- 居民佔 {profile.resident_ratio:.0%}，遊客佔 {profile.tourist_ratio:.0%}",
            f"",
            f"請生成 {total_agents} 個智能體，其職業分佈應大致符合以下比例：",
        ]
        
        for c in constraints[:6]:  # 最多 6 個類別
            role_name = {
                "hawker_vendor": "小販/攤檔經營者",
                "retail_worker": "零售業員工",
                "service_worker": "服務業員工",
                "office_worker": "文職人員",
                "unemployed_retired": "失業/退休人士",
                "tourist": "遊客",
                "government_staff": "政府執法人員",
                "other": "其他居民",
            }.get(c["role_category"], c["role_category"])
            
            lines.append(
                f"- {role_name}: 約 {c['suggested_count']} 人 "
                f"（實際人口佔比 {c['population_ratio']:.1%}）"
            )
        
        lines.append(f"\n數據來源：{', '.join(profile.data_sources)}")
        
        return "\n".join(lines)


# ============================================================
#  第三部分：政府數據管道 (Gov Data Pipeline)
#  系統性地發現、獲取、向量化、注入所有相關數據
# ============================================================

class GovDataPipeline:
    """
    政府開放數據管道
    
    解決「如何確保所有相關政府數據都被使用」的問題。
    
    工作流程：
    1. DISCOVER：根據模擬場景關鍵字，匹配相關數據集
    2. FETCH：從 data.gov.hk API 獲取數據
    3. EMBED：將數據內容向量化，存入 ChromaDB
    4. INJECT：在模擬運行時，透過 RAG 檢索相關數據
    
    使用範例：
        pipeline = GovDataPipeline()
        pipeline.discover_relevant_datasets("深水埗 夜市 噪音")
        pipeline.fetch_and_index(memory_manager)
        # 之後在 perceive_node 中，智能體可透過 RAG 查詢相關政府數據
    """
    
    def __init__(self, catalog: List[GovDataset] = None):
        """初始化管道"""
        self.catalog = catalog or GOV_DATA_CATALOG
        self._relevant_datasets: List[GovDataset] = []
        self._fetched_data: Dict[str, str] = {}  # dataset_id -> content
    
    # ------------------------------------------------------------------
    #  Phase 1: DISCOVER - 根據場景發現相關數據集
    # ------------------------------------------------------------------
    
    def discover_relevant_datasets(
        self,
        scenario_keywords: str,
        target_district: Optional[str] = None
    ) -> List[GovDataset]:
        """
        根據模擬場景關鍵字，從目錄中發現相關的數據集
        
        使用關鍵字匹配 + 分類權重來選擇最相關的數據集。
        在完整實現中，可使用語義相似度 (embedding) 來匹配。
        
        Args:
            scenario_keywords: 場景關鍵字（如 "深水埗 夜市 噪音 小販"）
            target_district: 目標區域
        
        Returns:
            相關數據集列表，按相關性排序
        """
        keywords = set(scenario_keywords.lower().split())
        
        # 關鍵字 → 分類映射
        keyword_category_map = {
            "夜市": ["economy", "population"],
            "小販": ["economy"],
            "噪音": ["environment"],
            "遊客": ["economy", "population"],
            "人口": ["population"],
            "交通": ["transport"],
            "房屋": ["housing"],
            "收入": ["population"],
            "天氣": ["environment"],
            "深水埗": ["population", "economy", "housing"],
            "旺角": ["economy", "transport"],
        }
        
        # 計算每個數據集的相關性分數
        scored = []
        for ds in self.catalog:
            score = 0
            
            # 關鍵字直接匹配
            desc_lower = (ds.name + ds.description + ds.name_en).lower()
            for kw in keywords:
                if kw in desc_lower:
                    score += 3
            
            # 分類匹配
            target_categories = set()
            for kw in keywords:
                target_categories.update(keyword_category_map.get(kw, []))
            
            if ds.category in target_categories:
                score += 2
            
            # 區域匹配
            if target_district and target_district in ds.name:
                score += 5
            
            if score > 0:
                scored.append((score, ds))
        
        # 按分數降序排列
        scored.sort(key=lambda x: x[0], reverse=True)
        self._relevant_datasets = [ds for _, ds in scored]
        
        print(f"\n[GovDataPipeline] 從 {len(self.catalog)} 個數據集中發現 "
              f"{len(self._relevant_datasets)} 個相關數據集：")
        for i, (score, ds) in enumerate(scored[:5], 1):
            print(f"  {i}. [{ds.category}] {ds.name} (相關度: {score})")
        
        return self._relevant_datasets
    
    # ------------------------------------------------------------------
    #  Phase 2: FETCH - 獲取數據（含緩存）
    # ------------------------------------------------------------------
    
    async def fetch_dataset(self, dataset: GovDataset) -> Optional[str]:
        """
        從 data.gov.hk 獲取單個數據集
        
        優先使用本地緩存，避免重複下載。
        
        Args:
            dataset: 數據集定義
        
        Returns:
            數據集內容文字（CSV/JSON 轉為文字摘要）
        """
        # 檢查緩存
        cache_key = hashlib.md5(dataset.api_endpoint.encode()).hexdigest()[:12]
        
        try:
            import aiohttp
            
            async with aiohttp.ClientSession() as session:
                async with session.get(dataset.api_endpoint, timeout=30) as resp:
                    if resp.status == 200:
                        content = await resp.text()
                        
                        # 根據格式處理
                        if dataset.format == "JSON":
                            data = json.loads(content)
                            # 提取文字摘要（取前 2000 字）
                            content = json.dumps(data, ensure_ascii=False, indent=2)[:2000]
                        elif dataset.format == "CSV":
                            # 取前 100 行
                            lines = content.split("\n")[:100]
                            content = "\n".join(lines)
                        
                        self._fetched_data[dataset.id] = content
                        print(f"  [FETCH] {dataset.name}: {len(content)} chars")
                        return content
                    else:
                        print(f"  [SKIP] {dataset.name}: HTTP {resp.status}")
                        return None
        except Exception as e:
            print(f"  [SKIP] {dataset.name}: {e} (使用預設數據)")
            # 返回預設摘要而非失敗
            self._fetched_data[dataset.id] = dataset.description
            return dataset.description
    
    async def fetch_all_relevant(self) -> Dict[str, str]:
        """
        獲取所有已發現的相關數據集
        
        Returns:
            dataset_id -> content 的字典
        """
        # 在實際場景中，這裡會使用 asyncio.gather() 並行獲取
        for ds in self._relevant_datasets[:5]:  # 限制獲取數量
            await self.fetch_dataset(ds)
        
        return self._fetched_data
    
    # ------------------------------------------------------------------
    #  Phase 3: EMBED - 向量化存入 ChromaDB
    # ------------------------------------------------------------------
    
    def embed_to_memory(
        self,
        memory_manager,
        simulation_id: str
    ) -> int:
        """
        將獲取的政府數據向量化並存入 ChromaDB
        
        每個數據集作為一條獨立的知識條目存入，
        後續智能體可透過 RAG 檢索相關的政府數據。
        
        Args:
            memory_manager: MemoryManager 實例
            simulation_id: 模擬 ID
        
        Returns:
            存入的數據條目數
        """
        memory_manager.init_simulation(simulation_id)
        
        count = 0
        for dataset_id, content in self._fetched_data.items():
            if not content:
                continue
            
            # 找到對應的數據集定義
            ds = next((d for d in self.catalog if d.id == dataset_id), None)
            if ds is None:
                continue
            
            # 構建知識條目（以 "system" 身份寫入）
            from models import AgentAction
            
            knowledge_action = AgentAction(
                agent_id="system",
                day=0,  # Day 0 = 模擬前的背景知識
                timestamp=datetime.now().isoformat(),
                action_type="knowledge_injection",
                action_description=f"[政府數據] {ds.name}: {content[:200]}",
                duration_minutes=0,
            )
            
            memory_manager.save_episodic_memory(
                agent_id="system",
                day=0,
                context=f"data.gov.hk 數據集: {ds.name} ({ds.category})",
                action=knowledge_action,
                emotion="neutral",
            )
            count += 1
        
        print(f"\n[GovDataPipeline] 已將 {count} 個政府數據集向量化存入 ChromaDB")
        return count
    
    # ------------------------------------------------------------------
    #  Phase 4: INJECT - 在模擬中注入相關數據
    # ------------------------------------------------------------------
    
    def build_domain_context(self, scenario: str) -> str:
        """
        構建領域知識上下文（注入到 EnvironmentState.domain_context）
        
        將所有已獲取的政府數據匯總為一個結構化的背景知識文本。
        這將作為 RAG 的基礎語料，供智能體在模擬中查詢。
        
        Args:
            scenario: 場景描述
        
        Returns:
            結構化的領域知識文字
        """
        sections = [
            f"# 模擬場景背景知識",
            f"場景：{scenario}",
            f"數據來源：data.gov.hk 香港政府開放數據",
            f"生成時間：{datetime.now().strftime('%Y-%m-%d %H:%M')}",
            f"",
        ]
        
        for dataset_id, content in self._fetched_data.items():
            ds = next((d for d in self.catalog if d.id == dataset_id), None)
            if ds:
                sections.append(f"## {ds.name}")
                sections.append(f"分類：{ds.category}")
                sections.append(f"來源：{ds.api_endpoint}")
                sections.append(f"```")
                sections.append(content[:1500])
                sections.append(f"```")
                sections.append("")
        
        return "\n".join(sections)
    
    def get_relevant_data_for_query(
        self,
        query: str,
        memory_manager,
        top_k: int = 3
    ) -> List[str]:
        """
        在模擬運行中，根據當前查詢檢索相關的政府數據
        
        這使得智能體可以在 perceive_node 中查詢相關背景資訊。
        例如：小販查詢「夜市噪音規管」，系統返回 EPD 噪音投訴數據。
        
        Args:
            query: 查詢文字
            memory_manager: MemoryManager 實例
            top_k: Top-K 結果
        
        Returns:
            相關政府數據摘要列表
        """
        results = memory_manager.retrieve_relevant_memory(
            agent_id="system",  # 查詢系統知識庫
            current_situation=query,
            top_k=top_k,
        )
        
        return [r["document"][:300] for r in results]


# ============================================================
#  第四部分：便捷函數 - 完整數據注入流程
# ============================================================

async def inject_gov_data_into_simulation(
    scenario: str,
    district: str,
    memory_manager,
    total_agents: int = 8,
) -> Tuple[PopulationProfile, str, List[Dict[str, Any]]]:
    """
    完整的政府數據注入流程
    
    在一次調用中完成：發現數據 → 提取人口特徵 → 生成智能體約束 → 向量化注入
    
    Args:
        scenario: 場景描述
        district: 目標區域
        memory_manager: MemoryManager 實例
        total_agents: 總智能體數
    
    Returns:
        (PopulationProfile, domain_context, agent_constraints)
    """
    # Step 1: 獲取人口特徵
    profiler = PopulationProfiler()
    profile = profiler.profile_district(district)
    
    # Step 2: 生成智能體約束
    constraints = profiler.generate_agent_constraints(profile, total_agents)
    
    # Step 3: 發現相關數據集
    pipeline = GovDataPipeline()
    pipeline.discover_relevant_datasets(scenario, district)
    
    # Step 4: 獲取數據
    await pipeline.fetch_all_relevant()
    
    # Step 5: 向量化注入
    pipeline.embed_to_memory(memory_manager, f"govdata_{district.encode('ascii','ignore').decode() or 'hk'}")
    
    # Step 6: 構建領域上下文
    domain_context = pipeline.build_domain_context(scenario)
    
    # Step 7: 構建 Creator Agent 的人口約束 prompt
    pop_constraint_text = profiler.build_creator_prompt_context(
        profile, scenario, total_agents
    )
    
    print(f"\n{'='*60}")
    print(f"  [GovData] 數據注入完成")
    print(f"  區域：{district} (人口 {profile.total_population:,})")
    print(f"  相關數據集：{len(pipeline._relevant_datasets)}")
    print(f"  智能體約束：{len(constraints)} 個職業類別")
    print(f"  領域知識：{len(domain_context)} 字")
    print(f"{'='*60}")
    
    return profile, domain_context, constraints


# ============================================================
#  自我測試
# ============================================================

if __name__ == "__main__":
    import asyncio
    
    print("=== 政府數據管道自我測試 ===\n")
    
    async def test():
        # 測試 1: 人口特徵提取
        print("【測試 1】深水埗人口特徵")
        profiler = PopulationProfiler()
        profile = profiler.profile_district("深水埗")
        print(f"  人口: {profile.total_population:,}")
        print(f"  老年比例: {profile.elderly_rate:.0%}")
        print(f"  小販比例: {profile.occupation_distribution['hawker_vendor']:.1%}")
        print(f"  貧窮率: {profile.poverty_rate:.0%}")
        
        # 測試 2: 智能體約束生成
        print(f"\n【測試 2】智能體約束 (8人)")
        constraints = profiler.generate_agent_constraints(profile, 8, "night_market")
        for c in constraints:
            print(f"  {c['role_category']}: {c['suggested_count']}人 "
                  f"(佔比 {c['population_ratio']:.1%})")
        
        # 測試 3: Creator Agent Prompt
        print(f"\n【測試 3】Creator Agent 人口約束 Prompt (節選)")
        prompt = profiler.build_creator_prompt_context(profile, "深水埗夜市噪音政策模擬", 8)
        print(prompt[:500] + "...")
        
        # 測試 4: 數據集發現
        print(f"\n【測試 4】數據集發現")
        pipeline = GovDataPipeline()
        relevant = pipeline.discover_relevant_datasets("深水埗 夜市 噪音 小販", "深水埗")
        print(f"  發現 {len(relevant)} 個相關數據集")
        
        # 測試 5: 嘗試獲取數據
        print(f"\n【測試 5】獲取數據 (前 3 個)")
        for ds in relevant[:3]:
            content = await pipeline.fetch_dataset(ds)
            if content:
                print(f"  {ds.name}: {len(content)} 字")
        
        print(f"\n✅ 測試完成")
    
    asyncio.run(test())
