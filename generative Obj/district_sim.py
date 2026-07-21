"""
============================================================
  18區日夜都繽紛 — 全港 18 區批量模擬系統
  基於 2021 年人口普查真實數據
============================================================
"""

import asyncio, sys, json, os
from datetime import datetime

if sys.platform == "win32":
    try: sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except: pass

from models import *

# 區域名 → ChromaDB-safe ID
_DISTRICT_EN = {"中西區":"cw","灣仔":"wc","東區":"east","南區":"south","油尖旺":"ytm","深水埗":"ssp","九龍城":"kc","黃大仙":"wts","觀塘":"kt","荃灣":"tw","屯門":"tm","元朗":"yl","北區":"north","大埔":"tp","沙田":"st","西貢":"sk","葵青":"kc","離島":"islands"}
def _eng(name): return _DISTRICT_EN.get(name, name)

def _detect_scenario(district, features):
    text = features + district
    scores = {"night_market":0,"tourism":0,"traffic":0,"housing":0}
    for k in ["夜市","小販","排檔","市集","美食","酒吧","廟街","蘭桂坊"]:
        if k in text: scores["night_market"]+=1
    for k in ["旅遊","遊客","景點","海灘","離島","度假","酒店"]:
        if k in text: scores["tourism"]+=1
    for k in ["交通","塞車","跨境","邊境","碼頭","隧道","巴士"]:
        if k in text: scores["traffic"]+=1
    for k in ["公屋","居屋","房屋","租金","樓價","劏房"]:
        if k in text: scores["housing"]+=1
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "night_market"

_DIST_SUR = {"中西區":["陳","李","張","黃","何"],"灣仔":["陳","李","張","劉","周"],"東區":["陳","李","張","黃","林"],"南區":["陳","李","張","吳","郭"],"油尖旺":["陳","李","劉","王","楊"],"深水埗":["陳","李","黃","林","何"],"九龍城":["陳","李","黃","林","蔡"],"黃大仙":["陳","李","黃","林","梁"],"觀塘":["陳","李","黃","林","吳"],"荃灣":["陳","李","黃","林","周"],"屯門":["陳","李","黃","林","廖"],"元朗":["陳","李","黃","鄧","文"],"北區":["陳","李","黃","林","廖"],"大埔":["陳","李","黃","林","蘇"],"沙田":["陳","李","黃","林","鄭"],"西貢":["陳","李","黃","林","許"],"葵青":["陳","李","黃","林","譚"],"離島":["陳","李","黃","林","周"]}
_SUF = ["伯","叔","哥","姐","太","生","小姐","姨","師傅","老闆"]
from engine import create_deepseek_llm, run_simulation
from memory_manager import create_memory_manager
from tools import create_default_tool_registry

# ══════════════════════════════════════════════════════════
#  18 區真實人口數據 (2021 人口普查)
#  格式: {年齡分佈, 收入中位數(HKD), 人口, 職業特徵}
# ══════════════════════════════════════════════════════════

