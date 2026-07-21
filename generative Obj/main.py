"""
============================================================
  互動式模擬規劃器 - Interactive Simulation Planner
============================================================
  解決兩個核心需求：
  
  1. 規模控制 — 讓使用者清楚看到每個參數如何影響模擬成本與深度
  2. 多階段互動 — 系統提出計劃 → 使用者審查調整 → 確認後執行
  
  使用方式:
    python main.py --plan    (互動規劃模式)
    python main.py --quick "場景描述"  (一句話快速啟動)
============================================================
"""

import asyncio
import sys
import json
import os
from datetime import datetime
from typing import Optional

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from models import SimulationConfig, EnvironmentState, AgentPersona, ActionThreshold, SimulationResult
from engine import create_deepseek_llm, run_simulation, create_simulation_from_natural_language
from memory_manager import create_memory_manager
from tools import create_default_tool_registry
from data_pipeline import PopulationProfiler, GovDataPipeline


# ============================================================
#  輔助函數
# ============================================================

# 區域英文對照（用於 ChromaDB collection name）
_DISTRICT_EN = {
    "深水埗": "ssp", "旺角": "mk", "中環": "central", "元朗": "yl",
    "尖沙咀": "tst", "銅鑼灣": "cwb", "觀塘": "kt", "荃灣": "tw",
}

def _sanitize_district(district: str) -> str:
    """將中文區域名轉為合法 ID（ChromaDB 只接受 [a-zA-Z0-9._-]）"""
    return _DISTRICT_EN.get(district, district.encode("ascii", errors="ignore").decode() or "hk")


# ============================================================
#  規模參數定義
# ============================================================

SIM_SCALES = {
    "tiny": {
        "label": "微型 (快速測試)",
        "agents": 3,
        "days": 3,
        "memory_depth": 2,
        "gov_datasets": 2,
        "tool_per_agent": 1,
        "estimated_tokens": 15000,
        "estimated_cost_hkd": 0.03,
        "estimated_time_sec": 15,
    },
    "small": {
        "label": "小型 (展示用)",
        "agents": 5,
        "days": 5,
        "memory_depth": 3,
        "gov_datasets": 3,
        "tool_per_agent": 1,
        "estimated_tokens": 35000,
        "estimated_cost_hkd": 0.07,
        "estimated_time_sec": 35,
    },
    "medium": {
        "label": "中型 (預設，適合比賽展示)",
        "agents": 8,
        "days": 7,
        "memory_depth": 5,
        "gov_datasets": 5,
        "tool_per_agent": 2,
        "estimated_tokens": 70000,
        "estimated_cost_hkd": 0.14,
        "estimated_time_sec": 70,
    },
    "large": {
        "label": "大型 (深度模擬)",
        "agents": 12,
        "days": 14,
        "memory_depth": 7,
        "gov_datasets": 8,
        "tool_per_agent": 2,
        "estimated_tokens": 200000,
        "estimated_cost_hkd": 0.40,
        "estimated_time_sec": 200,
    },
    "max": {
        "label": "最大 (完整研究級別)",
        "agents": 20,
        "days": 30,
        "memory_depth": 10,
        "gov_datasets": 9,
        "tool_per_agent": 3,
        "estimated_tokens": 700000,
        "estimated_cost_hkd": 1.50,
        "estimated_time_sec": 600,
    },
}


# ============================================================
#  成本估算器
# ============================================================

