"""從 18 區 JSON 生成 HTML 比較報告 (簡潔版 + 文字圖表)"""
import json, os, sys
from datetime import datetime

if sys.platform == "win32":
    try: sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except: pass

files = sorted([f for f in os.listdir(".") if f.startswith("18districts_results_") and f.endswith(".json")])
if not files: print("No results found"); sys.exit(1)

with open(files[-1], "r", encoding="utf-8") as f:
    data = json.load(f)

results = data["results"]
dist_names = sorted(results.keys())

def rank(k, reverse=False):
    sd = sorted(dist_names, key=lambda d: results[d].get("metrics",{}).get(k,0), reverse=reverse)
    return {d:i+1 for i,d in enumerate(sd)}

noise_rank = rank("noise_db", True)
crowd_rank = rank("crowd_density", True)
rev_rank = rank("vendor_daily_revenue", True)
comp_rank = rank("complaint_count", True)
sat_rank = rank("resident_satisfaction", True)
tour_rank = rank("tourist_count", True)

FEAT = {
    "中西區":"金融核心+半山蘇豪","灣仔":"商業+利東街海濱","東區":"住宅+太古城夜飛龍","南區":"香港仔+淺水灣",
    "油尖旺":"廟街女人街核心","深水埗":"基層社區+電腦商場","九龍城":"啟德+九龍城寨","黃大仙":"公屋+黃大仙祠",
    "觀塘":"人口最多+海濱市集","葵青":"貨櫃碼頭+青衣","荃灣":"新界西商業中心","屯門":"衛星城市+夜屯園",
    "元朗":"大馬路+YOHO","北區":"邊境+跨境消費","大埔":"大埔墟+林村河","沙田":"第二大區+城門河",
    "西貢":"將軍澳+海鮮街","離島":"大嶼山+長洲南丫島"
}

def badge(r, v, u=""):
    if r==1: return f'🥇{v:.0f}{u}'
    if r==2: return f'🥈{v:.0f}{u}'
    if r==3: return f'🥉{v:.0f}{u}'
    return f'{v:.0f}{u}'

def color(val, hi, low, flip=False):
    if flip: val = -val
    if val > hi: return "#e94560"
    if val > low: return "#ffd700"
    return "#4ecca3"

def bar(val, mx, w=10, ch="█"):
    n = max(0, int(val/mx*w))
    return ch*n + "░"*(w-n)

# Build rows
rows = ""
noise_vals, rev_vals, comp_vals, sat_vals, crowd_vals, tour_vals = [],[],[],[],[],[]
for d in dist_names:
    r = results.get(d,{})
    m = r.get("metrics",{})
    nv = m.get("noise_db",0); noise_vals.append(nv)
    rv = m.get("vendor_daily_revenue",0); rev_vals.append(rv)
    cv = m.get("complaint_count",0); comp_vals.append(cv)
    sv = m.get("resident_satisfaction",0); sat_vals.append(sv)
    cd = m.get("crowd_density",0); crowd_vals.append(cd)
    tv = m.get("tourist_count",0); tour_vals.append(tv)
    
    rows += f"""<tr>
      <td><b>{d}</b><br><small>{FEAT.get(d,'')}</small></td>
      <td style="color:{color(nv,80,70,True)}">{badge(noise_rank[d],nv,'dB')}</td>
      <td>{badge(crowd_rank[d],cd,'/m²')}</td>
      <td style="color:{color(rv,3000,2000)}">{badge(rev_rank[d],rv,'')}</td>
      <td style="color:{color(cv,15,10,True)}">{badge(comp_rank[d],cv,'')}</td>
      <td style="color:{color(sv,75,65)}">{badge(sat_rank[d],sv,'%')}</td>
      <td>{badge(tour_rank[d],tv,'')}</td>
    </tr>"""

# Build text scatter chart
mx_noise = max(noise_vals) or 1
mx_rev = max(rev_vals) or 1
mx_comp = max(comp_vals) or 1
mx_sat = max(sat_vals) or 1

scatter_rows = ""
for i, d in enumerate(dist_names):
    nb = bar(noise_vals[i], mx_noise, 12, "▇")
    rb = bar(rev_vals[i], mx_rev, 12, "▇")
    cb = bar(comp_vals[i], mx_comp, 12, "▇")
    scatter_rows += f'<tr><td style="font-size:0.8em">{d}</td><td style="font-family:monospace;color:#e94560">{nb}</td><td style="font-family:monospace;color:#4ecca3">{rb}</td><td style="font-family:monospace;color:#ffd700">{cb}</td></tr>'

# Find extreme districts
hottest = max(dist_names, key=lambda d: results[d]["metrics"].get("noise_db",0))
richest = max(dist_names, key=lambda d: results[d]["metrics"].get("vendor_daily_revenue",0))
angriest = max(dist_names, key=lambda d: results[d]["metrics"].get("complaint_count",0))
happiest = max(dist_names, key=lambda d: results[d]["metrics"].get("resident_satisfaction",0))
densest = max(dist_names, key=lambda d: results[d]["metrics"].get("crowd_density",0))
tourist_heavy = max(dist_names, key=lambda d: results[d]["metrics"].get("tourist_count",0))