DISTRICTS = {
    "中西區": {
        "pop": 236000, "income_median": 42000,
        "age": {"youth": 0.12, "young": 0.22, "mid": 0.34, "elderly": 0.32},
        "occ": {"hawker": 0.01, "retail": 0.10, "service": 0.18, "office": 0.35, "unemployed": 0.20, "tourist": 0.08, "gov": 0.05, "other": 0.03},
        "income": {"low": 0.15, "med_low": 0.20, "med": 0.35, "high": 0.30},
        "features": "金融核心區，半山豪宅與蘇豪夜生活並存，日夜都繽紛活動集中於海濱與蘭桂坊",
    },
    "灣仔": {
        "pop": 170000, "income_median": 40000,
        "age": {"youth": 0.11, "young": 0.23, "mid": 0.35, "elderly": 0.31},
        "occ": {"hawker": 0.01, "retail": 0.08, "service": 0.20, "office": 0.38, "unemployed": 0.18, "tourist": 0.10, "gov": 0.04, "other": 0.01},
        "income": {"low": 0.18, "med_low": 0.22, "med": 0.33, "high": 0.27},
        "features": "商業與娛樂混合，利東街、灣仔海濱、會展一帶為主要場地，日夜都繽紛於海濱長廊辦市集",
    },
    "東區": {
        "pop": 530000, "income_median": 30000,
        "age": {"youth": 0.14, "young": 0.19, "mid": 0.33, "elderly": 0.34},
        "occ": {"hawker": 0.03, "retail": 0.14, "service": 0.22, "office": 0.22, "unemployed": 0.25, "tourist": 0.02, "gov": 0.04, "other": 0.08},
        "income": {"low": 0.30, "med_low": 0.30, "med": 0.25, "high": 0.15},
        "features": "住宅為主，太古城、筲箕灣東大街、鯉魚門海鮮，日夜都繽紛曾辦閃耀東區夜飛龍(120萬撥款)",
    },
    "南區": {
        "pop": 260000, "income_median": 32000,
        "age": {"youth": 0.12, "young": 0.18, "mid": 0.34, "elderly": 0.36},
        "occ": {"hawker": 0.02, "retail": 0.12, "service": 0.22, "office": 0.18, "unemployed": 0.28, "tourist": 0.06, "gov": 0.03, "other": 0.09},
        "income": {"low": 0.28, "med_low": 0.32, "med": 0.25, "high": 0.15},
        "features": "香港仔避風塘、淺水灣、赤柱，日夜都繽紛集中於海濱市集與漁港文化活動",
    },
    "油尖旺": {
        "pop": 310000, "income_median": 25000,
        "age": {"youth": 0.13, "young": 0.22, "mid": 0.33, "elderly": 0.32},
        "occ": {"hawker": 0.06, "retail": 0.20, "service": 0.25, "office": 0.12, "unemployed": 0.22, "tourist": 0.10, "gov": 0.03, "other": 0.02},
        "income": {"low": 0.38, "med_low": 0.28, "med": 0.22, "high": 0.12},
        "features": "廟街夜市、女人街、花墟、天星碼頭，日夜都繽紛核心戰區，廟街熄咪事件發源地",
    },
    "深水埗": {
        "pop": 431000, "income_median": 24000,
        "age": {"youth": 0.10, "young": 0.18, "mid": 0.32, "elderly": 0.40},
        "occ": {"hawker": 0.08, "retail": 0.18, "service": 0.22, "office": 0.08, "unemployed": 0.28, "tourist": 0.03, "gov": 0.03, "other": 0.10},
        "income": {"low": 0.48, "med_low": 0.30, "med": 0.17, "high": 0.05},
        "features": "全港最基層社區，電腦商場+鴨寮街+桂林街夜市，光劍攻殼→深啡咖啡市集的士紳化案例",
    },
    "九龍城": {
        "pop": 410000, "income_median": 28000,
        "age": {"youth": 0.13, "young": 0.20, "mid": 0.34, "elderly": 0.33},
        "occ": {"hawker": 0.04, "retail": 0.15, "service": 0.23, "office": 0.18, "unemployed": 0.24, "tourist": 0.04, "gov": 0.04, "other": 0.08},
        "income": {"low": 0.32, "med_low": 0.30, "med": 0.23, "high": 0.15},
        "features": "啟德新區+九龍城寨舊區，潑水泰繽紛拖數71萬事件，MatchLive外判商醜聞",
    },
    "黃大仙": {
        "pop": 410000, "income_median": 24000,
        "age": {"youth": 0.11, "young": 0.17, "mid": 0.32, "elderly": 0.40},
        "occ": {"hawker": 0.03, "retail": 0.12, "service": 0.22, "office": 0.10, "unemployed": 0.32, "tourist": 0.02, "gov": 0.04, "other": 0.15},
        "income": {"low": 0.45, "med_low": 0.30, "med": 0.18, "high": 0.07},
        "features": "公共屋邨集中區，黃大仙祠吸引遊客，日夜都繽紛活動規模較小",
    },
    "觀塘": {
        "pop": 670000, "income_median": 25000,
        "age": {"youth": 0.12, "young": 0.19, "mid": 0.34, "elderly": 0.35},
        "occ": {"hawker": 0.04, "retail": 0.14, "service": 0.23, "office": 0.15, "unemployed": 0.28, "tourist": 0.02, "gov": 0.04, "other": 0.10},
        "income": {"low": 0.38, "med_low": 0.32, "med": 0.20, "high": 0.10},
        "features": "全港人口最多區域，觀塘海濱、裕民坊重建，日夜都繽紛海濱市集23日錄80萬人次",
    },
    "葵青": {
        "pop": 500000, "income_median": 23000,
        "age": {"youth": 0.12, "young": 0.18, "mid": 0.33, "elderly": 0.37},
        "occ": {"hawker": 0.03, "retail": 0.12, "service": 0.22, "office": 0.10, "unemployed": 0.30, "tourist": 0.01, "gov": 0.04, "other": 0.18},
        "income": {"low": 0.45, "med_low": 0.32, "med": 0.16, "high": 0.07},
        "features": "貨櫃碼頭+工業區轉型，青衣海濱，日夜都繽紛活動以社區嘉年華為主",
    },
    "荃灣": {
        "pop": 310000, "income_median": 28000,
        "age": {"youth": 0.13, "young": 0.20, "mid": 0.34, "elderly": 0.33},
        "occ": {"hawker": 0.04, "retail": 0.15, "service": 0.22, "office": 0.16, "unemployed": 0.24, "tourist": 0.03, "gov": 0.04, "other": 0.12},
        "income": {"low": 0.32, "med_low": 0.32, "med": 0.22, "high": 0.14},
        "features": "新界西商業中心，荃灣海濱+南豐紗廠文創，日夜都繽紛活動集中海濱",
    },
    "屯門": {
        "pop": 500000, "income_median": 23000,
        "age": {"youth": 0.15, "young": 0.19, "mid": 0.33, "elderly": 0.33},
        "occ": {"hawker": 0.03, "retail": 0.12, "service": 0.20, "office": 0.10, "unemployed": 0.30, "tourist": 0.01, "gov": 0.05, "other": 0.19},
        "income": {"low": 0.42, "med_low": 0.32, "med": 0.18, "high": 0.08},
        "features": "新界西北衛星城市，夜屯園三項目合共207萬撥款，日夜都繽紛重點區",
    },
    "元朗": {
        "pop": 640000, "income_median": 24000,
        "age": {"youth": 0.14, "young": 0.19, "mid": 0.34, "elderly": 0.33},
        "occ": {"hawker": 0.05, "retail": 0.14, "service": 0.22, "office": 0.10, "unemployed": 0.28, "tourist": 0.02, "gov": 0.04, "other": 0.15},
        "income": {"low": 0.40, "med_low": 0.30, "med": 0.20, "high": 0.10},
        "features": "大馬路夜市、元朗廣場、YOHO Mall，城鄉交界的日夜都繽紛案例",
    },
    "北區": {
        "pop": 310000, "income_median": 22000,
        "age": {"youth": 0.13, "young": 0.19, "mid": 0.34, "elderly": 0.34},
        "occ": {"hawker": 0.04, "retail": 0.11, "service": 0.21, "office": 0.08, "unemployed": 0.30, "tourist": 0.03, "gov": 0.05, "other": 0.18},
        "income": {"low": 0.45, "med_low": 0.30, "med": 0.17, "high": 0.08},
        "features": "邊境區域，上水石湖墟、粉嶺聯和墟，跨境消費影響區",
    },
    "大埔": {
        "pop": 310000, "income_median": 28000,
        "age": {"youth": 0.14, "young": 0.19, "mid": 0.34, "elderly": 0.33},
        "occ": {"hawker": 0.03, "retail": 0.13, "service": 0.21, "office": 0.15, "unemployed": 0.26, "tourist": 0.04, "gov": 0.04, "other": 0.14},
        "income": {"low": 0.32, "med_low": 0.32, "med": 0.22, "high": 0.14},
        "features": "大埔墟夜市、林村河畔、海濱公園，日夜都繽紛中型活動區",
    },
    "沙田": {
        "pop": 690000, "income_median": 31000,
        "age": {"youth": 0.14, "young": 0.20, "mid": 0.35, "elderly": 0.31},
        "occ": {"hawker": 0.02, "retail": 0.12, "service": 0.20, "office": 0.22, "unemployed": 0.22, "tourist": 0.05, "gov": 0.05, "other": 0.12},
        "income": {"low": 0.25, "med_low": 0.30, "med": 0.28, "high": 0.17},
        "features": "全港人口第二大區，新城市廣場+城門河，日夜都繽紛活動規模中等",
    },
    "西貢": {
        "pop": 480000, "income_median": 33000,
        "age": {"youth": 0.15, "young": 0.21, "mid": 0.35, "elderly": 0.29},
        "occ": {"hawker": 0.02, "retail": 0.10, "service": 0.20, "office": 0.22, "unemployed": 0.20, "tourist": 0.10, "gov": 0.05, "other": 0.11},
        "income": {"low": 0.22, "med_low": 0.28, "med": 0.30, "high": 0.20},
        "features": "將軍澳新市鎮+西貢海鮮街，海濱活動與社區市集",
    },
    "離島": {
        "pop": 180000, "income_median": 25000,
        "age": {"youth": 0.13, "young": 0.20, "mid": 0.34, "elderly": 0.33},
        "occ": {"hawker": 0.05, "retail": 0.10, "service": 0.25, "office": 0.10, "unemployed": 0.25, "tourist": 0.15, "gov": 0.04, "other": 0.06},
        "income": {"low": 0.35, "med_low": 0.30, "med": 0.22, "high": 0.13},
        "features": "大嶼山+長洲+南丫島，旅遊導向，日夜都繽紛分散各島",
    },
}


