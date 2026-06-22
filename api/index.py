"""
api/index.py  ─  Vercel Serverless Function
Sirve la web de stats Y los datos JSON desde MongoDB.
"""
from http.server import BaseHTTPRequestHandler
import json
import os
from urllib.parse import urlparse, parse_qs
from pymongo import MongoClient
from datetime import datetime, timezone
import re

MONGO_URI = os.environ.get("MONGODB_URI", "")
DB_NAME   = os.environ.get("MONGO_DB_NAME", "sbrp")

def get_db():
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    return client[DB_NAME]["sbrp_sessions"]

# ──────────────────────────────────────────────
# LÓGICA DE STATS
# ──────────────────────────────────────────────
def fetch_stats():
    col = get_db()
    sessions = list(col.find({"status": "closed"}).sort("close_time", -1).limit(200))

    if not sessions:
        return {
            "total_sessions": 0,
            "avg_duration": 0,
            "max_duration": 0,
            "max_duration_date": None,
            "total_votes": 0,
            "earliest_open": None,
            "latest_open": None,
            "staff_ranking": [],
            "recent": [],
            "by_weekday": [0]*7,
            "by_hour": [0]*24
        }

    durations  = [s["duration_minutes"] for s in sessions if s.get("duration_minutes")]
    avg_dur    = round(sum(durations)/len(durations)) if durations else 0
    max_dur    = max(durations) if durations else 0
    max_sess   = next((s for s in sessions if s.get("duration_minutes") == max_dur), None)
    total_votes = sum((s.get("votes_now",0)+s.get("votes_later",0)) for s in sessions)

    # Ranking de staff
    staff_count = {}
    for s in sessions:
        name = s.get("opened_by", "Desconocido")
        staff_count[name] = staff_count.get(name, 0) + 1
    staff_ranking = sorted(staff_count.items(), key=lambda x: x[1], reverse=True)[:10]

    # Hora más temprana / más tardía de apertura (hora UTC)
    open_hours = [s["open_start"].hour for s in sessions if s.get("open_start")]
    earliest   = min(open_hours) if open_hours else None
    latest_h   = max(open_hours) if open_hours else None

    # Por día de semana (0=lunes)
    by_weekday = [0]*7
    for s in sessions:
        if s.get("open_start"):
            by_weekday[s["open_start"].weekday()] += 1

    # Por hora del día
    by_hour = [0]*24
    for s in sessions:
        if s.get("open_start"):
            by_hour[s["open_start"].hour] += 1

    # Sesiones recientes
    recent = []
    for s in sessions[:8]:
        recent.append({
            "date":     s.get("open_start").strftime("%d/%m/%Y") if s.get("open_start") else "—",
            "duration": s.get("duration_minutes"),
            "staff":    s.get("opened_by", "—"),
            "votes":    s.get("votes_now",0)+s.get("votes_later",0)
        })

    return {
        "total_sessions": len(sessions),
        "avg_duration":   avg_dur,
        "max_duration":   max_dur,
        "max_duration_date": max_sess["open_start"].strftime("%d/%m/%Y") if max_sess and max_sess.get("open_start") else None,
        "total_votes":    total_votes,
        "earliest_open":  earliest,
        "latest_open":    latest_h,
        "staff_ranking":  [{"name": k, "count": v} for k,v in staff_ranking],
        "recent":         recent,
        "by_weekday":     by_weekday,
        "by_hour":        by_hour
    }

# ──────────────────────────────────────────────
# HTML
# ──────────────────────────────────────────────
HTML = r"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>SBRP · Panel de Aperturas</title>
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@300;400;500;600;700&family=Inter:wght@400;500&display=swap" rel="stylesheet"/>
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{
  --bg:#07080F;
  --surface:#0D0F1A;
  --surface2:#12152A;
  --border:#1C2040;
  --blue:#3B82F6;
  --cyan:#06B6D4;
  --green:#10B981;
  --red:#EF4444;
  --text:#E2E8F0;
  --muted:#64748B;
  --accent-glow:rgba(59,130,246,.18);
}
html{scroll-behavior:smooth}
body{background:var(--bg);color:var(--text);font-family:'Inter',sans-serif;min-height:100vh;overflow-x:hidden}

/* GRAIN overlay */
body::before{
  content:'';position:fixed;inset:0;pointer-events:none;z-index:0;
  background-image:url("data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)' opacity='0.04'/%3E%3C/svg%3E");
  opacity:.4
}

