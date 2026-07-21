"""
============================================================
  動態多智能體元沙盤推演系統 - LangGraph 核心引擎
  Dynamic Multi-Agent Meta-Simulation Platform - Core Engine
============================================================
  對比舊版 timeLine.py：
  - 舊版：硬編碼 while 迴圈 + prompt 字串拼接 + "!!!" 解析
  - 舊版：順序執行，無法並行處理智能體
  - 舊版：無狀態機，出錯即中斷，無法恢復
  
  新版：
  - 使用 LangGraph StateGraph 構建有向狀態圖
  - 三個核心節點：perceive → agent_action → environment_settle
  - 支援並行智能體決策 (asyncio)
  - 整合 ChromaDB 記憶管理器 + MCP 工具註冊表 + DeepSeek LLM
  - Creator Agent 自動從自然語言生成 SimulationConfig
============================================================
"""

import asyncio
import json
import os
import re
import sys
from datetime import datetime, timedelta
from typing import TypedDict, Annotated, List, Dict, Any, Optional, Sequence
from dataclasses import dataclass, field

# --- Windows 控制台 UTF-8 支援 (解決 cp950 無法處理香港特有字元如「埗」) ---
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# --- LangGraph 核心 ---
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

# --- LangChain + DeepSeek ---
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage, ToolMessage
from langchain_core.tools import BaseTool

# --- 本地模組 ---
from models import (
    SimulationConfig, SimulationResult, EnvironmentState,
    AgentPersona, AgentAction, DayLog, ActionThreshold, WeatherCondition,
    get_metric_template,
)
from memory_manager import MemoryManager, create_memory_manager
from tools import ToolRegistry, create_default_tool_registry, apply_tool_effects_to_environment


# 工具函數 — 三層防線將 DeepSeek 文字描述轉為數字 metric delta

# 防線 3：關鍵字啟發式映射
_HEURISTIC_MAP = {
    "投訴": {"complaint_count": 0.03},
    "噪音": {"noise_db": 0.02},
    "嘈": {"noise_db": 0.02},
    "收入": {"vendor_daily_revenue": 0.03},
    "生意": {"vendor_daily_revenue": 0.03},
    "人流": {"crowd_density": 0.02, "tourist_count": 0.03},
    "人群": {"crowd_density": 0.03},
    "遊客": {"tourist_count": 0.03},
    "滿意": {"resident_satisfaction": 0.03},
    "不滿": {"resident_satisfaction": -0.03},
    "執法": {"policy_tightness": 0.03},
    "巡查": {"policy_tightness": 0.02},
    "中產": {"gentrification_index": 0.03},
    "紳士": {"gentrification_index": 0.03},
    "咖啡": {"gentrification_index": 0.03},
    "抗議": {"complaint_count": 0.1, "noise_db": 0.03},
    "請願": {"complaint_count": 0.1, "policy_tightness": 0.03},
    "杯葛": {"policy_tightness": 0.03, "vendor_daily_revenue": -0.03},
    "訂金": {"policy_tightness": 0.03},
    "海濱": {"gentrification_index": 0.02},
    "打卡": {"tourist_count": 0.03},
    "宣傳": {"tourist_count": 0.02},
    "發帖": {"resident_satisfaction": -0.03, "complaint_count": 0.03},
    "拍片": {"tourist_count": 0.03},
    "流量": {"tourist_count": 0.03},
}

def _smart_effects(raw: Any, action_desc: str = "", action_type: str = "") -> dict:
    """
    三層防線將 DeepSeek 回應轉為有效的 environment_effects dict
    防線 1: 已是 dict + 數字 → 直接使用
    防線 2: 中文關鍵字啟發式匹配 (快速，零成本)
    防線 3: 空 dict（至少不會崩潰）
    """
    if isinstance(raw, dict):
        result = {}
        for k, v in raw.items():
            if isinstance(v, (int, float)):
                result[k] = float(v)
        if result:
            return result
    
    text = str(raw) + " " + str(action_desc) + " " + str(action_type)
    result = {}
    for keyword, effects in _HEURISTIC_MAP.items():
        if keyword in text:
            for mid, delta in effects.items():
                result[mid] = result.get(mid, 0.0) + delta
    if result:
        return result
    return {}


async def _llm_effects(llm, action_desc: str, action_type: str, metric_ids: list, metric_info: str) -> dict:
    """
    防線0 (LLM 語義→數字)：用 mini DeepSeek call 將行動描述轉為精確 metric delta
    比啟發式更準確，因為 LLM 理解語義而非僅匹配關鍵字
    """
    prompt = f"""Convert this agent action to environment metric changes.
Action: "{action_desc}" (type: {action_type})
Available metrics with their meanings:
{metric_info}
Return ONLY a JSON object like {{"metric_id": delta}} where delta is -0.5 to +0.5.
Example: {{"complaint_count": 0.15, "noise_db": 0.05}}
Do NOT include explanations. Output ONLY the JSON object."""
    try:
        resp = await llm.ainvoke([HumanMessage(content=prompt)])
        txt = resp.content.strip()
        start = txt.find('{')
        end = txt.rfind('}')
        if start >= 0 and end > start:
            result = {}
            for k, v in json.loads(txt[start:end+1]).items():
                if k in metric_ids and isinstance(v, (int, float)):
                    result[k] = max(-0.3, min(0.3, float(v)))
            if result:
                return result
    except Exception:
        pass
    return {}


