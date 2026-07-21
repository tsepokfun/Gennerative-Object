"""
============================================================
  動態多智能體元沙盤推演系統 - MCP 工具掛載點
  Dynamic Multi-Agent Meta-Simulation Platform - Tool Registry
============================================================
  對比舊版 ggg.py：
  - 舊版：只有單一 gR(q) 函數，無工具調用能力
  - 舊版：LLM 只能生成文字，無法與外部系統互動
  - 舊版：所有智能體共享同一函數，無角色分化
  
  新版：
  - 使用 LangChain @tool 裝飾器封裝可調用工具
  - ToolRegistry 管理全局工具目錄，支援動態掛載
  - 每個 AgentPersona 透過 available_tools 欄位選擇性綁定工具
  - 支援 MCP 協議風格的工具描述，讓 LLM 自主決定何時調用
============================================================
"""

from langchain_core.tools import tool
from typing import Optional, List, Dict, Any, Callable
from datetime import datetime, timedelta
from pydantic import BaseModel, Field
import random

from models import AgentPersona, EnvironmentState


# ============================================================
#  第一部分：工具輸入/輸出 Schema (Pydantic)
#  讓 LLM 清楚知道每個工具需要什麼參數、返回什麼
# ============================================================

class WeatherInput(BaseModel):
    """check_weather 工具的輸入 Schema"""
    location: str = Field(
        ...,
        description="查詢地點，如 '深水埗'、'旺角'、'中環'"
    )
    date: Optional[str] = Field(
        default=None,
        description="查詢日期 (YYYY-MM-DD)，預設為今天"
    )


class WeatherOutput(BaseModel):
    """check_weather 工具的輸出 Schema"""
    location: str
    date: str
    temperature_c: float
    humidity_pct: float
    weather_condition: str  # sunny, cloudy, rainy, stormy
    wind_speed_kmh: float
    advice: str  # 對智能體行動的建議


class ComplaintInput(BaseModel):
    """post_complaint 工具的輸入 Schema"""
    reporter_id: str = Field(
        ...,
        description="投訴人 ID (智能體的唯一識別碼)"
    )
    reporter_role: str = Field(
        ...,
        description="投訴人角色，如 '熟食小販'"
    )
    category: str = Field(
        ...,
        description="投訴類別：'noise'（噪音）、'hygiene'（衛生）、"
                    "'illegal_stall'（非法擺檔）、'traffic'（交通）、'other'（其他）"
    )
    target: str = Field(
        ...,
        description="投訴對象描述，如 '鄰近大排檔'、'無牌小販'"
    )
    description: str = Field(
        ...,
        description="投訴詳細內容"
    )
    urgency: str = Field(
        default="normal",
        description="緊急程度：'low'、'normal'、'high'、'critical'"
    )


class ComplaintOutput(BaseModel):
    """post_complaint 工具的輸出 Schema"""
    complaint_id: str
    status: str  # filed, under_review, action_taken
    estimated_response_hours: int
    message: str


# ============================================================
#  第二部分：工具函數定義 (使用 LangChain @tool 裝飾器)
#  這些是沙盤中智能體可調用的「外部能力」
# ============================================================

@tool(args_schema=WeatherInput)
def check_weather(
    location: str,
    date: Optional[str] = None
) -> str:
    """
    查詢指定地點和日期的天氣狀況。
    
    智能體可以使用此工具來決定當天的行動策略。
    例如：若天氣預報有雨，小販可能選擇不出檔；
    若天氣晴朗，遊客可能選擇戶外景點。
    
    使用時機 (When to use)：
    - 智能體需要決定當天是否外出擺檔
    - 遊客需要規劃當天行程
    - 活動主辦方需要評估戶外活動可行性
    
    Args:
        location: 查詢地點（如 '深水埗'、'尖沙咀'）
        date: 日期字串 YYYY-MM-DD，不指定則為當天
    
    Returns:
        JSON 格式的天氣資訊，含溫度、濕度、天氣狀況及行動建議
    """
    # --- 模擬天氣數據生成 ---
    # 在實際部署時，此處可替換為 data.gov.hk 的香港天文台 API：
    # https://data.gov.hk/tc-data/dataset/hk-hko-rss-weather-report
    query_date = date or datetime.now().strftime("%Y-%m-%d")
    
    # 根據月份模擬香港天氣特徵
    month = int(query_date.split("-")[1])
    
    if month in [6, 7, 8, 9]:  # 夏季：炎熱潮濕，多雨
        temp_base = 31.0
        humidity_base = 82.0
        conditions = ["sunny", "cloudy", "rainy", "stormy"]
        weights = [0.2, 0.3, 0.3, 0.2]
    elif month in [12, 1, 2]:  # 冬季：涼爽乾燥
        temp_base = 17.0
        humidity_base = 65.0
        conditions = ["sunny", "cloudy", "rainy", "stormy"]
        weights = [0.4, 0.3, 0.2, 0.1]
    else:  # 春秋：溫和
        temp_base = 25.0
        humidity_base = 75.0
        conditions = ["sunny", "cloudy", "rainy", "stormy"]
        weights = [0.3, 0.3, 0.3, 0.1]
    
    temp = round(temp_base + random.uniform(-3, 3), 1)
    humidity = round(humidity_base + random.uniform(-10, 10), 1)
    weather_cond = random.choices(conditions, weights=weights, k=1)[0]
    wind = round(random.uniform(5, 35), 1)
    
    # 生成行動建議
    advice_map = {
        "sunny": f"天氣晴朗，適合戶外活動。建議{location}的智能體增加戶外營業時間。",
        "cloudy": f"多雲天氣，不影響正常活動。{location}的日常運作不受影響。",
        "rainy": f"有雨天氣，建議{location}的小販準備防水設備或考慮暫停營業。遊客可能轉向室內場所。",
        "stormy": f"惡劣天氣！建議{location}所有戶外活動暫停。小販應立即收檔避險。",
    }
    
    output = WeatherOutput(
        location=location,
        date=query_date,
        temperature_c=temp,
        humidity_pct=humidity,
        weather_condition=weather_cond,
        wind_speed_kmh=wind,
        advice=advice_map.get(weather_cond, "請根據實際情況決定行動。")
    )
    
    return output.model_dump_json(indent=2, ensure_ascii=False)


