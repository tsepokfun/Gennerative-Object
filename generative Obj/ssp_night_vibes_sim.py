"""
============================================================
  深水埗日夜都繽紛 — 社會動態模擬
  Sham Shui Po Night Vibes — Social Dynamics Simulation
  
  基於用戶提供的深度研究文件校準
  2026 現況：政策已從街頭夜市退移至海濱「深．啡」咖啡市集
============================================================
"""

import asyncio
import sys, os
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except: pass

from models import *
from engine import create_deepseek_llm, run_simulation
from memory_manager import create_memory_manager
from tools import create_default_tool_registry

# ── 基於研究的真實數據校準 ──

def build_ssp_night_vibes_config() -> SimulationConfig:
    """
    基於研究文件的精確參數校準
    
    數據來源見研究文件 [A]-[F] 各節
    """
    
    # ── Metric 定義：基於研究中的真實數字 ──
    metrics = {
        "noise_db": Metric(
            id="noise_db", name="噪音水平", unit="dB(A)",
            real_min=40, real_max=100, baseline=68,
            description="深水埗夜市噪音。2024年廟街首晚因音響過大被迫熄咪(研究B)。EPD夜間標準55dB。",
            data_source="EPD各區噪音投訴統計; 廟街熄咪事件2024",
            higher_is_better=False,
        ),
        "crowd_density": Metric(
            id="crowd_density", name="人群密度", unit="人/m²",
            real_min=0, real_max=5, baseline=1.8,
            description="光劍攻殼活動時福華街人車爭路(研究B)。桂林街狹窄空間強行塞入大型集會。",
            data_source="運輸署行人流量; 媒體現場報導",
            higher_is_better=False,
        ),
        "vendor_daily_revenue": Metric(
            id="vendor_daily_revenue", name="小販日收入", unit="HKD/天",
            real_min=0, real_max=15000, baseline=1000,
            description="深水埗家庭月入中位數僅HK$24,000(研究C)。小販日入遠低於光劍活動宣稱的1000萬電腦商場消費。",
            data_source="C&SD表130-06806; 研究C",
            higher_is_better=True,
        ),
        "complaint_count": Metric(
            id="complaint_count", name="噪音投訴", unit="件/天",
            real_min=0, real_max=30, baseline=5,
            description="廟街首晚即觸發投訴致表演者熄咪。潑水節移入公園因安全投訴(研究B/D)。",
            data_source="EPD分區投訴; 媒體報導",
            higher_is_better=False,
        ),
        "policy_tightness": Metric(
            id="policy_tightness", name="執法巡查", unit="次/天",
            real_min=0, real_max=15, baseline=3,
            description="食環署在'鼓勵夜市'與'執行衛生條例'之間的兩難(研究D)。外判商拖數71萬後信任崩潰。",
            data_source="食環署年報; MatchLive拖數事件2024",
            higher_is_better=False,
        ),
        "resident_satisfaction": Metric(
            id="resident_satisfaction", name="居民滿意度", unit="%",
            real_min=0, real_max=100, baseline=45,
            description="低收入居民承擔噪音/擁擠成本但未獲益。光劍活動被嘲'無力多過原力'(研究D)。",
            data_source="區議會民意; 網絡輿論分析",
            higher_is_better=True,
        ),
        "tourist_count": Metric(
            id="tourist_count", name="外來人流", unit="人/晚",
            real_min=0, real_max=8000, baseline=1200,
            description="2025年全港旅客4990萬(+12%)。深水埗非傳統旅遊區，靠活動吸引跨區人流。",
            data_source="旅發局2025年報; 研究C",
            higher_is_better=True,
        ),
        "gentrification_index": Metric(
            id="gentrification_index", name="士紳化指數", unit="指數",
            real_min=0, real_max=100, baseline=30,
            description="2024光劍(基層街頭)→2026深啡(海濱精品咖啡+寵物友善)。追蹤活動主題中產化程度。",
            data_source="2026深啡活動分析(研究F); 新鴻基地產慈善基金贊助",
            higher_is_better=False,
        ),
    }
    
    # ── 12 個智能體：基於研究中的真實利害相關者 ──
    
    # 1-2: 小販群體
    hawker_wong = AgentPersona(
        agent_id="hawker_wong",
        name="阿黃", role="熟食小販（魚蛋檔）",
        background="深水埗桂林街持牌固定攤位小販，經營魚蛋檔逾15年。家庭月入約HK$18,000，太太在酒樓做兼職。"
                   "2024年光劍活動期間生意短暫上升30%，但其後因活動移至海濱，人流不再經過其攤位。",
        core_motivation="維持生計，對政府短期注資活動又愛又恨：有人流但怕日後租金上升被逼遷",
        personality_traits=["務實", "警覺", "江湖氣", "對政府不信任"],
        action_thresholds=ActionThreshold(noise_tolerance=0.8, social_interaction_drive=0.9),
        available_tools=["check_weather", "post_complaint"],
        initial_memory="2024年光劍活動嗰陣，生意好咗三成。但之後活動搬咗去海濱，啲客唔再經過我呢度。政府搞嘅嘢，都係一陣風。",
        initial_emotion=EmotionState.ANXIOUS,
    )
    
    hawker_keung = AgentPersona(
        agent_id="hawker_keung",
        name="阿強", role="乾貨小販（手機配件）",
        background="在鴨寮街擺檔賣手機配件10年。深水埗電腦節和光劍活動期間，周邊電腦商場宣稱營業額破千萬，"
                   "但他的路邊攤完全分不到。月入約HK$12,000，兩個孩子在內地讀書。",
        core_motivation="生存。政府活動的紅利永遠流向商場和地產商，路邊小販被邊緣化",
        personality_traits=["憤世嫉俗", "韌性強", "精明"],
        action_thresholds=ActionThreshold(noise_tolerance=0.7, economic_stress_threshold=0.3),
        available_tools=["post_complaint"],
        initial_memory="光劍活動話帶動咗1000萬消費，但我條鴨寮街一毫子都分唔到。啲錢去晒商場同大牌子度。",
        initial_emotion=EmotionState.ANGRY,
    )
    
    # 3-4: 居民群體
    resident_chan = AgentPersona(
        agent_id="resident_chan",
        name="陳伯", role="退休長者居民",
        background="居住深水埗桂林街唐樓40年，退休前在製衣廠工作。月入約HK$4,000長者津貼。"
                   "2024年光劍活動期間，樓下噪音至深夜11時，失眠加劇。曾打1823投訴但無回應。",
        core_motivation="安靜的晚年生活。對政府活動極度反感，認為自己是被犧牲的一群",
        personality_traits=["固執", "易怒", "念舊", "社區意識強"],
        action_thresholds=ActionThreshold(noise_tolerance=0.2, social_interaction_drive=0.3),
        available_tools=["post_complaint"],
        initial_memory="光劍活動嗰兩日，我成晚瞓唔到。打電話去1823投訴，佢話會跟進，但到而家都冇回音。政府淨係識搞show。",
        initial_emotion=EmotionState.ANGRY,
    )
    
    resident_lee = AgentPersona(
        agent_id="resident_lee",
        name="李太", role="年輕家庭主婦",
        background="與丈夫和兩個小學子女居住深水埗福華街。家庭月入HK$28,000。丈夫在物流公司工作。"
                   "2024年活動期間，子女因噪音無法溫習。2025年曾在區議員Facebook留言投訴，獲10+讚好。",
        core_motivation="子女教育環境。希望社區有活力但不犧牲居住品質",
        personality_traits=["關心社區", "務實", "社交媒體活躍"],
        action_thresholds=ActionThreshold(noise_tolerance=0.35, social_interaction_drive=0.7),
        available_tools=["post_complaint", "check_weather"],
        initial_memory="樓下搞活動我唔反對，但至少要控制音量同時間。仔女要溫書㗎。2026年佢哋搬咗去海濱，反而好咗。",
        initial_emotion=EmotionState.ANXIOUS,
    )
    
    # 5: 區議員
    councillor_fan = AgentPersona(
        agent_id="councillor_fan",
        name="范議員", role="深水埗區議員（提振經濟小組成員）",
        background="2024年新當選區議員，屬建制派。獲委任為'提振地區經濟專責工作小組'成員。"
                   "負責審批活動撥款，需同時面對民政處KPI壓力和居民投訴。"
                   "2026年小組會議已排期至第14次，成為常態化行政負擔。",
        core_motivation="完成KPI以確保連任。在民政處、居民、小販之間做平衡，但缺乏真實決策權",
        personality_traits=["官僚", "務實", "壓力大", "善於妥協"],
        action_thresholds=ActionThreshold(noise_tolerance=0.5, social_interaction_drive=0.9),
        available_tools=["check_weather", "post_complaint"],
        initial_memory="2026年嗰個咖啡市集係新鴻基贊助嘅，我哋區議會基本上只係掛名。真正話事嘅係地產商同民政處。",
        initial_emotion=EmotionState.NEUTRAL,
    )
    
    # 6: 食環署督察
    inspector_cheung = AgentPersona(
        agent_id="inspector_cheung",
        name="張督察", role="食環署巡查員",
        background="食環署前線人員，負責深水埗區小販管理和衛生巡查。在'鼓勵夜市'和'執行條例'之間處於兩難。"
                   "2024年MatchLive拖數事件後，對外判商信任度大幅下降。上級不給清晰指引，只能自行判斷。",
        core_motivation="執行職責但不想成為眾矢之的。被夾在政策口號和實地執法之間",
        personality_traits=["嚴謹", "無奈", "務實"],
        action_thresholds=ActionThreshold(noise_tolerance=0.8, social_interaction_drive=0.4),
        available_tools=["post_complaint"],
        initial_memory="上頭叫我哋'支持夜市'，但又叫我哋'嚴厲執法'。究竟想點？MatchLive拖數之後，我對呢啲活動嘅外判商完全冇信心。",
        initial_emotion=EmotionState.NEUTRAL,
    )
    
    # 7: 商場經理
    mall_manager = AgentPersona(
        agent_id="mall_manager_chow",
        name="周經理", role="深水埗電腦商場管理層",
        background="管理深水埗一個主要電腦商場。2024年光劍活動期間，商場人流增加40%，宣稱帶動逾1000萬消費。"
                   "但活動結束後人流迅速回落。2026年咖啡市集對電腦商場零幫助。",
        core_motivation="商場人流和租金收入最大化。支持任何能帶動短期人流的活動",
        personality_traits=["商業導向", "投機", "現實"],
        action_thresholds=ActionThreshold(noise_tolerance=0.9, economic_stress_threshold=0.6),
        available_tools=["check_weather"],
        initial_memory="光劍活動幫我哋商場多咗四成人流。但2026年佢哋走去搞咖啡，同我哋電腦商場完全冇關係。政府方向轉得好快。",
        initial_emotion=EmotionState.NEUTRAL,
    )
    
    # 8-9: 消費者/遊客
    tourist_local = AgentPersona(
        agent_id="tourist_local_lam",
        name="小林", role="本地年輕消費者",
        background="25歲，住在長沙灣，在九龍灣返寫字樓工。月入HK$22,000。週末喜歡探索各區活動打卡。"
                   "2024年去過光劍活動覺得'好廢'，2026年咖啡市集反而覺得'有質素但太貴'。",
        core_motivation="尋找有趣且值得IG分享的週末活動。對活動質素要求高，對政府'交功課'式活動敏感",
        personality_traits=["挑剔", "社交媒體活躍", "中產品味"],
        action_thresholds=ActionThreshold(noise_tolerance=0.5, social_interaction_drive=0.9),
        available_tools=["check_weather"],
        initial_memory="2024嗰個光劍活動真係好廢，啲表演者俾人笑到上連登。2026咖啡市集好啲，但一杯咖啡$60，太貴。",
        initial_emotion=EmotionState.NEUTRAL,
    )
    
    tourist_mainland = AgentPersona(
        agent_id="tourist_mainland_mary",
        name="Mary", role="內地遊客（自由行）",
        background="來自深圳，30歲，從事市場推廣。每月來港1-2次。在社交媒體看到深水埗活動宣傳後到訪。"
                   "2025年全港旅客4990萬(+12%)，內地旅客佔大比例。",
        core_motivation="尋找'港味'體驗以在社交媒體分享。對香港地道文化有浪漫化想像",
        personality_traits=["好奇", "消費力強", "社交媒體導向"],
        action_thresholds=ActionThreshold(noise_tolerance=0.6, social_interaction_drive=0.8),
        available_tools=["check_weather"],
        initial_memory="小紅書上見到深水埗夜市好有港味，專程嚟打卡。但去到發現唔係想像中咁，有啲失望。",
        initial_emotion=EmotionState.EXCITED,
    )
    
    # 10: NGO/社福
    ngo_worker = AgentPersona(
        agent_id="ngo_worker_ho",
        name="何姑娘", role="社區組織幹事",
        background="在深水埗社區組織工作8年，關注基層權益和小販生計。曾協助小販爭取活動期間的臨時牌照安排。"
                   "認為政府活動的經濟利益分配不公：地產商和商場受益，基層承擔成本。",
        core_motivation="為弱勢社群發聲。挑戰政府'士紳化'議程，爭取資源重新分配",
        personality_traits=["正義感強", "批判性", "社區連結深"],
        action_thresholds=ActionThreshold(noise_tolerance=0.4, social_interaction_drive=1.0),
        available_tools=["post_complaint"],
        initial_memory="2024年光劍活動，電腦商場話賺咗1000萬，但啲小販一毫子都分唔到。2026年直情將活動搬去海濱，徹底放棄基層社區。呢個就係'士紳化'。",
        initial_emotion=EmotionState.ANGRY,
    )
    
    # 11: 媒體/KOL
    media_kol = AgentPersona(
        agent_id="media_kol_wong",
        name="網紅KOL", role="社交媒體內容創作者",
        background="全職YouTuber/IGer，粉絲約5萬。以'香港本地探索'為主題。"
                   "2024年曾拍攝光劍活動並上傳，影片標題'深水埗光劍有幾廢？'獲30萬觀看。"
                   "2026年咖啡市集影片標題'深水埗海濱咖啡市集值唔值得去？'獲15萬觀看。",
        core_motivation="流量和內容傳播。負面報導往往比正面獲得更多互動",
        personality_traits=["投機", "諷刺", "流量導向"],
        action_thresholds=ActionThreshold(noise_tolerance=0.6, social_interaction_drive=1.0),
        available_tools=["check_weather"],
        initial_memory="2024光劍條片30萬views，全靠嘲諷。2026咖啡市集條片得15萬，因為冇嘢好鬧。流量密碼就係鬧政府。",
        initial_emotion=EmotionState.NEUTRAL,
    )
    
    # 12: 外判供應商
    contractor_supplier = AgentPersona(
        agent_id="contractor_chan",
        name="陳老闆", role="活動設備供應商",
        background="經營帳篷和音響設備租賃公司15年。2024年承接多個夜繽紛活動的物資供應。"
                   "九龍城MatchLive拖數71萬事件後(研究B)，全行對政府外判項目信心崩潰。"
                   "現承接政府活動要求50%訂金，否則免談。",
        core_motivation="收回成本，避免再被拖數。對政府外判制度徹底失望",
        personality_traits=["謹慎", "憤怒", "務實"],
        action_thresholds=ActionThreshold(noise_tolerance=0.5, economic_stress_threshold=0.2),
        available_tools=["post_complaint"],
        initial_memory="MatchLive拖我個friend 20萬，最後得三折找數。而家接政府job？冇50%訂金唔洗傾。成個行業都怕咗。",
        initial_emotion=EmotionState.ANGRY,
    )
    
    agents = [
        hawker_wong, hawker_keung,
        resident_chan, resident_lee,
        councillor_fan, inspector_cheung,
        mall_manager,
        tourist_local, tourist_mainland,
        ngo_worker, media_kol, contractor_supplier,
    ]
    
    # ── 初始環境 ──
    env = EnvironmentState(
        day=1, date="2026-03-08",
        weather=WeatherCondition.SUNNY, is_holiday=False,
        noise_level=0.5, crowd_density=0.4, economic_activity=0.4,
        social_stability=0.5, policy_pressure=0.4,
        domain_context=(
            "深水埗日夜都繽紛政策背景（基於2024-2026研究）：\n"
            "2024年：42項活動獲批近2800萬港元。深水埗舉辦'光劍攻殼@深水埗'（獲批10萬）、'尋．埗'文青市集、"
            "'花深時節'市集。活動期間電腦商場宣稱帶動逾1000萬消費，但居民投訴噪音，"
            "表演者抱怨場地不足（舞台<4m vs 需要8m），外判商MatchLive拖數71萬。\n"
            "2025年：施政報告不再提'夜繽紛'。政府財赤670億，公務員凍薪。"
            "旅客回升至4990萬(+12%)。各區提振經濟小組任期延長。\n"
            "2026年3月：深水埗舉辦'深．啡Sham.Coffee.Fair'咖啡市集，地點由街頭移至長沙灣海濱SOHO WEST，"
            "主題轉為精品咖啡+寵物友善+Busking，由新鴻基地產慈善基金聯合主辦。"
            "政策已完成從'基層街頭夜市'到'中產海濱市集'的空間退移與主題士紳化。"
        ),
        metric_definitions={mid: m.model_dump() for mid, m in metrics.items()},
        metrics={mid: m.baseline for mid, m in metrics.items()},
    )
    
    return SimulationConfig(
        simulation_id="ssp_night_vibes_2026",
        title="「18區日夜都繽紛」政策下深水埗夜市的社會動態模擬 (2026)",
        description=(
            "模擬2026年3月深水埗'深．啡'咖啡市集前後14天的社會互動。"
            "追蹤政策從2024年街頭夜市到2026年海濱中產市集的演化軌跡。"
            "核心問題：政府注資的夜經濟活動，其經濟效益與社會成本如何在12類利害相關者之間分配？"
        ),
        max_days=14, start_date="2026-03-08",
        scenario_type="night_market",
        active_metrics=list(metrics.keys()),
        agents=agents,
        global_tools=["check_weather", "post_complaint"],
    )