def _compute_effects(llm, action_data, env) -> dict:
    """四層防線整合：LLM→dict→keyword→empty"""
    action_desc = action_data.get("action_description", "")
    action_type = action_data.get("action_type", "observe")
    raw = action_data.get("environment_effects")
    return _smart_effects(raw, action_desc, action_type)


# ============================================================
#  第零部分：DeepSeek LLM 工廠
#  對比舊版 ggg.py 的 genai.GenerativeModel("gemini-1.5-flash")
# ============================================================

import os

# DeepSeek API 配置 (API Key 從環境變數 DEEPSEEK_API_KEY 讀取)
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL = "deepseek-chat"


def create_deepseek_llm(
    temperature: float = 0.7,
    model: str = DEEPSEEK_MODEL
) -> ChatOpenAI:
    """
    創建 DeepSeek LLM 實例 (OpenAI 兼容接口)
    
    DeepSeek API 與 OpenAI API 完全兼容，因此可直接使用
    LangChain 的 ChatOpenAI 類別，只需替換 base_url。
    
    Args:
        temperature: LLM 溫度 (0.0~2.0)
        model: 模型名稱 (deepseek-chat / deepseek-reasoner)
    
    Returns:
        ChatOpenAI 實例，指向 DeepSeek API
    """
    return ChatOpenAI(
        model=model,
        api_key=DEEPSEEK_API_KEY,
        base_url=DEEPSEEK_BASE_URL,
        temperature=temperature,
        max_tokens=4096,
    )


# ============================================================
#  第一部分：LangGraph 圖狀態定義 (Graph State)
#  取代舊版 timeLine.py 中的分散變數 (ct_dt, ST, ed, ...)
# ============================================================

class SimulationState(TypedDict):
    """
    LangGraph 狀態圖的共享狀態 — 在節點之間傳遞的核心數據
    
    對比舊版：
    - 舊版的 ct_dt, ST, ed → state["day"], state["date"]
    - 舊版的 ObjInfo.Memory → state["memories"] (透過 MemoryManager)
    - 舊版的 GF.action[] → state["day_logs"]
    - 舊版完全沒有的 → state["config"], state["messages"]
    """
    # --- 模擬配置 (唯讀參考) ---
    config: SimulationConfig
    
    # --- 當前環境狀態 (隨模擬日更新) ---
    environment: EnvironmentState
    
    # --- 智能體運行時狀態 ---
    agent_states: Dict[str, Dict[str, Any]]
    # 格式: {agent_id: {"emotion": "neutral", "last_action": None, ...}}
    
    # --- 當日日誌 (每日重置) ---
    current_day_log: Dict[str, Any]
    # 格式: {"day": 1, "date": "2008-01-01", "actions": [], "notable_events": []}
    
    # --- 歷史日誌 (累積) ---
    day_logs: List[Dict[str, Any]]
    
    # --- LLM 訊息歷史 (用於多輪對話) ---
    messages: List[Dict[str, Any]]
    
    # --- 循環控制 ---
    should_continue: bool


def create_initial_state(config: SimulationConfig) -> SimulationState:
    """
    根據 SimulationConfig 創建初始狀態
    
    這是 LangGraph 的入口點，對應舊版 timeLine.py 中
    設定 ST, ed, ST_dt, ed_dt 的初始化步驟。
    """
    # 初始化每個智能體的運行時狀態
    agent_states = {}
    for agent in config.agents:
        agent_states[agent.agent_id] = {
            "emotion": agent.initial_emotion.value,
            "last_action": None,
            "persona": agent.model_dump(),  # 緩存 persona 數據
        }
    
    return SimulationState(
        config=config,
        environment=config.initial_environment.model_copy(deep=True),
        agent_states=agent_states,
        current_day_log={
            "day": 1,
            "date": config.start_date,
            "actions": [],
            "notable_events": [],
            "emergent_phenomena": [],
        },
        day_logs=[],
        messages=[],
        should_continue=True,
    )


# ============================================================
#  第二部分：節點函數定義 (Node Functions)
#  對應舊版 while 迴圈中的每一步
# ============================================================

# --- 節點 1: perceive_node (感知節點) ---
# 對應舊版：讀取 ObjInfo.getData(obj_num) 獲取記憶
# 新版：透過 MemoryManager.retrieve_relevant_memory() 做語義檢索