@tool(args_schema=ComplaintInput)
def post_complaint(
    reporter_id: str,
    reporter_role: str,
    category: str,
    target: str,
    description: str,
    urgency: str = "normal"
) -> str:
    """
    向有關部門提交正式投訴。
    
    智能體在遇到無法自行解決的問題時（如噪音滋擾、衛生問題、
    非法擺檔等），可以使用此工具向虛擬的「管理部門」提出投訴。
    投訴結果將影響後續的 policy_pressure 和 social_stability 變數。
    
    使用時機 (When to use)：
    - 噪音水平超過自身容忍度 (noise_level > ActionThreshold.noise_tolerance)
    - 發現衛生隱患影響生意
    - 與其他智能體發生衝突需要第三方介入
    
    Args:
        reporter_id: 投訴人 ID
        reporter_role: 投訴人角色
        category: 投訴類別 (noise/hygiene/illegal_stall/traffic/other)
        target: 投訴對象
        description: 詳細描述
        urgency: 緊急程度
    
    Returns:
        JSON 格式的投訴結果，含投訴編號及預計處理時間
    """
    # --- 模擬投訴處理系統 ---
    # 在實際部署時，可對接真實的政府 1823 投訴 API 或
    # data.gov.hk 的相關數據集
    
    # 生成投訴編號
    complaint_id = f"COMP-{datetime.now().strftime('%Y%m%d')}-{random.randint(1000, 9999)}"
    
    # 根據緊急程度決定處理時間
    urgency_response_map = {
        "low": (72, "filed"),
        "normal": (48, "filed"),
        "high": (24, "under_review"),
        "critical": (4, "under_review"),
    }
    
    hours, status = urgency_response_map.get(urgency, (48, "filed"))
    
    # 根據投訴類別生成回應訊息
    category_messages = {
        "noise": f"已記錄噪音投訴（針對 {target}）。相關部門將於 {hours} 小時內派員巡查。",
        "hygiene": f"衛生投訴已受理。食環署將於 {hours} 小時內派員檢查 {target} 的衛生狀況。",
        "illegal_stall": f"非法擺檔投訴已轉交城管部門。預計 {hours} 小時內採取行動。",
        "traffic": f"交通投訴已記錄。運輸署將檢視 {target} 附近的交通情況。",
        "other": f"投訴已受理，編號 {complaint_id}。預計 {hours} 小時內跟進。",
    }
    
    message = category_messages.get(category, category_messages["other"])
    
    output = ComplaintOutput(
        complaint_id=complaint_id,
        status=status,
        estimated_response_hours=hours,
        message=message
    )
    
    return output.model_dump_json(indent=2, ensure_ascii=False)


# ============================================================
#  第三部分：工具註冊表 (Tool Registry)
#  管理全局工具目錄，支援按 AgentPersona 動態分配
# ============================================================