def estimate_cost(agents: int, days: int, tools_per_agent: int = 2, with_gov_data: bool = True) -> dict:
    """
    根據參數估算 API 調用次數與成本
    
    計算邏輯：
    - 每次模擬日: agents 次 agent_action + 1 次 settle + 1 次 perceive(無API)
    - 最終摘要: 1 次
    - Creator Agent 生成: 1 次
    - Gov data 不計入 API（是免費的開放數據）
    """
    daily_agent_calls = agents * days      # 每個智能體每天一次決策
    daily_settle_calls = days               # 每天一次環境結算摘要
    final_summary_calls = 1                 # 最終摘要
    creator_calls = 1                       # Creator Agent 生成配置
    
    total_calls = daily_agent_calls + daily_settle_calls + final_summary_calls + creator_calls
    
    # Token 估算（每次調用平均）
    avg_agent_input = 600 + (tools_per_agent * 100)
    avg_agent_output = 150
    avg_settle_input = 300
    avg_settle_output = 200
    avg_final_input = 500
    avg_final_output = 400
    avg_creator_input = 1500
    avg_creator_output = 1000
    
    total_input_tokens = (
        daily_agent_calls * avg_agent_input +
        daily_settle_calls * avg_settle_input +
        final_summary_calls * avg_final_input +
        creator_calls * avg_creator_input
    )
    total_output_tokens = (
        daily_agent_calls * avg_agent_output +
        daily_settle_calls * avg_settle_output +
        final_summary_calls * avg_final_output +
        creator_calls * avg_creator_output
    )
    
    # DeepSeek 定價 (USD per 1M tokens)
    input_cost = total_input_tokens / 1_000_000 * 0.27
    output_cost = total_output_tokens / 1_000_000 * 1.10
    total_cost_usd = input_cost + output_cost
    total_cost_hkd = total_cost_usd * 7.8
    
    # 時間估算（每調用 ~1.5 秒）
    estimated_time = total_calls * 1.5
    
    return {
        "total_api_calls": total_calls,
        "total_input_tokens": total_input_tokens,
        "total_output_tokens": total_output_tokens,
        "cost_usd": round(total_cost_usd, 4),
        "cost_hkd": round(total_cost_hkd, 2),
        "estimated_seconds": round(estimated_time, 0),
        "breakdown": {
            "agent_actions": f"{daily_agent_calls} 次 (={agents}人 × {days}天)",
            "daily_summaries": f"{daily_settle_calls} 次 (={days}天 × 1)",
            "final_summary": "1 次",
            "creator_agent": "1 次 (生成智能體配置)",
        }
    }


# ============================================================
#  互動式規劃器
# ============================================================