def perceive_node(
    state: SimulationState,
    memory_manager: MemoryManager
) -> SimulationState:
    """
    感知節點：讓每個智能體根據當前環境狀態，從 ChromaDB 檢索相關歷史記憶
    
    對比舊版 timeLine.py：
    - 舊版：obj_data = ObjInfo.getData(obj_num) → 僅獲取最新一條字串記憶
    - 新版：語義檢索 Top-K 相關記憶，附帶 relevance_score
    
    此節點在每天開始時執行，為智能體提供「今天的背景資訊」。
    """
    env = state["environment"]
    config = state["config"]
    
    # 構建當前情境描述（用於語義匹配）
    situation = (
        f"模擬第 {env.day} 天，日期 {env.date}。"
        f"天氣：{env.weather.value}。"
        f"{env.format_for_llm()}"
    )
    if env.special_event:
        situation += f" 特殊事件：{env.special_event}。"
    
    # 為每個智能體檢索記憶
    agent_perceptions = {}
    for agent in config.agents:
        memories = memory_manager.retrieve_relevant_memory(
            agent_id=agent.agent_id,
            current_situation=situation,
            top_k=3  # Top-3 最相關記憶
        )
        agent_perceptions[agent.agent_id] = {
            "memories": memories,
            "situation": situation,
        }
    
    # 將感知結果存入 agent_states
    for agent_id, perception in agent_perceptions.items():
        if agent_id in state["agent_states"]:
            state["agent_states"][agent_id]["perception"] = perception
    
    state["messages"].append({
        "role": "system",
        "content": f"[Day {env.day}] perceive_node: 已為 {len(agent_perceptions)} 個智能體檢索歷史記憶",
        "timestamp": datetime.now().isoformat(),
    })
    
    print(f"  [Perceive] Day {env.day}: 已檢索 {len(agent_perceptions)} 個智能體的相關記憶")
    return state


# --- 節點 2: agent_action_node (智能體行動節點) ---
# 對應舊版：ggg.gR(prompt) → 解析 "!!!" → GF.adda()
# 新版：DeepSeek LLM + Tool Calling + 結構化輸出