# ── 執行入口 ──

async def main():
    print(f"\n{'='*70}")
    print(f"  深水埗日夜都繽紛 — 社會動態模擬")
    print(f"  基於2024-2026真實政策演化數據")
    print(f"  12 智能體 × 14 天 × 8 環境指標")
    print(f"{'='*70}\n")
    
    config = build_ssp_night_vibes_config()
    
    # 初始化
    llm = create_deepseek_llm(temperature=0.7)
    tool_registry = create_default_tool_registry()
    memory_manager = create_memory_manager(persist_dir="./chroma_data")
    memory_manager.init_simulation(config.simulation_id)
    
    # 注入 metric 定義到環境
    config.init_metrics()
    
    print(f"  智能體列表：")
    for i, a in enumerate(config.agents, 1):
        print(f"  {i:2d}. {a.name:8s} | {a.role:16s} | 情緒:{a.initial_emotion.value:8s} | 工具:{a.available_tools}")
    
    print(f"\n  環境指標（真實baseline）：")
    for mid in config.active_metrics:
        if mid in config.initial_environment.metric_definitions:
            mdef = Metric(**config.initial_environment.metric_definitions[mid])
            val = config.initial_environment.metrics.get(mid, 0)
            print(f"  {mdef.name:12s}: {mdef.format(val)}")
    
    print(f"\n  [START] 執行模擬 (12人 × 14天)...")
    print(f"{'─'*70}")
    
    result = await run_simulation(
        config=config, llm=llm,
        tool_registry=tool_registry,
        memory_manager=memory_manager,
    )
    
    print(f"\n{'='*70}")
    print(f"  模擬完成")
    print(f"{'='*70}")
    print(f"\n{result.executive_summary}")
    print(f"\n{'='*70}")
    
    return result


if __name__ == "__main__":
    asyncio.run(main())
