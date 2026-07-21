"""一次執行模擬並輸出 HTML 報告，直接可用 Chrome 打開"""
import asyncio, sys, json, os
from datetime import datetime

if sys.platform == "win32":
    try: sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except: pass

from ssp_night_vibes_sim import build_ssp_night_vibes_config
from engine import create_deepseek_llm, run_simulation
from memory_manager import create_memory_manager
from tools import create_default_tool_registry

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-HK">
<head><meta charset="UTF-8"><title>{title}</title>
<style>
body{{font-family:'Segoe UI',Arial,sans-serif;max-width:900px;margin:0 auto;padding:20px;background:#1a1a2e;color:#e0e0e0}}
h1{{color:#e94560;border-bottom:2px solid #e94560;padding-bottom:10px}}
h2{{color:#0f3460;background:#e94560;padding:8px 15px;border-radius:5px;display:inline-block;margin-top:30px}}
.metrics{{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:15px;margin:20px 0}}
.card{{background:#16213e;border-radius:8px;padding:15px;border-left:4px solid #e94560}}
.card .name{{font-size:0.9em;color:#aaa}}
.card .value{{font-size:1.6em;font-weight:bold;margin:5px 0}}
.card .delta{{font-size:0.85em}}
.delta-up{{color:#4ecca3}}.delta-down{{color:#e94560}}
.agents{{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:10px}}
.agent{{background:#16213e;border-radius:6px;padding:10px;font-size:0.9em}}
.agent strong{{color:#e94560}}
table{{width:100%;border-collapse:collapse;margin:10px 0}}
th,td{{padding:8px 12px;text-align:left;border-bottom:1px solid #333}}
th{{background:#0f3460;color:#e94560}}
tr:hover{{background:#1a1a3e}}
.obs{{background:#16213e;border-radius:8px;padding:15px;margin:10px 0;border-left:4px solid #4ecca3}}
.obs h4{{color:#4ecca3;margin-top:0}}
.footer{{text-align:center;color:#666;margin-top:40px;font-size:0.8em}}
</style></head>
<body>
<h1>{title}</h1>
<p>{description}</p>
<p>模擬日期: {start_date} → Day {max_days} | 智能體: {agent_count} 人 | 執行時間: {elapsed_sec:.0f} 秒 | 成本: ~HK${cost:.2f}</p>

<h2>智能體名冊</h2>
<div class="agents">{agent_cards}</div>

<h2>環境指標 (Day 1 → Day {max_days})</h2>
<div class="metrics">{metric_cards}</div>

<h2>執行摘要</h2>
<div class="obs">{executive_summary}</div>

<h2>模擬觀察</h2>
<div class="obs">{observations}</div>

<div class="footer">深水埗日夜都繽紛 — 社會動態模擬系統 | 數據來源: 2024-2026研究文件 [A]-[F] | 生成時間: {gen_time}</div>
</body></html>"""

async def main():
    config = build_ssp_night_vibes_config()
    config.init_metrics()
    
    llm = create_deepseek_llm(temperature=0.7)
    tool_registry = create_default_tool_registry()
    memory_manager = create_memory_manager(persist_dir="./chroma_data")
    memory_manager.init_simulation(config.simulation_id)
    
    print("Running simulation (12 agents × 14 days)...")
    start = datetime.now()
    result = await run_simulation(config, llm, tool_registry, memory_manager)
    elapsed = (datetime.now() - start).total_seconds()
    
    # Build HTML
    env = config.initial_environment
    agent_cards = "".join(
        f'<div class="agent"><strong>{a.name}</strong><br>{a.role}<br>'
        f'<span style="color:#888;font-size:0.8em">{a.core_motivation[:60]}...</span></div>'
        for a in config.agents
    )
    
    # Metric cards with deltas if available
    metric_cards = ""
    for mid in config.active_metrics:
        if mid not in env.metric_definitions: continue
        from models import Metric
        m = Metric(**env.metric_definitions[mid])
        start_val = env.metrics.get(mid, m.baseline)
        end_val = start_val
        if result.all_day_logs:
            last_log = result.all_day_logs[-1]
            end_val = last_log.environment_after.metrics.get(mid, start_val)
        delta = end_val - start_val
        css = "delta-up" if (delta > 0 and m.higher_is_better) or (delta < 0 and not m.higher_is_better) else "delta-down"
        metric_cards += (
            f'<div class="card"><div class="name">{m.name} ({m.unit})</div>'
            f'<div class="value">{end_val:.1f}</div>'
            f'<div class="delta {css}">Day 1: {start_val:.1f} → Day {config.max_days}: {end_val:.1f} ({"+" if delta>=0 else ""}{delta:.1f})</div>'
            f'<div style="font-size:0.75em;color:#888;margin-top:5px">{m.data_source}</div></div>'
        )
    
    # Parse summary into parts
    summary = result.executive_summary
    # Extract sections
    exec_part = summary
    obs_part = ""
    if "## 模擬觀察" in summary:
        parts = summary.split("## 模擬觀察")
        exec_part = parts[0].strip()
        obs_part = ("## 模擬觀察" + parts[1]).strip() if len(parts) > 1 else ""
    elif "### 3." in summary:
        parts = summary.split("### 3.")
        exec_part = parts[0].strip()
        obs_part = ("### 3." + "### 3.".join(parts[1:])).strip()
    
    # Format for HTML
    exec_html = exec_part.replace("\n\n", "</p><p>").replace("\n", "<br>").replace("### ", "<h4>").replace("## ", "<h3>").replace("**", "<b>").replace("**", "</b>")
    obs_html = obs_part.replace("\n\n", "</p><p>").replace("\n", "<br>")
    
    html = HTML_TEMPLATE.format(
        title=config.title, description=config.description,
        start_date=config.start_date, max_days=config.max_days,
        agent_count=len(config.agents), elapsed_sec=elapsed, cost=0.55,
        agent_cards=agent_cards, metric_cards=metric_cards,
        executive_summary=exec_html, observations=obs_html,
        gen_time=datetime.now().strftime("%Y-%m-%d %H:%M"),
    )
    
    out_path = "ssp_night_vibes_report.html"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    
    print(f"\nReport saved: {out_path}")
    print(f"Open in Chrome: {os.path.abspath(out_path)}")

if __name__ == "__main__":
    asyncio.run(main())