async def agent_action_node(
    state: SimulationState,
    llm: ChatOpenAI,
    tool_registry: ToolRegistry,
    memory_manager: MemoryManager
) -> SimulationState:
    """
    智能體行動節點：並發調用 LLM 為每個智能體生成當天行動
    
    對比舊版 timeLine.py 的 for obj_num in range(ObjInfo.noOfObj):
    - 舊版：順序執行，N 個智能體需 N 次 API 調用（無並行）
    - 舊版：prompt 純文字拼接，無結構化輸出，依賴 "!!!" 分割
    - 新版：asyncio 並行調用、結構化 JSON 輸出、支援 Tool Calling
    
    Args:
        state: 當前圖狀態
        llm: DeepSeek LLM 實例
        tool_registry: 工具註冊表
        memory_manager: 記憶管理器
    """
    env = state["environment"]
    config = state["config"]
    metric_defs = getattr(config, 'metric_definitions', None) or {}
    
    # 構建系統提示 — 使用真實單位而非抽象 0-1
    metrics_display = env.format_for_llm()
    system_context = (
        f"你正在參與一個社會模擬沙盤推演。\n"
        f"模擬主題：{config.title}\n"
        f"模擬描述：{config.description}\n"
        f"當前日期：{env.date} (第 {env.day} 天)\n"
        f"天氣：{env.weather.value}\n"
        f"環境指標：\n{metrics_display}\n"
    )
    if env.special_event:
        system_context += f"⚠️ 特殊事件：{env.special_event}\n"
    if env.is_holiday:
        system_context += "今天為公眾假期，人流與消費模式可能與平日不同。\n"
    
    # --- 並行處理每個智能體 ---
    async def process_agent(agent: AgentPersona) -> Optional[AgentAction]:
        """處理單個智能體的決策 (異步)"""
        try:
            # 獲取該智能體的感知資訊（含歷史記憶）
            agent_state = state["agent_states"].get(agent.agent_id, {})
            perception = agent_state.get("perception", {})
            memories = perception.get("memories", [])
            
            # 構建歷史記憶摘要（加入行動結果以便 agent 從歷史學習）
            memory_text = "暫無相關歷史記憶。"
            if memories:
                memory_lines = ["以下是與當前情境相關的歷史記憶（請根據這些經驗調整今天的決策）："]
                for i, mem in enumerate(memories, 1):
                    meta = mem.get('metadata', {})
                    memory_lines.append(
                        f"  [Day {meta.get('day','?')}] {mem['document'][:120]}\n"
                        f"    當時行動類型: {meta.get('action_type','?')}, 情緒: {meta.get('emotion','?')}"
                    )
                memory_text = "\n".join(memory_lines)
            
            # 獲取該智能體的工具
            agent_tools = tool_registry.get_tools_for_agent(agent)
            tool_names = [t.name for t in agent_tools] if agent_tools else ["無"]
            
            # --- 構建 Agent 專屬 Prompt (純文字描述欄位，不展示巢狀JSON) ---
            user_prompt = (
                f"請只用JSON回應，不要其他文字。\n"
                f"你是 {agent.name}，{agent.role}。背景：{agent.background}。"
                f"動機：{agent.core_motivation}。"
                f"特質：{', '.join(agent.personality_traits)}。"
                f"情緒：{agent_state.get('emotion', 'neutral')}。\n"
                f"日期：{env.date}。可用工具：{', '.join(tool_names)}。\n"
                f"記憶：{memory_text}\n"
                f"JSON欄位: action_type action_description duration_minutes "
                f"target_agent_id environment_effects tool_to_call tool_args "
                f"emotion_after_action"
            )
            
            # 調用 LLM (純 prompt 驅動 JSON，比 response_format 更可控)
            messages = [
                SystemMessage(content=system_context),
                HumanMessage(content=user_prompt),
            ]
            response = await llm.ainvoke(messages)
            response_text = response.content.strip()
            
            # 從回應中提取 JSON (找 { 到 } )
            try:
                start = response_text.find('{')
                end = response_text.rfind('}')
                if start >= 0 and end > start:
                    action_data = json.loads(response_text[start:end+1])
                else:
                    raise ValueError("No JSON found")
                if env.day == 1:
                    print(f"    [OK] {agent.name}: {str(action_data.get('action_description',''))[:80]}")
            except Exception:
                desc = response_text[:120].replace('\n',' ').strip()
                print(f"    [WARN] {agent.name} JSON parse failed, using raw text")
                action_data = {
                    "action_type": "observe",
                    "action_description": desc or f"{agent.name} 觀察了周圍環境",
                    "duration_minutes": 30, "target_agent_id": None,
                    "environment_effects": {}, "tool_to_call": None,
                    "tool_args": {}, "emotion_after_action": "neutral",
                }
            
            # 處理工具調用
            tool_calls_record = []
            tool_to_call = action_data.get("tool_to_call")
            if tool_to_call and agent_tools:
                tool = tool_registry.get_tool(tool_to_call)
                if tool:
                    try:
                        tool_args = action_data.get("tool_args", {})
                        tool_result = tool.invoke(tool_args)
                        tool_calls_record.append({
                            "tool_name": tool_to_call,
                            "tool_args": tool_args,
                            "tool_result": str(tool_result)[:500],  # 截斷過長結果
                        })
                        
                        # 將工具結果反映到環境
                        state["environment"] = apply_tool_effects_to_environment(
                            tool_name=tool_to_call,
                            tool_result=str(tool_result),
                            environment=state["environment"],
                            agent_id=agent.agent_id
                        )
                    except Exception as e:
                        tool_calls_record.append({
                            "tool_name": tool_to_call,
                            "error": str(e),
                        })
            
            # 構建 AgentAction
            # 四層防線: LLM→dict→keyword→empty
            action_desc = action_data.get("action_description", f"{agent.name} 觀察了周圍環境")
            action_type = action_data.get("action_type", "observe")
            raw_eff = action_data.get("environment_effects")
            
            # 防線 1+2: 關鍵字匹配
            effects = _smart_effects(raw_eff, action_desc, action_type)
            
            # 防線 0: 若結果太簡單，用 LLM 做語義分析
            if not effects or len(effects) < 2:
                try:
                    mids = list(env.metrics.keys()) if env.metrics else []
                    info = ""
                    for mid in mids[:5]:
                        mdef = env.get_metric_def(mid)
                        info += f"- {mid}: {mdef.description if mdef else 'no desc'}\n"
                    llm_eff = await _llm_effects(llm, action_desc, action_type, mids, info)
                    if llm_eff:
                        effects = llm_eff
                except Exception:
                    pass
            
            agent_action = AgentAction(
                agent_id=agent.agent_id,
                day=env.day,
                timestamp=datetime.now().isoformat(),
                action_type=action_type,
                action_description=action_desc,
                duration_minutes=action_data.get("duration_minutes", 30),
                target_agent_id=action_data.get("target_agent_id"),
                environment_effects=effects,
                tool_calls=tool_calls_record,
            )
            
            # 更新智能體情緒
            new_emotion = action_data.get("emotion_after_action", "neutral")
            state["agent_states"][agent.agent_id]["emotion"] = new_emotion
            state["agent_states"][agent.agent_id]["last_action"] = agent_action.model_dump()
            
            # --- 將記憶寫入 ChromaDB ---
            try:
                memory_manager.save_episodic_memory(
                    agent_id=agent.agent_id,
                    day=env.day,
                    context=perception.get("situation", f"Day {env.day}"),
                    action=agent_action,
                    emotion=new_emotion
                )
            except Exception as e:
                print(f"    [WARN] 寫入記憶失敗 ({agent.name}): {e}")
            
            print(f"    [{agent.name}] {agent_action.action_description[:60]}...")
            return agent_action
            
        except Exception as e:
            print(f"    [ERROR] 處理智能體 {agent.name} 時出錯: {e}")
            # 返回一個預設的觀察行動
            return AgentAction(
                agent_id=agent.agent_id,
                day=env.day,
                timestamp=datetime.now().isoformat(),
                action_type="observe",
                action_description=f"{agent.name} 因技術原因無法執行預定行動，僅觀察周圍環境",
                duration_minutes=15,
            )
    
    # 並行執行所有智能體的決策
    tasks = [process_agent(agent) for agent in config.agents]
    results = await asyncio.gather(*tasks)
    
    # 收集有效的行動結果
    for action in results:
        if action is not None:
            state["current_day_log"]["actions"].append(action.model_dump())
    
    state["messages"].append({
        "role": "system",
        "content": f"[Day {env.day}] agent_action_node: {len([r for r in results if r])} 個智能體完成行動",
        "timestamp": datetime.now().isoformat(),
    })
    
    print(f"  [Action] Day {env.day}: {len([r for r in results if r])}/{len(config.agents)} 個智能體執行行動")
    return state


