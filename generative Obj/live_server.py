"""
============================================================
  18區日夜都繽紛 — 即時推送伺服器 + 儀表板
  使用 WebSocket 即時推送每區每日模擬結果到瀏覽器
============================================================
啟動: python live_server.py
打開: http://localhost:8765
"""

import asyncio, json, sys, os, threading, time
from datetime import datetime
from pathlib import Path

if sys.platform == "win32":
    try: sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except: pass

import websockets
from http.server import HTTPServer, SimpleHTTPRequestHandler

# 加入專案路徑
sys.path.insert(0, str(Path(__file__).parent))

from district_sim import DISTRICTS, build_district_config
from engine import create_deepseek_llm, run_simulation
from memory_manager import create_memory_manager
from tools import create_default_tool_registry

# 全局狀態
connected_clients = set()
simulation_progress = {"current": "", "done": [], "total": 18, "metrics": {}}

HTML = """<!DOCTYPE html>
<html lang="zh-HK">
<head><meta charset="UTF-8"><title>18區日夜都繽紛 — 即時監控</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Microsoft YaHei','PingFang HK','Noto Sans TC','Segoe UI',sans-serif;background:#0a0a1a;color:#e0e0e0;padding:20px}
h1{color:#e94560;text-align:center;margin-bottom:5px}
.subtitle{text-align:center;color:#888;margin-bottom:20px;font-size:0.9em}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:8px}
.card{background:#1a1a3e;border-radius:6px;padding:10px;text-align:center;transition:all .3s}
.card.active{background:#0f3460;box-shadow:0 0 10px #e94560}
.card.done{background:#0d3320;opacity:.8}
.card .name{font-size:.85em;font-weight:bold;color:#e94560}
.card .metrics{font-size:.7em;color:#aaa;margin-top:3px}
.card .status{font-size:.65em;margin-top:3px}
#progress{width:100%;height:4px;background:#333;border-radius:2px;margin:15px 0}
#bar{height:100%;background:linear-gradient(90deg,#e94560,#4ecca3);border-radius:2px;width:0%;transition:width .5s}
#log{background:#111;border-radius:6px;padding:10px;max-height:200px;overflow-y:auto;font-size:.75em;font-family:monospace;margin-top:10px}
#log .item{border-bottom:1px solid #222;padding:3px 0}
.v{color:#4ecca3}.w{color:#e94560}.i{color:#888}
</style></head>
<body>
<h1>18區日夜都繽紛 — 即時監控</h1>
<p class="subtitle" id="status">連接中...</p>
<div id="progress"><div id="bar"></div></div>
<div class="grid" id="grid"></div>
<div id="log"></div>
<script>
const ws = new WebSocket(`ws://${location.host}/ws`);
const grid = document.getElementById('grid');
const log = document.getElementById('log');
const bar = document.getElementById('bar');
const status = document.getElementById('status');
let districts = {};

ws.onopen = () => { status.innerHTML = '<span class="v">已連接</span> 等待模擬開始...'; };
ws.onmessage = (e) => {
    const d = JSON.parse(e.data);
    if (d.type === 'init') {
        d.districts.forEach(name => {
            districts[name] = {name, status:'pending', metrics:{}};
        });
        render();
    }
    if (d.type === 'start') {
        districts[d.district].status = 'active';
        logMsg(`<span class="v">▶</span> ${d.district} 開始`);
        render();
    }
    if (d.type === 'day') {
        districts[d.district].status = 'active';
        districts[d.district].metrics = d.metrics;
        districts[d.district].day = d.day;
        logMsg(`${d.district} Day ${d.day}: 噪音${(d.metrics.noise_db||0).toFixed(0)}dB 投訴${(d.metrics.complaint_count||0).toFixed(0)}件`);
        render();
    }
    if (d.type === 'done') {
        districts[d.district].status = 'done';
        districts[d.district].metrics = d.metrics;
        bar.style.width = (d.done / d.total * 100) + '%';
        status.innerHTML = `完成: ${d.done}/${d.total} 區`;
        logMsg(`<span class="v">✅</span> ${d.district} 完成`);
        render();
    }
};
function logMsg(msg) {
    log.innerHTML += `<div class="item">${msg}</div>`;
    log.scrollTop = log.scrollHeight;
}
function render() {
    let html = '';
    for (const [name, d] of Object.entries(districts)) {
        const cls = d.status === 'active' ? 'active' : (d.status === 'done' ? 'done' : '');
        const m = d.metrics;
        let metricStr = '';
        if (d.day) metricStr += `D${d.day} `;
        if (m.noise_db) metricStr += `<span class="${m.noise_db>75?'w':'v'}">${m.noise_db.toFixed(0)}dB</span> `;
        if (m.complaint_count) metricStr += `${m.complaint_count.toFixed(0)}件 `;
        if (m.vendor_daily_revenue) metricStr += `$${m.vendor_daily_revenue.toFixed(0)} `;
        html += `<div class="card ${cls}"><div class="name">${name}</div><div class="metrics">${metricStr||'等待中'}</div><div class="status">${d.status==='active'?'⏳模擬中':(d.status==='done'?'✅完成':'⏸')}</div></div>`;
    }
    grid.innerHTML = html;
}
</script>
</body></html>"""