/* HERO */
.hero{
  position:relative;padding:4rem 2rem 3rem;text-align:center;
  background:radial-gradient(ellipse 80% 50% at 50% -10%,rgba(59,130,246,.15),transparent);
  border-bottom:1px solid var(--border)
}
.badge{
  display:inline-flex;align-items:center;gap:.4rem;
  background:rgba(59,130,246,.12);border:1px solid rgba(59,130,246,.3);
  border-radius:999px;padding:.25rem .9rem;font-size:.72rem;
  font-family:'Space Grotesk',sans-serif;letter-spacing:.08em;text-transform:uppercase;
  color:var(--blue);margin-bottom:1.2rem
}
.badge-dot{width:6px;height:6px;border-radius:50%;background:var(--cyan);animation:pulse 2s infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.3}}
h1{font-family:'Space Grotesk',sans-serif;font-size:clamp(2rem,5vw,3.5rem);font-weight:700;
   background:linear-gradient(135deg,#fff 0%,var(--cyan) 100%);
   -webkit-background-clip:text;-webkit-text-fill-color:transparent;line-height:1.1}
.hero-sub{color:var(--muted);margin-top:.75rem;font-size:.95rem}

/* GRID */
.container{max-width:1200px;margin:0 auto;padding:2rem 1.5rem}
.kpi-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:1rem;margin-bottom:2rem}
.main-grid{display:grid;grid-template-columns:1fr 1fr;gap:1rem}
@media(max-width:700px){.main-grid{grid-template-columns:1fr}}

/* CARDS */
.card{
  background:var(--surface);border:1px solid var(--border);border-radius:16px;
  padding:1.5rem;position:relative;overflow:hidden;transition:border-color .2s
}
.card:hover{border-color:rgba(59,130,246,.4)}
.card::after{
  content:'';position:absolute;top:0;left:0;right:0;height:1px;
  background:linear-gradient(90deg,transparent,rgba(59,130,246,.4),transparent)
}

/* KPI */
.kpi-label{font-size:.72rem;text-transform:uppercase;letter-spacing:.1em;color:var(--muted);font-family:'Space Grotesk',sans-serif;margin-bottom:.5rem}
.kpi-value{font-family:'Space Grotesk',sans-serif;font-size:2.4rem;font-weight:700;line-height:1}
.kpi-sub{font-size:.75rem;color:var(--muted);margin-top:.35rem}
.kpi-icon{position:absolute;top:1.2rem;right:1.2rem;font-size:1.4rem;opacity:.35}

/* SECTION TITLE */
.section-title{
  font-family:'Space Grotesk',sans-serif;font-size:.8rem;
  text-transform:uppercase;letter-spacing:.12em;color:var(--muted);
  margin-bottom:1rem;display:flex;align-items:center;gap:.5rem
}
.section-title::after{content:'';flex:1;height:1px;background:var(--border)}