# --- 節點 3: environment_settle_node (環境結算節點) ---
# 對應舊版：無（舊版沒有環境動態更新機制）
# 新版：根據所有智能體的行動，更新全局環境變數

def environment_settle_node(
    state: SimulationState,
    llm: ChatOpenAI
) -> SimulationState:
    """
    環境結算節點：匯總當天所有智能體行動，更新環境狀態並生成日誌
    
    對比舊版：
    - 舊版 timeLine.py：無環境更新，所有變數在整個模擬中保持不變
    - 新版：根據智能體行動的 environment_effects 累積更新環境
    
    此節點在每天所有智能體完成行動後執行。
    """
    env = state["environment"]
    config = state["config"]
    actions = state["current_day_log"].get("actions", [])
    
    # 確保 metric_definitions 在 LangGraph state 傳遞中不丟失
    if not env.metric_definitions and hasattr(config, "get_metric_definitions"):
        mdefs = config.get_metric_definitions()
        env.metric_definitions = {mid: m.model_dump() for mid, m in mdefs.items()}
        env.init_metrics_from_definitions()
    
    # --- 步驟 1: 使用 Metric-aware apply_effect 累積影響 ---
    for action_data in actions:
        effects = action_data.get("environment_effects", {})
        if isinstance(effects, dict):
            for metric_id, delta in effects.items():
                if isinstance(delta, (int, float)):
                    env.apply_effect(metric_id, delta)
    
    # --- 步驟 2: 自然衰減 (每日自我調節) ---
    env.apply_effect("noise_level", -0.02)
    env.apply_effect("crowd_density", -0.01)
    
    # --- 步驟 3: 使用 LLM 生成當日摘要 (真實單位) ---
    if actions:
        actions_summary = "\n".join([
            f"- [{a.get('agent_id', '?')}] {a.get('action_description', '')[:100]}"
            for a in actions
        ])
        
        metrics_display = env.format_for_llm()
        summary_prompt = f"""
以下是模擬第 {env.day} 天（{env.date}）的所有智能體行動摘要：

{actions_summary}

當前環境狀態：
{metrics_display}
- 經濟活躍度：{env.economic_activity:.1%}
- 社會穩定度：{env.social_stability:.1%}
- 政策壓力：{env.policy_pressure:.1%}

請用 1-2 句繁體中文摘要今天的重要事件，並指出是否出現任何「浮現現象」
（即個別智能體行為的集體結果，超出了單一智能體的意圖）。
"""
        
        try:
            summary_response = llm.invoke([HumanMessage(content=summary_prompt)])
            summary_text = summary_response.content.strip()
        except Exception:
            summary_text = f"第 {env.day} 天：{len(actions)} 個智能體執行了行動。"
        
        state["current_day_log"]["notable_events"] = [summary_text]
    
    # --- 步驟 4: 生成 DayLog 並存檔 ---
    day_log = DayLog(
        day=env.day,
        date=env.date,
        actions=[AgentAction(**a) for a in actions],
        environment_before=state["environment"].model_copy(deep=True),
        environment_after=env.model_copy(deep=True),
        notable_events=state["current_day_log"].get("notable_events", []),
        emergent_phenomena=state["current_day_log"].get("emergent_phenomena", []),
    )
    
    state["day_logs"].append(day_log.model_dump())
    
    state["messages"].append({
        "role": "system",
        "content": f"[Day {env.day}] environment_settle_node: 環境已更新",
        "timestamp": datetime.now().isoformat(),
    })
    
    print(f"  [Settle] Day {env.day}: {env.format_short()}")
    
    return state


# --- 節點 4: day_advance_node (日期推進節點) ---

def day_advance_node(state: SimulationState) -> SimulationState:
    """
    日期推進節點：將模擬日推進一天
    
    對應舊版 timeLine.py 的 ct_dt += datetime.timedelta(days=1)
    """
    env = state["environment"]
    config = state["config"]
    
    # 推進日期
    env.day += 1
    current_date = datetime.strptime(config.start_date, "%Y-%m-%d")
    env.date = (current_date + timedelta(days=env.day - 1)).strftime("%Y-%m-%d")
    
    # 判斷是否繼續
    if env.day > config.max_days:
        state["should_continue"] = False
    else:
        state["should_continue"] = True
        # 重置當日日誌
        state["current_day_log"] = {
            "day": env.day,
            "date": env.date,
            "actions": [],
            "notable_events": [],
            "emergent_phenomena": [],
        }
    
    print(f"  [Advance] → Day {env.day}/{config.max_days} "
          f"({'繼續' if state['should_continue'] else '結束'})")
    
    return state


# ============================================================
#  第三部分：條件邊 (Conditional Edge)
#  控制循環：繼續 → perceive_node / 結束 → END
# ============================================================

def should_continue_simulation(state: SimulationState) -> str:
    """
    條件路由函數：判斷模擬是否應該繼續
    
    對應舊版 timeLine.py 的 while ct_dt <= ed_dt:
    """
    if state["should_continue"]:
        return "perceive"
    else:
        return "end"


# ============================================================
#  第四部分：構建完整的模擬圖 (build_simulation_graph)
#  這是整個系統的入口點
# ============================================================