def build_district_config(district_name: str, max_days: int = 14, agents_count: int = 12) -> SimulationConfig:
    """根據真實人口數據為任一區域生成模擬配置"""
    d = DISTRICTS.get(district_name)
    if not d:
        raise ValueError(f"未知區域: {district_name}")
    
    sim_id = f"18d_{_eng(district_name)}_{datetime.now().strftime('%Y%m%d_%H%M')}"
    
    # 從人口數據推導智能體
    agents = _generate_agents(district_name, d, agents_count)
    
    # Metric baselines adjusted per district
    noise_baseline = 55 if d["income_median"] < 28000 else 50  # 基層區較吵
    crowd_baseline = 1.5 if d["pop"] > 500000 else 1.0
    vendor_revenue = d["income_median"] * 0.08  # 約為中位數8%
    
    metrics = {
        "noise_db": Metric(id="noise_db", name="噪音水平", unit="dB(A)",
            real_min=30, real_max=100, baseline=noise_baseline,
            data_source="EPD各區噪音投訴統計", higher_is_better=False),
        "crowd_density": Metric(id="crowd_density", name="人群密度", unit="人/m²",
            real_min=0, real_max=5, baseline=crowd_baseline,
            data_source="運輸署行人流量", higher_is_better=False),
        "vendor_daily_revenue": Metric(id="vendor_daily_revenue", name="小販日收入", unit="HKD/天",
            real_min=0, real_max=15000, baseline=vendor_revenue,
            data_source="C&SD零售業統計", higher_is_better=True),
        "complaint_count": Metric(id="complaint_count", name="投訴量", unit="件/天",
            real_min=0, real_max=30, baseline=3,
            data_source="EPD分區投訴", higher_is_better=False),
        "resident_satisfaction": Metric(id="resident_satisfaction", name="居民滿意度", unit="%",
            real_min=0, real_max=100, baseline=55,
            data_source="區議會民意", higher_is_better=True),
        "tourist_count": Metric(id="tourist_count", name="遊客量", unit="人/晚",
            real_min=0, real_max=5000, baseline=int(d["pop"] * 0.002),
            data_source="旅發局統計", higher_is_better=True),
        "policy_tightness": Metric(id="policy_tightness", name="執法巡查", unit="次/天",
            real_min=0, real_max=15, baseline=2,
            data_source="食環署年報", higher_is_better=False),
    }
    
    scenario_type = _detect_scenario(district_name, d["features"])
    
    env = EnvironmentState(
        day=1, date="2026-03-08",
        noise_level=0.5, crowd_density=0.4, economic_activity=0.4,
        social_stability=0.6, policy_pressure=0.3,
        domain_context=d["features"],
        metric_definitions={mid: m.model_dump() for mid, m in metrics.items()},
        metrics={mid: m.baseline for mid, m in metrics.items()},
    )
    
    return SimulationConfig(
        simulation_id=sim_id,
        title=f"「18區日夜都繽紛」— {district_name}區社會動態模擬",
        description=f"{d['features']}。家庭月入中位數HK${d['income_median']:,}，人口{d['pop']:,}。",
        max_days=max_days, start_date="2026-03-08",
        scenario_type=scenario_type,
        active_metrics=list(metrics.keys()),
        agents=agents,
        global_tools=["check_weather", "post_complaint"],
    )