html = f"""<!DOCTYPE html><html lang="zh-HK">
<head><meta charset="UTF-8"><title>18區日夜都繽紛 — 全港模擬報告</title>
<style>
body{{font-family:'Segoe UI',Arial,sans-serif;max-width:1200px;margin:0 auto;padding:20px;background:#1a1a2e;color:#e0e0e0}}
h1{{color:#e94560;border-bottom:2px solid #e94560;padding-bottom:10px}}
h2{{color:#0f3460;background:#e94560;padding:8px 15px;border-radius:5px;display:inline-block;margin-top:30px}}
h3{{color:#ffd700;margin-top:25px}}
table{{width:100%;border-collapse:collapse;margin:15px 0;font-size:0.9em}}
th{{background:#0f3460;color:#e94560;padding:10px 8px;text-align:center;position:sticky;top:0}}
td{{padding:8px;text-align:center;border-bottom:1px solid #333}}
tr:hover{{background:#1a1a3e}}
.card{{background:#16213e;border-radius:8px;padding:15px;margin:10px 0;border-left:4px solid #e94560}}
.card.green{{border-left-color:#4ecca3}}
.card.yellow{{border-left-color:#ffd700}}
.footer{{text-align:center;color:#666;margin-top:40px;font-size:0.8em}}
.chart{{font-family:'Courier New',monospace;font-size:0.9em}}
</style></head>
<body>
<h1>18區日夜都繽紛 — 全港社會動態模擬報告</h1>
<p>模擬日期: 2026-03-08→03-12 (5天) | 每區6智能體 | 共108智能體 | 數據來源: 2021人口普查 + 2024-2026政策研究</p>

<h2>📊 18區指標對比 (Day 5 終局)</h2>
<p style="color:#888">🥇🥈🥉 = 排名前三 | <span style="color:#e94560">紅色</span>=需注意 | <span style="color:#4ecca3">綠色</span>=良好</p>
<table><thead><tr>
  <th>區域</th><th>噪音(dB)</th><th>人群(/m²)</th><th>小販收入(HKD)</th><th>投訴(件/天)</th><th>滿意度(%)</th><th>遊客(/晚)</th>
</tr></thead><tbody>{rows}</tbody></table>

<h2>📈 文字圖表 (18區並排對比)</h2>
<p style="color:#888">每條 bar 的長度代表該區在該指標上的相對值</p>
<table><thead><tr><th>區域</th><th style="color:#e94560">噪音 ▇</th><th style="color:#4ecca3">收入 ▇</th><th style="color:#ffd700">投訴 ▇</th></tr></thead>
<tbody>{scatter_rows}</tbody></table>

<h2>🔍 極端區域發現</h2>
<div class="card"><b>🔴 最嘈:</b> {hottest} — {results[hottest]['metrics']['noise_db']:.0f}dB<br><small>{FEAT.get(hottest,'')}</small></div>
<div class="card green"><b>🟢 最賺:</b> {richest} — HK${results[richest]['metrics']['vendor_daily_revenue']:.0f}/天</div>
<div class="card yellow"><b>🟡 最多投訴:</b> {angriest} — {results[angriest]['metrics']['complaint_count']:.0f}件/天</div>
<div class="card green"><b>🟢 最滿意:</b> {happiest} — {results[happiest]['metrics']['resident_satisfaction']:.0f}%</div>
<div class="card"><b>🔴 最擠:</b> {densest} — {results[densest]['metrics']['crowd_density']:.1f}人/m²</div>
<div class="card yellow"><b>🟡 最多遊客:</b> {tourist_heavy} — {results[tourist_heavy]['metrics']['tourist_count']:.0f}人/晚</div>

<h2>💡 政策啟示</h2>
<div class="card">1. <b>高密度+低收入區域</b>（深水埗、觀塘）活動需配套隔音設施和清潔預算</div>
<div class="card green">2. <b>旅遊主導區域</b>（離島、北區）需控制遊客量上限，避免過度旅遊</div>
<div class="card yellow">3. <b>高端消費區域</b>（中西區、灣仔）可著重品質而非數量</div>
<div class="card">4. <b>新界西區域</b>（屯門、元朗）需注意跨境消費對本地小販的排擠效應</div>

<div class="footer">
動態多智能體元沙盤推演系統 (Meta-Simulation Platform) | 2021人口普查+2024-2026政策研究 | 生成: {datetime.now().strftime("%Y-%m-%d %H:%M")}
</div>
</body></html>"""

path = f"18districts_report_{datetime.now().strftime('%Y%m%d_%H%M')}.html"
with open(path, "w", encoding="utf-8") as f:
    f.write(html)
print(f"Report: {path}")