def build_simulation_graph(
    config: SimulationConfig,
    llm: Optional[ChatOpenAI] = None,
    tool_registry: Optional[ToolRegistry] = None,
    memory_manager: Optional[MemoryManager] = None,
) -> StateGraph:
    """
    構建模擬狀態圖 — 整個 Meta-Simulation Platform 的核心
    
    對比舊版 timeLine.py：
    - 舊版：一個 while 迴圈包含所有邏輯，難以擴展
    - 新版：LangGraph StateGraph，節點分離、可測試、可視化
    
    圖結構:
    
        ┌─────────────┐
        │  perceive   │ ← 每天開始：檢索記憶
        └──────┬──────┘
               │
        ┌──────▼──────┐
        │agent_action │ ← 智能體決策 + 工具調用
        └──────┬──────┘
               │
        ┌──────▼──────────┐
        │environment_settle│ ← 環境結算 + 日誌生成
        └──────┬──────────┘
               │
        ┌──────▼──────┐
        │ day_advance │ ← 推進日期
        └──────┬──────┘
               │
          ┌────▼────┐
          │ 繼續?   │
          ├─YES: ───┼──→ perceive (循環)
          └─NO: ────┼──→ END
                     
    Args:
        config: 模擬配置
        llm: DeepSeek LLM 實例 (可選，預設自動創建)
        tool_registry: 工具註冊表 (可選)
        memory_manager: 記憶管理器 (可選)
    
    Returns:
        已編譯的 LangGraph StateGraph
    """
    # 初始化依賴（若未提供則使用預設值）
    if llm is None:
        llm = create_deepseek_llm(temperature=config.llm_temperature)
    
    if tool_registry is None:
        tool_registry = create_default_tool_registry()
    
    if memory_manager is None:
        memory_manager = create_memory_manager()
        memory_manager.init_simulation(config.simulation_id)
    
    # --- 構建圖 ---
    workflow = StateGraph(SimulationState)
    
    # 添加節點
    # 使用 functools.partial 或 lambda 來傳遞額外依賴
    workflow.add_node("perceive", lambda s: perceive_node(s, memory_manager))
    workflow.add_node(
        "agent_action",
        lambda s: asyncio.run(agent_action_node(s, llm, tool_registry, memory_manager))
    )
    workflow.add_node("environment_settle", lambda s: environment_settle_node(s, llm))
    workflow.add_node("day_advance", day_advance_node)
    
    # 設置入口點
    workflow.set_entry_point("perceive")
    
    # 設置邊 (串聯節點)
    workflow.add_edge("perceive", "agent_action")
    workflow.add_edge("agent_action", "environment_settle")
    workflow.add_edge("environment_settle", "day_advance")
    
    # 設置條件邊 (循環控制)
    workflow.add_conditional_edges(
        "day_advance",
        should_continue_simulation,
        {
            "perceive": "perceive",
            "end": END,
        }
    )
    
    # 編譯圖 (使用 MemorySaver 支援檢查點)
    checkpointer = MemorySaver()
    compiled_graph = workflow.compile(checkpointer=checkpointer)
    
    print(f"\n{'='*60}")
    print(f"  [BUILD] 模擬圖已構建完成")
    print(f"  模擬 ID: {config.simulation_id}")
    print(f"  標題: {config.title}")
    print(f"  天數: {config.max_days}")
    print(f"  智能體數: {len(config.agents)}")
    print(f"  工具數: {len(tool_registry.get_all_tools())}")
    print(f"{'='*60}\n")
    
    return compiled_graph


# ============================================================
#  第五部分：簡化的執行入口 (Run Simulation)
# ============================================================