def _generate_agents(district: str, d: dict, count: int) -> list:
    """根據人口特徵生成智能體（含 LLM 個性化背景）"""
    surnames = _DIST_SUR.get(district, ["陳","李","張","黃","林"])
    features = d.get("features", "")
    income = d.get("income_median", 25000)
    
    # 嘗試用 LLM 生成區專屬背景（若失敗則 fallback 到模板）
    llm_bg = _try_llm_backgrounds(district, features, income, count)
    
    roles = ["小販","居民(長者)","居民(家庭)","零售店員","食肆員工","區議員","食環署巡查","商場經理","遊客","NGO社工"]
    tools_pool = [["post_complaint"],["post_complaint"],["post_complaint"],["check_weather"],["check_weather"],["check_weather","post_complaint"],["post_complaint"],["check_weather"],["check_weather"],["post_complaint"]]
    emotions = [EmotionState.ANXIOUS,EmotionState.ANGRY,EmotionState.NEUTRAL,EmotionState.NEUTRAL,EmotionState.NEUTRAL,EmotionState.NEUTRAL,EmotionState.NEUTRAL,EmotionState.NEUTRAL,EmotionState.EXCITED,EmotionState.ANGRY]
    
    agents = []
    for i in range(count):
        s = surnames[i % len(surnames)]
        suf = _SUF[i % len(_SUF)]
        name = f"{s}{suf}"
        r_idx = i % len(roles)
        bg = llm_bg[i] if i < len(llm_bg) else f"{district}{roles[r_idx]}，受日夜都繽紛政策影響。{features[:50]}"
        agents.append(AgentPersona(
            agent_id=f"agent_{_eng(district)}_{i+1:02d}",
            name=name, role=roles[r_idx],
            background=bg,
            core_motivation="在日夜都繽紛政策變化中維護自身利益與生活品質",
            personality_traits=["務實","關注社區"],
            available_tools=tools_pool[r_idx],
            initial_emotion=emotions[r_idx],
            action_thresholds=ActionThreshold(noise_tolerance=0.5),
        ))
    return agents