class SimulationPlanner:
    """
    互動式模擬規劃器
    
    多階段互動流程：
    Phase 1: 收集場景描述
    Phase 2: 分析複雜度 → 推薦規模
    Phase 3: 確認/調整各項參數
    Phase 4: 確認成本 → 執行
    """
    
    def __init__(self):
        self.scenario: str = ""
        self.district: str = "深水埗"
        self.scale: str = "medium"
        self.agents: int = 8
        self.days: int = 7
        self.memory_depth: int = 5
        self.tools_per_agent: int = 2
        self.with_gov_data: bool = True
        self.with_population_constraints: bool = True
        self.gov_datasets: int = 5
        self._confirmed: bool = False
    
    # ------------------------------------------------------------------
    #  Phase 1: 場景收集
    # ------------------------------------------------------------------
    
    async def phase1_collect_scenario(self) -> str:
        """Phase 1: 收集場景描述"""
        print(f"\n{'='*70}")
        print(f"  🎯 Phase 1/4: 場景描述")
        print(f"{'='*70}")
        print(f"\n  請描述你想模擬的社會場景。")
        print(f"  你可以描述：地點、政策、參與者、時間範圍...")
        print(f"\n  示例：")
        print(f"    - 深水埗桂林街夜市噪音新規對小販生計的影響")
        print(f"    - 模擬取消旺角行人專用區後，街頭表演者與商戶的互動")
        print(f"    - 農曆新年期間深水埗夜市的人流管控政策效果")
        print()
        
        scenario = input("  場景描述 > ").strip()
        
        if not scenario:
            scenario = "深水埗夜市噪音政策對小販與居民的影響"
            print(f"  → 使用預設: {scenario}")
        
        self.scenario = scenario
        
        # 詢問區域
        print(f"\n  目標區域？")
        district = input(f"  [預設: 深水埗] > ").strip()
        if district:
            self.district = district
        
        print(f"\n  ✅ 場景: {self.scenario[:60]}...")
        print(f"  ✅ 區域: {self.district}")
        
        return self.scenario
    
    # ------------------------------------------------------------------
    #  Phase 2: 規模推薦
    # ------------------------------------------------------------------
    
    async def phase2_recommend_scale(self) -> dict:
        """Phase 2: 分析場景複雜度 → 推薦規模 → 顯示成本"""
        print(f"\n{'='*70}")
        print(f"  📊 Phase 2/4: 規模分析與成本預估")
        print(f"{'='*70}")
        
        # 分析場景複雜度（基於關鍵字）
        complexity_keywords = {
            "政策": 2, "噪音": 1, "經濟": 2, "小販": 2, "居民": 1,
            "遊客": 1, "交通": 2, "房屋": 2, "衝突": 3, "抗議": 3,
            "農曆新年": 2, "國慶": 2, "颱風": 1, "疫情": 3,
            "多個": 2, "所有": 3, "長期": 3, "大規模": 3,
        }
        
        complexity_score = 1  # 基礎分
        for kw, weight in complexity_keywords.items():
            if kw in self.scenario:
                complexity_score += weight
        
        # 根據複雜度推薦規模
        if complexity_score <= 3:
            recommended = "small"
        elif complexity_score <= 6:
            recommended = "medium"
        elif complexity_score <= 10:
            recommended = "large"
        else:
            recommended = "max"
        
        print(f"\n  場景複雜度分析：")
        print(f"  - 複雜度分數: {complexity_score}")
        print(f"  - 推薦規模: {SIM_SCALES[recommended]['label']}")
        
        # 顯示所有規模選項
        print(f"\n  可用規模選項：")
        print(f"  {'規模':8s} {'智能體':5s} {'天數':5s} {'API調用':8s} {'時間':8s} {'成本(HKD)':>10s}")
        print(f"  {'-'*55}")
        
        for key, s in SIM_SCALES.items():
            marker = " ← 推薦" if key == recommended else ""
            cost = estimate_cost(s["agents"], s["days"], s["tool_per_agent"])
            print(f"  {s['label']:10s} {s['agents']:3d}人 {s['days']:3d}天 "
                  f"{cost['total_api_calls']:5d}次 {cost['estimated_seconds']:5.0f}秒 "
                  f"HK${cost['cost_hkd']:7.2f}{marker}")
        
        # 讓使用者選擇
        print(f"\n  請選擇規模：")
        print(f"    1 = 微型  2 = 小型  3 = 中型(推薦)  4 = 大型  5 = 最大")
        print(f"    C = 自訂參數")
        
        choice = input(f"  [預設: 3] > ").strip().lower()
        
        if choice == "c":
            await self._custom_config()
        elif choice in ["1", "2", "3", "4", "5"]:
            scale_keys = ["tiny", "small", "medium", "large", "max"]
            self.scale = scale_keys[int(choice) - 1]
            s = SIM_SCALES[self.scale]
            self.agents = s["agents"]
            self.days = s["days"]
            self.memory_depth = s["memory_depth"]
            self.gov_datasets = s["gov_datasets"]
            self.tools_per_agent = s["tool_per_agent"]
        else:
            self.scale = recommended
            s = SIM_SCALES[self.scale]
            self.agents = s["agents"]
            self.days = s["days"]
            self.memory_depth = s["memory_depth"]
            self.gov_datasets = s["gov_datasets"]
            self.tools_per_agent = s["tool_per_agent"]
        
        # 計算最終成本
        cost = estimate_cost(self.agents, self.days, self.tools_per_agent, self.with_gov_data)
        
        print(f"\n  📋 目前配置：")
        print(f"  ┌─────────────────────────────────┐")
        print(f"  │ 智能體數量:     {self.agents:3d} 人            │")
        print(f"  │ 模擬天數:       {self.days:3d} 天            │")
        print(f"  │ 記憶深度:       {self.memory_depth:3d} 條/人       │")
        print(f"  │ 每智能體工具:   {self.tools_per_agent:3d} 個            │")
        print(f"  │ 政府數據集:     {self.gov_datasets:3d} 個            │")
        print(f"  │ 人口約束:       {'是' if self.with_population_constraints else '否':3s}              │")
        print(f"  ├─────────────────────────────────┤")
        print(f"  │ API 總調用:     {cost['total_api_calls']:3d} 次           │")
        print(f"  │ 預估 Token:     {cost['total_input_tokens']+cost['total_output_tokens']:,.0f}          │")
        print(f"  │ 預估時間:       {cost['estimated_seconds']:4.0f} 秒          │")
        print(f"  │ 預估成本:       HK$ {cost['cost_hkd']:.2f}         │")
        print(f"  └─────────────────────────────────┘")
        
        return cost
    
    async def _custom_config(self):
        """自訂參數"""
        print(f"\n  --- 自訂參數 ---")
        
        try:
            agents = input(f"  智能體數量 [預設: 8]: ").strip()
            self.agents = int(agents) if agents else 8
            self.agents = max(2, min(30, self.agents))
        except ValueError:
            self.agents = 8
        
        try:
            days = input(f"  模擬天數 [預設: 7]: ").strip()
            self.days = int(days) if days else 7
            self.days = max(1, min(365, self.days))
        except ValueError:
            self.days = 7
        
        try:
            depth = input(f"  記憶深度(每智能體檢索幾條歷史) [預設: 5]: ").strip()
            self.memory_depth = int(depth) if depth else 5
        except ValueError:
            self.memory_depth = 5
        
        try:
            datasets = input(f"  政府數據集數量(1-9) [預設: 5]: ").strip()
            self.gov_datasets = int(datasets) if datasets else 5
        except ValueError:
            self.gov_datasets = 5
        
        gov = input(f"  注入政府開放數據? (Y/n): ").strip().lower()
        self.with_gov_data = gov != "n"
        
        pop = input(f"  使用人口約束生成智能體? (Y/n): ").strip().lower()
        self.with_population_constraints = pop != "n"
        
        self.scale = "custom"
    
    # ------------------------------------------------------------------
    #  Phase 3: 確認調整
    # ------------------------------------------------------------------
    
    async def phase3_confirm(self) -> bool:
        """Phase 3: 最終確認或調整"""
        print(f"\n{'='*70}")
        print(f"  ✅ Phase 3/4: 確認配置")
        print(f"{'='*70}")
        
        print(f"\n  配置摘要：")
        print(f"  場景: {self.scenario[:80]}")
        print(f"  區域: {self.district}")
        print(f"  規模: {self.scale.upper()}")
        print(f"  智能體: {self.agents} 人 × {self.days} 天")
        
        cost = estimate_cost(self.agents, self.days, self.tools_per_agent)
        print(f"  成本: HK$ {cost['cost_hkd']:.2f} | ~{cost['estimated_seconds']:.0f} 秒")
        
        print(f"\n  請確認：")
        print(f"    Y = 開始執行模擬")
        print(f"    N = 取消")
        print(f"    A = 重新調整參數")
        print(f"    S = 切換規模")
        
        choice = input(f"\n  [Y/n/a/s] > ").strip().lower()
        
        if choice == "a":
            await self._custom_config()
            cost = estimate_cost(self.agents, self.days, self.tools_per_agent)
            print(f"\n  更新後成本: HK$ {cost['cost_hkd']:.2f}")
            return await self.phase3_confirm()
        elif choice == "s":
            await self.phase2_recommend_scale()
            return await self.phase3_confirm()
        elif choice == "n":
            print(f"\n  ❌ 模擬已取消。")
            return False
        else:
            self._confirmed = True
            return True
    
    # ------------------------------------------------------------------
    #  Phase 4: 執行
    # ------------------------------------------------------------------
    
    async def phase4_execute(self) -> Optional[SimulationResult]:
        """Phase 4: 執行模擬"""
        if not self._confirmed:
            print(f"\n  ❌ 尚未確認配置，無法執行。")
            return None
        
        print(f"\n{'='*70}")
        print(f"  🚀 Phase 4/4: 執行模擬")
        print(f"{'='*70}")
        
        start_time = datetime.now()
        
        # Step 1: 初始化
        print(f"\n  [1/4] 初始化基礎設施...")
        llm = create_deepseek_llm(temperature=0.7)
        tool_registry = create_default_tool_registry()
        memory_manager = create_memory_manager(persist_dir="./chroma_data")
        sim_id = f"sim_{_sanitize_district(self.district)}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        memory_manager.init_simulation(sim_id)
        
        # Step 2: 政府數據注入
        domain_context = ""
        pop_constraints = ""
        
        if self.with_gov_data or self.with_population_constraints:
            print(f"\n  [2/4] 注入政府數據...")
            profiler = PopulationProfiler()
            profile = profiler.profile_district(self.district)
            
            if self.with_population_constraints:
                pop_constraints = profiler.build_creator_prompt_context(
                    profile, self.scenario, self.agents
                )
            
            if self.with_gov_data:
                pipeline = GovDataPipeline()
                pipeline.discover_relevant_datasets(self.scenario, self.district)
                await pipeline.fetch_all_relevant()
                domain_context = pipeline.build_domain_context(self.scenario)
                pipeline.embed_to_memory(memory_manager, sim_id)
        
        # Step 3: Creator Agent 生成配置
        print(f"\n  [3/4] Creator Agent 生成智能體配置...")
        
        enhanced_scenario = self.scenario
        if pop_constraints:
            enhanced_scenario += f"\n\n{pop_constraints}"
        if domain_context:
            enhanced_scenario += f"\n\n領域知識：\n{domain_context[:2000]}"
        
        try:
            config = create_simulation_from_natural_language(
                user_input=enhanced_scenario,
                llm=llm,
                tool_registry=tool_registry,
            )
            config.max_days = self.days
            config.simulation_id = sim_id
            config.initial_environment.domain_context = domain_context
            
            print(f"\n  生成智能體列表：")
            for i, agent in enumerate(config.agents, 1):
                print(f"    {i}. {agent.name} ({agent.role})")
                print(f"       動機: {agent.core_motivation[:50]}")
                print(f"       工具: {agent.available_tools}")
        except Exception as e:
            print(f"  Creator Agent 失敗: {e}")
            print(f"  使用人口約束生成 fallback 配置...")
            config = self._build_fallback(sim_id, domain_context)
        
        # Step 4: 執行模擬
        print(f"\n  [4/4] 執行 LangGraph 模擬...")
        
        # 確保 memory 正確初始化
        memory_manager.init_simulation(sim_id)
        
        result = await run_simulation(
            config=config,
            llm=llm,
            tool_registry=tool_registry,
            memory_manager=memory_manager,
        )
        
        elapsed = (datetime.now() - start_time).total_seconds()
        
        # 輸出最終結果
        print(f"\n{'='*70}")
        print(f"  🏁 模擬完成")
        print(f"  實際耗時: {elapsed:.1f} 秒")
        print(f"  智能體: {len(config.agents)} 人 × {config.max_days} 天")
        print(f"{'='*70}")
        
        print(f"\n{'─'*70}")
        print(f"  📊 模擬結果摘要")
        print(f"{'─'*70}")
        print(f"\n{result.executive_summary}")
        print(f"\n{'─'*70}")
        
        # 可選：儲存 JSON
        save = input(f"\n  儲存結果為 JSON? (y/N): ").strip().lower()
        if save == "y":
            filename = f"simulation_result_{sim_id}.json"
            with open(filename, "w", encoding="utf-8") as f:
                json.dump(result.model_dump(), f, ensure_ascii=False, indent=2)
            print(f"  ✅ 已儲存至: {filename}")
        
        return result
    
    def _build_fallback(self, sim_id: str, domain_context: str = "") -> SimulationConfig:
        """Fallback: 根據人口約束生成配置"""
        profiler = PopulationProfiler()
        profile = profiler.profile_district(self.district)
        constraints = profiler.generate_agent_constraints(profile, self.agents, "night_market")
        
        role_templates = {
            "hawker_vendor": {"role": "熟食小販", "motivation": "在夜市擺檔謀生", "tools": ["post_complaint"], "noise_tolerance": 0.7},
            "unemployed_retired": {"role": "退休長者", "motivation": "關注社區變化", "tools": ["post_complaint"], "noise_tolerance": 0.3},
            "retail_worker": {"role": "零售店員", "motivation": "夜市帶動人流", "tools": ["check_weather"], "noise_tolerance": 0.5},
            "service_worker": {"role": "食肆員工", "motivation": "夜市帶動生意", "tools": ["check_weather"], "noise_tolerance": 0.6},
            "tourist": {"role": "外來遊客", "motivation": "探索地道文化", "tools": ["check_weather"], "noise_tolerance": 0.4},
            "government_staff": {"role": "城管人員", "motivation": "維持秩序", "tools": ["post_complaint", "check_weather"], "noise_tolerance": 0.8},
            "office_worker": {"role": "上班族", "motivation": "下班後逛夜市", "tools": ["check_weather"], "noise_tolerance": 0.5},
            "other": {"role": "居民", "motivation": "日常生活", "tools": [], "noise_tolerance": 0.5},
        }
        
        surnames = ["陳", "李", "張", "黃", "林", "何", "王", "劉", "吳", "周"]
        suffixes = ["伯", "叔", "姐", "姨", "生", "太", "哥", "嫂"]
        
        agents = []
        idx = 0
        for c in constraints:
            t = role_templates.get(c["role_category"], role_templates["other"])
            for _ in range(min(c["suggested_count"], 3)):
                if idx >= self.agents:
                    break
                agents.append(AgentPersona(
                    agent_id=f"agent_{idx+1:02d}",
                    name=f"{surnames[idx%10]}{suffixes[idx%8]}",
                    role=t["role"],
                    background=f"{self.district}{t['motivation']}",
                    core_motivation=t["motivation"],
                    personality_traits=["勤奮", "務實"],
                    action_thresholds=ActionThreshold(noise_tolerance=t["noise_tolerance"]),
                    available_tools=t["tools"],
                ))
                idx += 1
        
        return SimulationConfig(
            simulation_id=sim_id,
            title=f"{self.district}{self.scenario[:30]}",
            description=self.scenario,
            max_days=self.days,
            start_date="2024-01-01",
            initial_environment=EnvironmentState(
                day=1, date="2024-01-01",
                domain_context=domain_context,
            ),
            agents=agents,
        )