async def run_simulation(
    config: SimulationConfig,
    llm: Optional[ChatOpenAI] = None,
    tool_registry: Optional[ToolRegistry] = None,
    memory_manager: Optional[MemoryManager] = None,
) -> SimulationResult:
    """
    執行一次完整的模擬
    
    這是使用者的主要 API 入口。對應舊版執行 python timeLine.py。
    
    Args:
        config: 模擬配置
        llm: LLM 實例
        tool_registry: 工具註冊表
        memory_manager: 記憶管理器
    
    Returns:
        SimulationResult: 結構化模擬結果
    """
    # 初始化依賴
    if llm is None:
        llm = create_deepseek_llm(temperature=config.llm_temperature)
    
    if tool_registry is None:
        tool_registry = create_default_tool_registry()
    
    if memory_manager is None:
        memory_manager = create_memory_manager()
        memory_manager.init_simulation(config.simulation_id)
    
    # 構建並執行圖
    graph = build_simulation_graph(
        config=config,
        llm=llm,
        tool_registry=tool_registry,
        memory_manager=memory_manager,
    )
    
    initial_state = create_initial_state(config)
    
    print(f"[START] 開始模擬: {config.title}")
    print(f"   日期範圍: {config.start_date} → "
          f"Day {config.max_days}")
    print(f"   智能體: {[a.name for a in config.agents]}")
    print(f"{'-'*60}")
    
    # 執行圖直到結束
    final_state = None
    async for event in graph.astream(
        initial_state,
        config={"configurable": {"thread_id": config.simulation_id}}
    ):
        # event 包含每個節點的輸出
        for node_name, node_output in event.items():
            if node_name in ["perceive", "agent_action", "environment_settle", "day_advance"]:
                pass  # 節點內部已有 print 輸出
        final_state = node_output if node_output else final_state
    
    print(f"\n{'-'*60}")
    print(f"[END] 模擬結束: Day {config.max_days}/{config.max_days}")
    
    # 提取最終狀態
    if final_state is None:
        # 若圖未能正常完成，嘗試從 initial_state 構建結果
        final_state = initial_state
    
    env = final_state.get("environment", config.initial_environment)
    day_logs = final_state.get("day_logs", [])
    
    # --- 生成最終摘要 (對應舊版 GF.end()) ---
    summary_prompt = f"""
請總結以下沙盤模擬的結果：

模擬標題：{config.title}
模擬描述：{config.description}
總天數：{config.max_days}
參與智能體：{', '.join([a.name + '(' + a.role + ')' for a in config.agents])}

最終環境狀態（真實單位）：
{env.format_for_llm()}

總行動數：{sum(len(log.get('actions', [])) for log in day_logs)}

請用繁體中文撰寫以下內容。注意：你是一個模擬觀察者，不是政策顧問，不要給出政策建議。
1. 一個 3-5 句的執行摘要（描述模擬中觀察到的關鍵動態）
2. 列出 2-3 個從模擬數據中觀察到的浮現現象 (emergent behaviors)。每個現象必須引用具體的智能體行動或指標變化作為證據
3. 模擬觀察 (Simulation Observations)：基於數據，指出哪些利害相關者受益、哪些受損、哪些指標出現非預期變化
"""
    
    try:
        summary_response = llm.invoke([HumanMessage(content=summary_prompt)])
        executive_summary = summary_response.content.strip()
    except Exception as e:
        executive_summary = f"模擬完成。總共模擬了 {config.max_days} 天，{len(config.agents)} 個智能體參與。"
    
    # 構建結果
    result = SimulationResult(
        simulation_id=config.simulation_id,
        total_days_simulated=config.max_days,
        all_day_logs=[DayLog(**log) for log in day_logs],
        executive_summary=executive_summary,
        agent_final_states={
            agent_id: f"情緒: {state.get('emotion', 'unknown')}"
            for agent_id, state in final_state.get("agent_states", {}).items()
        }
    )
    
    return result


# ============================================================
#  第六部分：Creator Agent (從自然語言生成 SimulationConfig)
#  這是整個系統的「魔法入口」
# ============================================================

def create_simulation_from_natural_language(
    user_input: str,
    llm: Optional[ChatOpenAI] = None,
    tool_registry: Optional[ToolRegistry] = None,
) -> SimulationConfig:
    """
    Creator Agent：從自然語言描述自動生成 SimulationConfig
    
    這是對應舊版 timeLine.py 中最核心的創新：
    - 舊版：需要手動設定 Aim，手動編寫 fact.txt
    - 新版：只需一句話，LLM 自動生成所有配置
    
    使用範例：
        config = create_simulation_from_natural_language(
            "模擬深水埗夜市在農曆新年期間的小販與城管互動"
        )
    
    Args:
        user_input: 用戶的自然語言場景描述
        llm: LLM 實例
        tool_registry: 工具註冊表
    
    Returns:
        自動生成的 SimulationConfig
    """
    if llm is None:
        llm = create_deepseek_llm(temperature=0.8)  # Creator 需要更高創造性
    
    if tool_registry is None:
        tool_registry = create_default_tool_registry()
    
    tools_summary = tool_registry.get_tools_summary_for_llm()
    
    creator_prompt = f"""
你是一個專業的社會模擬場景設計師（Creator Agent）。
請根據用戶的場景描述，生成一個完整的 SimulationConfig。

{tools_summary}

## 用戶場景描述
{user_input}

## 你的任務
請以 JSON 格式（不要包含 markdown 代碼塊標記）生成以下配置：

{{
  "simulation_id": "一個唯一的英文 ID，如 ssp_night_market_2025",
  "title": "模擬標題（繁體中文）",
  "description": "詳細場景描述（繁體中文，2-3句）",
  "max_days": 模擬天數 (7-30，根據場景複雜度決定),
  "start_date": "開始日期 YYYY-MM-DD",
  "initial_environment": {{
    "day": 1,
    "noise_level": 0.0-1.0,
    "crowd_density": 0.0-1.0,
    "economic_activity": 0.0-1.0,
    "social_stability": 0.0-1.0,
    "policy_pressure": 0.0-1.0,
    "weather": "sunny|cloudy|rainy|stormy|hot|cold",
    "is_holiday": true/false,
    "special_event": null 或 "特殊事件描述",
    "domain_context": "相關的領域知識摘要"
  }},
  "agents": [
    {{
      "agent_id": "唯一英文 ID",
      "name": "名字（繁體中文或英文）",
      "role": "角色（繁體中文）",
      "background": "詳細背景故事（繁體中文，2-3句）",
      "core_motivation": "核心動機（繁體中文）",
      "personality_traits": ["特質1", "特質2", "特質3"],
      "action_thresholds": {{
        "noise_tolerance": 0.0-1.0,
        "crowd_pressure_threshold": 0.0-1.0,
        "economic_stress_threshold": 0.0-1.0,
        "social_interaction_drive": 0.0-1.0
      }},
      "initial_emotion": "neutral|happy|anxious|angry|fearful|excited",
      "available_tools": ["工具名稱1", "工具名稱2"],
      "initial_memory": "初始記憶（繁體中文，1-2句）或 null"
    }}
  ],
  "global_tools": ["check_weather", "post_complaint"],
  "llm_model": "deepseek-chat",
  "llm_temperature": 0.7
}}

## 重要規則
1. 智能體數量應在 3-8 人之間，且需涵蓋不同角色面向
2. 每個智能體的 background 和 core_motivation 必須具體、有區分度
3. 根據角色合理分配 available_tools：例如小販/居民用 post_complaint，遊客/活動策劃者用 check_weather
4. action_thresholds 需根據角色特質設定：例如小販的 noise_tolerance 應較高，居民的較低
5. 所有描述文字使用繁體中文
6. 直接返回 JSON，不要包在 ```json 或其他標記中
"""
    
    try:
        response = llm.invoke([HumanMessage(content=creator_prompt)])
        response_text = response.content.strip()
        
        # 清理可能的 markdown 標記
        if response_text.startswith("```"):
            lines = response_text.split("\n")
            response_text = "\n".join(lines[1:-1])
        
        config_data = json.loads(response_text)
        
        # 將 JSON 轉換為 SimulationConfig
        config = SimulationConfig(**config_data)
        
        print(f"\n{'='*60}")
        print(f"  [CREATED] Creator Agent 已生成模擬配置")
        print(f"  標題: {config.title}")
        print(f"  天數: {config.max_days}")
        print(f"  智能體: {[a.name for a in config.agents]}")
        print(f"{'='*60}\n")
        
        return config
        
    except Exception as e:
        print(f"[ERROR] Creator Agent 生成失敗: {e}")
        print("   將使用預設配置...")
        
        # 返回一個簡單的預設配置
        return SimulationConfig(
            simulation_id="default_sim",
            title=user_input[:50],
            description=user_input,
            max_days=7,
            start_date=datetime.now().strftime("%Y-%m-%d"),
            agents=[
                AgentPersona(
                    agent_id="agent_01",
                    name="預設智能體",
                    role="參與者",
                    background="一個普通的模擬參與者",
                    core_motivation="觀察與互動",
                    available_tools=["check_weather"],
                )
            ],
        )