def _try_llm_backgrounds(district, features, income, count):
    """用 LLM 生成區專屬背景，失敗則返回空列表"""
    try:
        from engine import create_deepseek_llm
        from langchain_core.messages import HumanMessage
        llm = create_deepseek_llm(temperature=0.8)
        prompt = f"""為香港{district}區的日夜都繽紛政策模擬，生成{min(count,6)}個智能體的專屬背景。
區特徵：{features}
家庭月入中位數：HK${income:,}

每個智能體需有角色和具體背景故事（繁體中文，每段30-50字），要包含真實的區域名稱和具體數字。
輸出JSON array: ["背景1", "背景2", ...]
只輸出JSON，不要其他文字。"""
        resp = llm.invoke([HumanMessage(content=prompt)])
        txt = resp.content.strip()
        s = txt.find('[')
        e = txt.rfind(']')
        if s >= 0 and e > s:
            import json
            bgs = json.loads(txt[s:e+1])
            return [str(b) for b in bgs[:count]]
    except Exception:
        pass
    return []
async def run_district(district_name: str, days: int = 5, agents: int = 6):
    """執行單一區域模擬（快速版）"""
    print(f"\n{'='*60}")
    print(f"  {district_name} — 日夜都繽紛模擬 ({agents}人 × {days}天)")
    print(f"{'='*60}")
    
    config = build_district_config(district_name, days, agents)
    config.init_metrics()
    
    llm = create_deepseek_llm(temperature=0.7)
    tool_registry = create_default_tool_registry()
    memory_manager = create_memory_manager()
    memory_manager.init_simulation(config.simulation_id)
    
    result = await run_simulation(config, llm, tool_registry, memory_manager)
    
    # 提取最終指標
    env = result.all_day_logs[-1].environment_after if result.all_day_logs else config.initial_environment
    metrics_summary = {}
    for mid in config.active_metrics:
        if mid in env.metrics:
            metrics_summary[mid] = env.metrics[mid]
    
    return {
        "district": district_name,
        "metrics": metrics_summary,
        "summary": result.executive_summary[:300],
    }