class ToolRegistry:
    """
    工具註冊表 — 管理沙盤中所有可用的 MCP 工具
    
    對比舊版 ggg.py 的單一 gR(q) 函數：
    - 舊版：所有智能體共用一個函數，無法區分能力
    - 新版：每個智能體根據其 available_tools 選擇性獲取工具
    
    使用範例：
        registry = ToolRegistry()
        registry.register(check_weather)
        registry.register(post_complaint)
        
        # 為特定智能體獲取其工具
        agent_tools = registry.get_tools_for_agent(agent_persona)
    """
    
    def __init__(self):
        """初始化空的工具註冊表"""
        # 工具目錄：name -> LangChain BaseTool
        self._tools: Dict[str, Any] = {}
        
        # 工具元數據：name -> description (供 LLM 理解工具用途)
        self._tool_metadata: Dict[str, Dict[str, str]] = {}
    
    def register(self, tool_func: Callable) -> None:
        """
        註冊一個 LangChain @tool 函數到全局目錄
        
        Args:
            tool_func: 使用 @tool 裝飾器修飾的函數
        """
        tool_name = tool_func.name
        self._tools[tool_name] = tool_func
        
        # 提取工具元數據供 Creator Agent 參考
        self._tool_metadata[tool_name] = {
            "name": tool_name,
            "description": tool_func.description,
            "args_schema": str(tool_func.args_schema.schema()) 
                if tool_func.args_schema else "None"
        }
        
        print(f"[ToolRegistry] 已註冊工具: '{tool_name}' — {tool_func.description[:60]}...")
    
    def unregister(self, tool_name: str) -> None:
        """從註冊表中移除一個工具"""
        self._tools.pop(tool_name, None)
        self._tool_metadata.pop(tool_name, None)
        print(f"[ToolRegistry] 已移除工具: '{tool_name}'")
    
    def get_tool(self, tool_name: str) -> Optional[Callable]:
        """
        按名稱獲取單個工具
        
        Args:
            tool_name: 工具名稱
        
        Returns:
            LangChain BaseTool 實例，不存在則返回 None
        """
        return self._tools.get(tool_name)
    
    def get_tools_for_agent(self, persona: AgentPersona) -> List[Callable]:
        """
        根據智能體人格，獲取其有權使用的工具列表
        
        這是動態工具分配的關鍵方法：每個 AgentPersona 的
        available_tools 欄位定義了它可以使用哪些工具，
        此方法將名稱解析為實際的 LangChain BaseTool 實例。
        
        Args:
            persona: 智能體人格配置
        
        Returns:
            該智能體可調用的 LangChain BaseTool 列表
        """
        agent_tools = []
        
        for tool_name in persona.available_tools:
            tool = self._tools.get(tool_name)
            if tool:
                agent_tools.append(tool)
            else:
                print(f"[ToolRegistry] 警告: 智能體 '{persona.name}' 請求了未註冊的工具 '{tool_name}'")
        
        return agent_tools
    
    def get_all_tools(self) -> List[Callable]:
        """獲取所有已註冊的工具（供全局使用）"""
        return list(self._tools.values())
    
    def list_tools(self) -> List[Dict[str, str]]:
        """
        列出所有已註冊工具的摘要
        
        Returns:
            工具名稱與描述的列表
        """
        return [
            {"name": name, "description": meta["description"]}
            for name, meta in self._tool_metadata.items()
        ]
    
    def get_tools_summary_for_llm(self) -> str:
        """
        生成工具目錄的文字摘要，供 Creator Agent 在生成
        AgentPersona 時決定如何分配 available_tools
        
        Returns:
            格式化的工具目錄文字
        """
        if not self._tools:
            return "（暫無可用工具）"
        
        lines = ["目前可用的 MCP 工具列表："]
        for i, (name, meta) in enumerate(self._tool_metadata.items(), 1):
            lines.append(
                f"  {i}. **{name}** — {meta['description'][:100]}"
            )
        
        return "\n".join(lines)


# ============================================================
#  第四部分：工具與環境互動 (Tool-Environment Bridge)
#  工具執行結果如何影響沙盤的 EnvironmentState
# ============================================================

def apply_tool_effects_to_environment(
    tool_name: str,
    tool_result: str,
    environment: EnvironmentState,
    agent_id: str
) -> EnvironmentState:
    """
    將工具執行的結果反映到環境狀態中
    
    這是工具系統與環境狀態的橋樑。當智能體調用工具後，
    此函數根據工具類型更新 EnvironmentState 的相關變數。
    
    Args:
        tool_name: 被調用的工具名稱
        tool_result: 工具返回的 JSON 結果
        environment: 當前環境狀態（會被複製並修改）
        agent_id: 調用工具的智能體 ID
    
    Returns:
        更新後的環境狀態副本
    """
    import json
    import copy
    
    # 複製環境狀態以避免副作用
    new_env = copy.deepcopy(environment)
    
    try:
        result_data = json.loads(tool_result)
    except json.JSONDecodeError:
        return new_env
    
    if tool_name == "post_complaint":
        # 投訴行為增加政策壓力，可能降低社會穩定度
        urgency = result_data.get("urgency", "normal")
        urgency_impact = {"low": 0.01, "normal": 0.03, "high": 0.06, "critical": 0.10}
        
        new_env.policy_pressure = min(
            1.0,
            new_env.policy_pressure + urgency_impact.get(urgency, 0.03)
        )
        new_env.social_stability = max(
            0.0,
            new_env.social_stability - urgency_impact.get(urgency, 0.02)
        )
    
    elif tool_name == "check_weather":
        # 天氣查詢本身不改變環境，但結果可以更新 weather 欄位
        condition = result_data.get("weather_condition", "sunny")
        from models import WeatherCondition
        try:
            new_env.weather = WeatherCondition(condition)
        except ValueError:
            pass  # 無效的天氣狀況，保持不變
    
    return new_env