# ============================================================
#  主入口
# ============================================================

async def interactive_mode():
    """互動規劃模式"""
    planner = SimulationPlanner()
    
    await planner.phase1_collect_scenario()
    await planner.phase2_recommend_scale()
    confirmed = await planner.phase3_confirm()
    
    if confirmed:
        await planner.phase4_execute()


async def quick_mode(scenario: str, days: int = 5, agents: int = 8):
    """快速模式：一句話啟動"""
    from engine import create_deepseek_llm, run_simulation, create_simulation_from_natural_language
    
    print(f"\n[QUICK] {scenario} ({agents}人 × {days}天)")
    
    llm = create_deepseek_llm(temperature=0.8)
    tool_registry = create_default_tool_registry()
    memory_manager = create_memory_manager()
    
    config = create_simulation_from_natural_language(scenario, llm, tool_registry)
    config.max_days = days
    
    result = await run_simulation(config, llm, tool_registry, memory_manager)
    
    print(f"\n{'='*70}")
    print(result.executive_summary)
    print(f"{'='*70}")
    
    return result


async def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Meta-Simulation Platform")
    parser.add_argument("scenario", nargs="?", default=None)
    parser.add_argument("--plan", "-p", action="store_true", help="互動規劃模式")
    parser.add_argument("--quick", "-q", action="store_true", help="快速模式")
    parser.add_argument("--days", type=int, default=5)
    parser.add_argument("--agents", type=int, default=8)
    
    args = parser.parse_args()
    
    if args.plan or (args.scenario is None and not args.quick):
        # 互動規劃模式（預設）
        await interactive_mode()
    elif args.quick and args.scenario:
        await quick_mode(args.scenario, args.days, args.agents)
    elif args.scenario:
        await quick_mode(args.scenario, args.days, args.agents)
    else:
        print("用法: python main.py [--plan] [場景描述]")
        print("      python main.py --plan          (互動規劃模式)")
        print("      python main.py --quick \"...\"   (快速模式)")


if __name__ == "__main__":
    asyncio.run(main())