class Handler(SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/':
            self.send_response(200); self.send_header('Content-Type','text/html; charset=utf-8')
            self.end_headers(); self.wfile.write(HTML.encode())
        else:
            super().do_GET()

async def broadcast(msg):
    if connected_clients:
        payload = json.dumps(msg, ensure_ascii=False)
        await asyncio.gather(*[c.send(payload) for c in connected_clients], return_exceptions=True)

async def ws_handler(websocket):
    connected_clients.add(websocket)
    try:
        await websocket.send(json.dumps({"type":"init","districts":list(DISTRICTS.keys())}, ensure_ascii=False))
        await websocket.wait_closed()
    finally:
        connected_clients.discard(websocket)

async def run_simulation_with_push(days=5, agents=6):
    districts = list(DISTRICTS.keys())
    await broadcast({"type":"init","districts":districts})
    
    llm = create_deepseek_llm(temperature=0.7)
    tool_registry = create_default_tool_registry()
    memory_manager = create_memory_manager()
    
    results = {}
    for i, dist_name in enumerate(districts):
        await broadcast({"type":"start","district":dist_name,"done":i,"total":18})
        
        config = build_district_config(dist_name, days, agents)
        config.init_metrics()
        memory_manager.init_simulation(config.simulation_id)
        
        # 執行模擬（但需要攔截每日結果來推送）
        # run_simulation 是封裝好的，我們直接用它的結果再推送摘要
        result = await run_simulation(config, llm, tool_registry, memory_manager)
        
        # 推送最終指標
        last_log = result.all_day_logs[-1] if result.all_day_logs else None
        if last_log:
            metrics = last_log.environment_after.metrics
            await broadcast({"type":"day","district":dist_name,"day":days,"metrics":metrics})
        
        results[dist_name] = {
            "metrics": last_log.environment_after.metrics if last_log else {},
            "summary": result.executive_summary[:200]
        }
        
        await broadcast({"type":"done","district":dist_name,"done":i+1,"total":18,
                         "metrics": last_log.environment_after.metrics if last_log else {}})
    
    # 儲存結果
    out = {"simulated_at": datetime.now().isoformat(), "results": results}
    path = f"18districts_live_{datetime.now().strftime('%Y%m%d_%H%M')}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    
    await broadcast({"type":"all_done","path":path})
    return results

async def main():
    # 啟動 HTTP server
    httpd = HTTPServer(('0.0.0.0', 8765), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    
    print(f"""
╔══════════════════════════════════════════════╗
║  18區日夜都繽紛 — 即時監控伺服器            ║
║  打開瀏覽器: http://localhost:8765          ║
║  按 Ctrl+C 停止                              ║
╚══════════════════════════════════════════════╝
""")
    
    # 啟動 WebSocket
    async with websockets.serve(ws_handler, "0.0.0.0", 8766):
        print("[WS] WebSocket ready on port 8766")
        print("[SIM] 開始 18 區模擬...")
        await run_simulation_with_push(days=5, agents=6)

if __name__ == "__main__":
    asyncio.run(main())