# ============================================================
#  第五部分：便捷初始化函數
# ============================================================

def create_default_tool_registry() -> ToolRegistry:
    """
    創建並初始化包含所有預設工具的 ToolRegistry
    
    這是沙盤啟動時的標準初始化流程。
    預設註冊 check_weather 和 post_complaint 兩個工具。
    
    Returns:
        已註冊預設工具的 ToolRegistry 實例
    """
    registry = ToolRegistry()
    
    # 註冊基礎工具
    registry.register(check_weather)   # 天氣查詢工具
    registry.register(post_complaint)  # 投訴提交工具
    
    # 未來可在這裡註冊更多工具，例如：
    # registry.register(query_data_gov_hk)  # data.gov.hk 開放數據查詢
    # registry.register(send_message)       # 智能體間通訊
    # registry.register(apply_license)      # 申請牌照
    
    return registry


# ============================================================
#  自我測試 (開發期間用)
# ============================================================

if __name__ == "__main__":
    print("=== MCP 工具掛載點自我測試 ===\n")
    
    # --- 測試 1: check_weather ---
    print("【測試 1】check_weather 工具")
    print("-" * 50)
    result = check_weather.invoke({
        "location": "深水埗",
        "date": "2008-07-15"
    })
    print(result)
    
    # --- 測試 2: post_complaint ---
    print("\n【測試 2】post_complaint 工具")
    print("-" * 50)
    result = post_complaint.invoke({
        "reporter_id": "hawker_01",
        "reporter_role": "熟食小販",
        "category": "noise",
        "target": "桂林街大排檔",
        "description": "大排檔深夜營業噪音過大，影響附近居民休息及我檔口生意",
        "urgency": "high"
    })
    print(result)
    
    # --- 測試 3: ToolRegistry ---
    print("\n【測試 3】ToolRegistry 動態分配")
    print("-" * 50)
    
    registry = create_default_tool_registry()
    print(f"\n已註冊工具總數: {len(registry.get_all_tools())}")
    print(f"\n{registry.get_tools_summary_for_llm()}")
    
    # 模擬一個小販智能體
    hawker = AgentPersona(
        agent_id="hawker_01",
        name="陳伯",
        role="熟食小販",
        background="深水埗經營魚蛋檔30年",
        core_motivation="養活一家三口，維持生計",
        personality_traits=["勤奮", "保守", "易怒"],
        available_tools=["post_complaint"]  # 小販可以投訴
    )
    
    # 模擬一個遊客智能體
    tourist = AgentPersona(
        agent_id="tourist_01",
        name="Mary",
        role="外國遊客",
        background="來自英國的背包客",
        core_motivation="探索香港地道文化",
        personality_traits=["好奇", "友善"],
        available_tools=["check_weather"]  # 遊客可以查天氣
    )
    
    # 獲取各智能體的工具
    hawker_tools = registry.get_tools_for_agent(hawker)
    tourist_tools = registry.get_tools_for_agent(tourist)
    
    print(f"\n陳伯的工具 ({len(hawker_tools)}個): "
          f"{[t.name for t in hawker_tools]}")
    print(f"Mary 的工具 ({len(tourist_tools)}個): "
          f"{[t.name for t in tourist_tools]}")
    
    # --- 測試 4: 工具對環境的影響 ---
    print("\n【測試 4】工具對環境狀態的影響")
    print("-" * 50)
    
    env = EnvironmentState(
        day=1,
        date="2008-07-15",
        noise_level=0.75,
        policy_pressure=0.2,
        social_stability=0.8
    )
    print(f"投訴前: policy_pressure={env.policy_pressure}, "
          f"social_stability={env.social_stability}")
    
    complaint_result = post_complaint.invoke({
        "reporter_id": "hawker_01",
        "reporter_role": "熟食小販",
        "category": "noise",
        "target": "桂林街大排檔",
        "description": "噪音過大",
        "urgency": "high"
    })
    
    env = apply_tool_effects_to_environment(
        "post_complaint", complaint_result, env, "hawker_01"
    )
    print(f"投訴後: policy_pressure={env.policy_pressure:.2f}, "
          f"social_stability={env.social_stability:.2f}")
    
    print("\n✅ 所有測試完成")