# ============================================================
#  自我測試 (開發期間用)
# ============================================================

if __name__ == "__main__":
    import asyncio
    
    print("=== LangGraph 核心引擎自我測試 ===\n")
    
    # 建立一個簡單的測試配置
    test_config = SimulationConfig(
        simulation_id="test_engine_001",
        title="深水埗夜市噪音測試",
        description="測試引擎基本功能的小規模模擬",
        max_days=3,  # 只模擬 3 天以節省 API 調用
        start_date="2008-07-01",
        initial_environment=EnvironmentState(
            day=1,
            date="2008-07-01",
            noise_level=0.6,
            crowd_density=0.5,
            economic_activity=0.5,
            social_stability=0.7,
            policy_pressure=0.3,
            weather=WeatherCondition.SUNNY,
            domain_context="深水埗是香港九龍的傳統社區，以夜市和地道美食聞名。",
            metric_definitions={
                m.id: m.model_dump() for m in get_metric_template("night_market")
            },
            metrics={
                m.id: m.baseline for m in get_metric_template("night_market")
            },
        ),
        agents=[
            AgentPersona(
                agent_id="hawker_01",
                name="陳伯",
                role="熟食小販",
                background="在深水埗桂林街經營魚蛋檔30年，與街坊關係密切",
                core_motivation="養活一家三口，維持生計",
                personality_traits=["勤奮", "保守", "易怒"],
                action_thresholds=ActionThreshold(
                    noise_tolerance=0.6,
                    social_interaction_drive=0.8,
                ),
                initial_emotion="neutral",
                available_tools=["post_complaint"],
                initial_memory="我在桂林街賣魚蛋30年，見證了夜市從繁榮到現在的轉變。",
            ),
            AgentPersona(
                agent_id="tourist_01",
                name="Mary",
                role="外國遊客",
                background="來自英國的背包客，第一次來香港，對地道文化充滿好奇",
                core_motivation="探索最地道的香港夜市文化",
                personality_traits=["好奇", "友善", "冒險"],
                action_thresholds=ActionThreshold(
                    noise_tolerance=0.4,
                    social_interaction_drive=0.9,
                ),
                initial_emotion="excited",
                available_tools=["check_weather"],
                initial_memory="聽說深水埗夜市是香港最地道的，一定要來試試。",
            ),
        ],
    )
    
    # 執行模擬
    async def main():
        result = await run_simulation(test_config)
        print(f"\n[RESULT] 模擬結果摘要:")
        print(f"   執行摘要: {result.executive_summary[:200]}...")
        print(f"   總日誌數: {len(result.all_day_logs)}")
    
    asyncio.run(main())