/* STAFF RANKING */
.staff-row{
  display:flex;align-items:center;gap:.75rem;padding:.6rem 0;
  border-bottom:1px solid var(--border)
}
.staff-row:last-child{border-bottom:none}
.rank{
  font-family:'Space Grotesk',sans-serif;font-weight:700;font-size:.75rem;
  color:var(--muted);width:1.5rem;text-align:center
}
.rank-1{color:#FFD700}.rank-2{color:#C0C0C0}.rank-3{color:#CD7F32}
.staff-name{flex:1;font-size:.9rem;font-weight:500}
.staff-bar-wrap{width:80px;background:var(--surface2);border-radius:4px;height:6px;overflow:hidden}
.staff-bar{height:100%;border-radius:4px;background:linear-gradient(90deg,var(--blue),var(--cyan));transition:width 1s ease}
.staff-count{font-family:'Space Grotesk',sans-serif;font-size:.8rem;color:var(--blue);font-weight:600;min-width:2rem;text-align:right}

/* BAR CHART */
.bar-chart{display:flex;align-items:flex-end;gap:3px;height:90px;padding-top:.5rem}
.bar-col{flex:1;display:flex;flex-direction:column;align-items:center;gap:4px}
.bar{
  width:100%;border-radius:3px 3px 0 0;
  background:linear-gradient(180deg,var(--cyan),var(--blue));
  min-height:2px;transition:height 1s ease;position:relative
}
.bar:hover .bar-tooltip{opacity:1;transform:translateY(-4px)}
.bar-tooltip{
  position:absolute;bottom:calc(100% + 4px);left:50%;transform:translateX(-50%);
  background:var(--surface2);border:1px solid var(--border);
  border-radius:6px;padding:.2rem .5rem;font-size:.65rem;
  white-space:nowrap;opacity:0;transition:all .15s;pointer-events:none;
  font-family:'Space Grotesk',sans-serif;color:var(--text)
}
.bar-label{font-size:.55rem;color:var(--muted);font-family:'Space Grotesk',sans-serif}

/* RECENT TABLE */
.table-wrap{overflow-x:auto}
table{width:100%;border-collapse:collapse;font-size:.83rem}
th{
  font-family:'Space Grotesk',sans-serif;font-size:.68rem;text-transform:uppercase;
  letter-spacing:.08em;color:var(--muted);padding:.6rem .75rem;
  border-bottom:1px solid var(--border);text-align:left
}
td{padding:.65rem .75rem;border-bottom:1px solid rgba(28,32,64,.6);vertical-align:middle}
tr:last-child td{border-bottom:none}
tr:hover td{background:rgba(59,130,246,.04)}
.dur-badge{
  display:inline-flex;align-items:center;gap:.3rem;
  background:rgba(16,185,129,.1);border:1px solid rgba(16,185,129,.25);
  border-radius:999px;padding:.15rem .55rem;font-size:.75rem;
  color:var(--green);font-family:'Space Grotesk',sans-serif;font-weight:600
}
.vote-num{color:var(--cyan);font-weight:600;font-family:'Space Grotesk',sans-serif}

/* SKELETON */
.skeleton{
  background:linear-gradient(90deg,var(--surface) 25%,var(--surface2) 50%,var(--surface) 75%);
  background-size:200% 100%;animation:shimmer 1.4s infinite;
  border-radius:6px
}
@keyframes shimmer{0%{background-position:200% 0}100%{background-position:-200% 0}}

/* FOOTER */
footer{text-align:center;padding:2rem;color:var(--muted);font-size:.75rem;border-top:1px solid var(--border)}
.live-dot{display:inline-block;width:6px;height:6px;border-radius:50%;background:var(--green);margin-right:.4rem;animation:pulse 2s infinite}

/* LOADING STATE */
#loading{display:flex;flex-direction:column;align-items:center;justify-content:center;padding:4rem;gap:1rem;color:var(--muted)}
.spinner{width:32px;height:32px;border:2px solid var(--border);border-top-color:var(--blue);border-radius:50%;animation:spin .7s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}
</style>
</head>
<body>

<div class="hero">
  <div class="badge"><span class="badge-dot"></span>Spanish Barcelona RP</div>
  <h1>Panel de Aperturas</h1>
  <p class="hero-sub">Estadísticas en tiempo real de las sesiones del servidor</p>
</div>

<div class="container">
  <div id="loading"><div class="spinner"></div><span>Cargando datos...</span></div>
  <div id="content" style="display:none">
    <!-- KPIs -->
    <div class="kpi-grid" id="kpis"></div>
    <!-- Main grid -->
    <div class="main-grid">
      <div class="card">
        <p class="section-title">🏆 Ranking de Staff</p>
        <div id="staff-ranking"></div>
      </div>
      <div class="card">
        <p class="section-title">📅 Aperturas por día de semana</p>
        <div class="bar-chart" id="weekday-chart"></div>
        <div class="bar-chart" style="height:auto;margin-top:.25rem" id="weekday-labels"></div>
      </div>
      <div class="card" style="grid-column:1/-1">
        <p class="section-title">🕐 Aperturas por hora del día (UTC)</p>
        <div class="bar-chart" id="hour-chart" style="height:80px"></div>
      </div>
    </div>

    <!-- Recent sessions -->
    <div class="card" style="margin-top:1rem">
      <p class="section-title">⏱️ Sesiones recientes</p>
      <div class="table-wrap">
        <table>
          <thead><tr><th>Fecha</th><th>Staff</th><th>Duración</th><th>Votos</th></tr></thead>
          <tbody id="recent-table"></tbody>
        </table>
      </div>
    </div>
  </div>
</div>

<footer><span class="live-dot"></span>Actualizado cada 60 segundos · SBRP Stats Panel</footer>

<script>
const DAYS = ['Lun','Mar','Mié','Jue','Vie','Sáb','Dom'];

async function load(){
  try{
    const r = await fetch('/api/stats');
    const d = await r.json();
    render(d);
    document.getElementById('loading').style.display='none';
    document.getElementById('content').style.display='block';
  }catch(e){
    document.getElementById('loading').innerHTML='<p style="color:#EF4444">Error cargando datos. Revisa la conexión a MongoDB.</p>';
  }
}

function render(d){
  // KPIs
  const kpis=[
    {label:'Sesiones totales',value:d.total_sessions,sub:'históricas registradas',icon:'📋',color:'var(--blue)'},
    {label:'Duración media',value:d.avg_duration+'m',sub:'por sesión',icon:'⏱️',color:'var(--cyan)'},
    {label:'Sesión más larga',value:d.max_duration+'m',sub:d.max_duration_date||'',icon:'🏅',color:'var(--green)'},
    {label:'Votos totales',value:d.total_votes,sub:'de jugadores',icon:'🗳️',color:'var(--blue)'},
    {label:'Apertura más temprana',value:d.earliest_open!=null?(d.earliest_open+'h UTC'):'—',sub:'hora UTC',icon:'🌅',color:'var(--cyan)'},
    {label:'Apertura más tardía',value:d.latest_open!=null?(d.latest_open+'h UTC'):'—',sub:'hora UTC',icon:'🌙',color:'var(--muted)'},
  ];
  document.getElementById('kpis').innerHTML=kpis.map(k=>`
    <div class="card">
      <p class="kpi-label">${k.label}</p>
      <p class="kpi-value" style="color:${k.color}">${k.value}</p>
      <p class="kpi-sub">${k.sub}</p>
      <span class="kpi-icon">${k.icon}</span>
    </div>`).join('');

  // Staff ranking
  const maxCount = d.staff_ranking[0]?.count||1;
  document.getElementById('staff-ranking').innerHTML=d.staff_ranking.length
    ? d.staff_ranking.map((s,i)=>`
      <div class="staff-row">
        <span class="rank rank-${i+1}">${i===0?'👑':i+1}</span>
        <span class="staff-name">${s.name}</span>
        <div class="staff-bar-wrap"><div class="staff-bar" style="width:${Math.round(s.count/maxCount*100)}%"></div></div>
        <span class="staff-count">${s.count}</span>
      </div>`).join('')
    : '<p style="color:var(--muted);font-size:.85rem">Sin datos aún</p>';

  // Weekday chart
  const maxW=Math.max(...d.by_weekday,1);
  document.getElementById('weekday-chart').innerHTML=d.by_weekday.map((v,i)=>`
    <div class="bar-col">
      <div class="bar" style="height:${Math.round(v/maxW*80)}px">
        <div class="bar-tooltip">${v} sesiones</div>
      </div>
    </div>`).join('');
  document.getElementById('weekday-labels').innerHTML=DAYS.map(l=>`
    <div class="bar-col"><span class="bar-label">${l}</span></div>`).join('');

  // Hour chart
  const maxH=Math.max(...d.by_hour,1);
  document.getElementById('hour-chart').innerHTML=d.by_hour.map((v,i)=>`
    <div class="bar-col">
      <div class="bar" style="height:${Math.round(v/maxH*70)}px;background:linear-gradient(180deg,var(--blue),rgba(59,130,246,.3))">
        <div class="bar-tooltip">${i}h UTC — ${v}</div>
      </div>
    </div>`).join('');

  // Recent table
  document.getElementById('recent-table').innerHTML=d.recent.length
    ? d.recent.map(s=>`
      <tr>
        <td>${s.date}</td>
        <td>${s.staff}</td>
        <td><span class="dur-badge">⏱ ${s.duration!=null?s.duration+'m':'—'}</span></td>
        <td><span class="vote-num">${s.votes}</span></td>
      </tr>`).join('')
    : '<tr><td colspan="4" style="color:var(--muted);text-align:center;padding:2rem">Sin sesiones registradas todavía</td></tr>';
}

load();
setInterval(load,60000);
</script>
</body>
</html>"""

# ──────────────────────────────────────────────
# HANDLER VERCEL
# ──────────────────────────────────────────────
class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/stats":
            try:
                data = fetch_stats()
                body = json.dumps(data, default=str).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Cache-Control", "s-maxage=30")
                self.end_headers()
                self.wfile.write(body)
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type","application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error":str(e)}).encode())
        else:
            body = HTML.encode()
            self.send_response(200)
            self.send_header("Content-Type","text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(body)

    def log_message(self, *args):
        pass