async def batch_run(districts: list = None, days: int = 5, agents: int = 6):
    """批量執行多個區域（按順序以避免 API 過載）"""
    if districts is None:
        districts = list(DISTRICTS.keys())
    
    results = {}
    start = datetime.now()
    
    for i, dist in enumerate(districts, 1):
        print(f"\n[{i}/{len(districts)}] 開始: {dist}")
        try:
            results[dist] = await run_district(dist, days, agents)
            print(f"  ✅ {dist} 完成")
        except Exception as e:
            print(f"  ❌ {dist} 失敗: {e}")
            results[dist] = {"district": dist, "error": str(e)}
    
    elapsed = (datetime.now() - start).total_seconds()
    
    # 生成比較報告
    print(f"\n{'='*70}")
    print(f"  18區模擬完成 ({len(results)}區, {elapsed:.0f}秒)")
    print(f"{'='*70}")
    print(f"\n{'區':8s} {'噪音':>6s} {'人群':>6s} {'收入':>8s} {'投訴':>6s} {'滿意':>6s}")
    print(f"{'-'*50}")
    
    for dist_name, r in sorted(results.items()):
        if "error" in r:
            print(f"{dist_name:8s} ❌ {r['error'][:30]}")
            continue
        m = r.get("metrics", {})
        noise = m.get("noise_db", 0)
        crowd = m.get("crowd_density", 0)
        revenue = m.get("vendor_daily_revenue", 0)
        complaints = m.get("complaint_count", 0)
        satisfaction = m.get("resident_satisfaction", 0)
        print(f"{dist_name:8s} {noise:5.0f}dB {crowd:4.1f}/m² ${revenue:5.0f} {complaints:4.0f}件 {satisfaction:4.0f}%")
    
    # 儲存 JSON
    out = {
        "simulated_at": datetime.now().isoformat(),
        "config": {"days": days, "agents_per_district": agents},
        "results": {k: {"metrics": v.get("metrics", {}), "summary": v.get("summary", "")[:200]} 
                     for k, v in results.items()}
    }
    path = f"18districts_results_{datetime.now().strftime('%Y%m%d_%H%M')}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"\n📁 結果已儲存: {path}")
    
    return results


# ── CLI ──
async def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--district", "-d", default=None, help="單一區域名稱")
    p.add_argument("--days", type=int, default=5)
    p.add_argument("--agents", type=int, default=6)
    p.add_argument("--all", action="store_true", help="執行全部18區")
    p.add_argument("--sample", type=int, default=0, help="只跑前N區做測試")
    args = p.parse_args()
    
    if args.district:
        await run_district(args.district, args.days, args.agents)
    elif args.all:
        await batch_run(list(DISTRICTS.keys()), args.days, args.agents)
    elif args.sample > 0:
        await batch_run(list(DISTRICTS.keys())[:args.sample], args.days, args.agents)
    else:
        print("用法:")
        print("  python district_sim.py --district 深水埗     # 單區")
        print("  python district_sim.py --sample 3             # 前3區測試")
        print("  python district_sim.py --all                  # 全部18區(約3小時)")


if __name__ == "__main__":
    asyncio.run(main())
