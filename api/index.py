"""
api/index.py  ─  Vercel Serverless Function
Sirve la web de stats Y los datos JSON desde MongoDB.
"""
from http.server import BaseHTTPRequestHandler
import json
import os
from urllib.parse import urlparse
from pymongo import MongoClient
import zoneinfo
from datetime import datetime

MONGO_URI = os.environ.get("MONGODB_URI", "")
DB_NAME   = os.environ.get("MONGO_DB_NAME", "sbrp")

# Configuración de zona horaria de Madrid
MADRID_TZ = zoneinfo.ZoneInfo("Europe/Madrid")

def get_db():
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    return client[DB_NAME]["sbrp_sessions"]

# ──────────────────────────────────────────────
# LÓGICA DE STATS (ZONA HORARIA MADRID)
# ──────────────────────────────────────────────
def fetch_stats():
    col = get_db()
    # Traemos las últimas 15 sesiones para el gráfico de líneas y tabla
    sessions = list(col.find({"status": "closed"}).sort("close_time", -1).limit(15))

    if not sessions:
        return {
            "total_sessions": 0,
            "avg_duration": 0,
            "max_duration": 0,
            "max_duration_date": None,
            "total_votes": 0,
            "staff_ranking": [],
            "recent": [],
            "by_weekday": [0]*7,
            "by_hour": [0]*24
        }

    durations = [s["duration_minutes"] for s in sessions if s.get("duration_minutes")]
    avg_dur = round(sum(durations)/len(durations)) if durations else 0
    max_dur = max(durations) if durations else 0
    max_sess = next((s for s in sessions if s.get("duration_minutes") == max_dur), None)
    total_votes = sum((s.get("votes_now", 0) + s.get("votes_later", 0)) for s in sessions)

    # Ranking de staff
    staff_count = {}
    for s in sessions:
        name = s.get("opened_by", "Desconocido")
        staff_count[name] = staff_count.get(name, 0) + 1
    staff_ranking = sorted(staff_count.items(), key=lambda x: x[1], reverse=True)[:5]

    # Distribución por día de la semana y hora en Madrid
    by_weekday = [0]*7
    by_hour = [0]*24
    recent = []

    for s in sessions:
        open_start = s.get("open_start")
        if open_start:
            # Convertir la fecha UTC nativa de Mongo a la de Madrid
            if open_start.tzinfo is None:
                open_start = open_start.replace(tzinfo=zoneinfo.ZoneInfo("UTC"))
            local_time = open_start.astimezone(MADRID_TZ)
            
            by_weekday[local_time.weekday()] += 1
            by_hour[local_time.hour] += 1

    # Formatear las sesiones recientes (invertidas para que el gráfico de líneas vaya de pasado a presente)
    for s in reversed(sessions):
        open_start = s.get("open_start")
        date_str = "—"
        if open_start:
            if open_start.tzinfo is None:
                open_start = open_start.replace(tzinfo=zoneinfo.ZoneInfo("UTC"))
            date_str = open_start.astimezone(MADRID_TZ).strftime("%d/%m")

        recent.append({
            "date": date_str,
            "duration": s.get("duration_minutes", 0),
            "staff": s.get("opened_by", "—"),
            "votes": s.get("votes_now", 0) + s.get("votes_later", 0)
        })

    # Fecha de la sesión más larga a Zona Madrid
    max_date_str = None
    if max_sess and max_sess.get("open_start"):
        m_start = max_sess["open_start"]
        if m_start.tzinfo is None:
            m_start = m_start.replace(tzinfo=zoneinfo.ZoneInfo("UTC"))
        max_date_str = m_start.astimezone(MADRID_TZ).strftime("%d/%m/%Y")

    return {
        "total_sessions": len(sessions),
        "avg_duration": avg_dur,
        "max_duration": max_dur,
        "max_duration_date": max_date_str,
        "total_votes": total_votes,
        "staff_ranking": [{"name": k, "count": v} for k, v in staff_ranking],
        "recent": recent, # Va de más antigua a más reciente para el gráfico
        "by_weekday": by_weekday,
        "by_hour": by_hour
    }

# ──────────────────────────────────────────────
# HTML INTERFAZ PREMIUM
# ──────────────────────────────────────────────
HTML = r"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>SBRP · Panel de Control</title>
<link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap" rel="stylesheet"/>
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{
  --bg:#03040B;
  --surface:rgba(13,16,34,0.6);
  --surface-card:#0d1124;
  --border:rgba(255,255,255,0.06);
  --border-hover:rgba(59,130,246,0.3);
  --blue:#3b82f6;
  --cyan:#22d3ee;
  --green:#10b981;
  --text:#f8fafc;
  --muted:#94a3b8;
  --brand-grad:linear-gradient(135deg, #58a6ff 0%, #22d3ee 100%);
}
body{
  background:var(--bg);color:var(--text);font-family:'Plus Jakarta Sans',sans-serif;
  min-height:100vh;overflow-x:hidden;
  background-image: 
    radial-gradient(at 0% 0%, rgba(59,130,246,0.12) 0px, transparent 50%),
    radial-gradient(at 100% 100%, rgba(34,211,238,0.08) 0px, transparent 50%);
}

/* CONTAINER */
.container{max-width:1200px;margin:0 auto;padding:2rem 1.5rem}

/* NAVBAR / HERO */
.header-panel{
  display:flex;align-items:center;justify-content:between;gap:1.5rem;
  background:rgba(13,16,34,0.4);border:1px solid var(--border);
  backdrop-filter:blur(16px);padding:1.5rem 2rem;border-radius:24px;margin-bottom:2.5rem;
}
.brand-wrapper{display:flex;align-items:center;gap:1.2rem}
.server-logo{width:64px;height:64px;border-radius:20px;border:2px solid rgba(223, 233, 255, 0.15);box-shadow:0 8px 24px rgba(0,0,0,0.4)}
h1{font-size:1.75rem;font-weight:800;letter-spacing:-0.02em;background:var(--brand-grad);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.subtitle{color:var(--muted);font-size:0.85rem;margin-top:0.15rem}

.badge{
  margin-left:auto;display:inline-flex;align-items:center;gap:0.5rem;
  background:rgba(16,185,129,0.1);border:1px solid rgba(16,185,129,0.2);
  border-radius:999px;padding:0.4rem 1rem;font-size:0.75rem;font-weight:600;color:var(--green);
}
.badge-dot{width:8px;height:8px;border-radius:50%;background:var(--green);animation:pulse 2s infinite}
@keyframes pulse{0%,100%{transform:scale(1);opacity:1}50%{transform:scale(1.2);opacity:0.4}}

/* GRID */
.kpi-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:1.25rem;margin-bottom:2rem}
.main-grid{display:grid;grid-template-columns:1.4fr 1fr;gap:1.25rem;margin-bottom:2rem}
@media(max-width:900px){.main-grid{grid-template-columns:1fr}}

/* CARDS */
.card{
  background:var(--surface-card);border:1px solid var(--border);border-radius:20px;
  padding:1.5rem;position:relative;transition:all 0.25s cubic-bezier(0.4, 0, 0.2, 1);
}
.card:hover{border-color:var(--border-hover);transform:translateY(-2px);box-shadow:0 12px 30px rgba(3,4,11,0.6)}

/* KPI TEXTS */
.kpi-label{font-size:0.75rem;font-weight:600;text-transform:uppercase;letter-spacing:0.05em;color:var(--muted);margin-bottom:0.5rem}
.kpi-value{font-size:2.2rem;font-weight:800;line-height:1;letter-spacing:-0.03em}
.kpi-sub{font-size:0.75rem;color:var(--muted);margin-top:0.5rem;display:flex;align-items:center;gap:0.25rem}

.section-title{font-size:0.95rem;font-weight:700;margin-bottom:1.25rem;color:var(--text);display:flex;align-items:center;gap:0.5rem}

/* LINE CHART SVG */
.chart-container{position:relative;width:100%;height:180px;margin-top:1rem}
svg.line-chart{width:100%;height:100%;overflow:visible}
.chart-line{fill:none;stroke:url(#line-grad);stroke-width:4;stroke-linecap:round;stroke-linejoin:round;animation:draw 1.5s ease forward}
.chart-area{fill:url(#area-grad);opacity:0.15}
.chart-dot{fill:var(--bg);stroke:var(--cyan);stroke-width:3;cursor:pointer;transition:all 0.2s}
.chart-dot:hover{r:7;fill:var(--cyan)}
.chart-xaxis{display:flex;justify-content:space-between;margin-top:0.5rem;padding:0 10px}
.xaxis-lbl{font-size:0.7rem;color:var(--muted);font-weight:600}

/* HOURLY & WEEKDAY COMPACT BARS */
.bar-chart-compact{display:flex;gap:4px;height:60px;align-items:flex-end;margin-top:1rem}
.bar-col-c{flex:1;height:100%;display:flex;flex-direction:column;justify-content:flex-end;position:relative}
.bar-c{width:100%;background:rgba(59,130,246,0.15);border-radius:4px;min-height:4px;transition:all 0.3s}
.bar-col-c:hover .bar-c{background:var(--cyan);box-shadow:0 0 10px var(--cyan)}
.bar-tooltip{
  position:absolute;bottom:100%;left:50%;transform:translateX(-50%) translateY(-4px);
  background:#1e293b;border:1px solid var(--border);padding:0.25rem 0.5rem;border-radius:6px;
  font-size:0.65rem;white-space:nowrap;opacity:0;pointer-events:none;transition:all 0.15s;z-index:10;
}
.bar-col-c:hover .bar-tooltip{opacity:1;transform:translateX(-50%) translateY(0)}

/* RANKING STAFF */
.staff-list{display:flex;flex-direction:column;gap:0.75rem}
.staff-item{display:flex;align-items:center;gap:1rem;background:rgba(255,255,255,0.02);padding:0.75rem 1rem;border-radius:12px;border:1px solid var(--border)}
.staff-rank{font-weight:800;font-size:0.85rem;width:24px;height:24px;display:flex;align-items:center;justify-content:center;border-radius:6px;background:rgba(255,255,255,0.05)}
.rank-1{background:rgba(234,179,8,0.15);color:#eab308}
.staff-info{flex:1}
.staff-name{font-size:0.85rem;font-weight:600}
.staff-count{font-size:0.8rem;font-weight:700;color:var(--cyan)}

/* TABLE */
.table-wrap{overflow-x:auto;margin-top:0.5rem}
table{width:100%;border-collapse:collapse;font-size:0.85rem;text-align:left}
th{color:var(--muted);font-weight:600;padding:1rem;font-size:0.75rem;text-transform:uppercase;letter-spacing:0.05em;border-bottom:1px solid var(--border)}
td{padding:1rem;border-bottom:1px solid rgba(255,255,255,0.02)}
tr:hover td{background:rgba(255,255,255,0.01)}
.dur-tag{background:rgba(34,211,238,0.1);color:var(--cyan);padding:0.25rem 0.6rem;border-radius:6px;font-weight:600;font-size:0.8rem}

/* FOOTER */
footer{display:flex;justify-content:between;align-items:center;margin-top:4rem;padding-top:1.5rem;border-top:1px solid var(--border);color:var(--muted);font-size:0.8rem}
.made-by{font-weight:700;background:var(--brand-grad);-webkit-background-clip:text;-webkit-text-fill-color:transparent}

#loading{display:flex;flex-direction:column;align-items:center;justify-content:center;padding:5rem 0;color:var(--muted);font-size:0.9rem}
.spinner{width:28px;height:28px;border:2px solid var(--border);border-top-color:var(--cyan);border-radius:50%;animation:spin 0.8s linear infinite;margin-bottom:1rem}
@keyframes spin{to{transform:rotate(360deg)}}
</style>
</head>
<body>

<div class="container">
  <div class="header-panel">
    <div class="brand-wrapper">
      <img src="https://images-ext-1.discordapp.net/external/WmcMleh2YLFKbqQvgPKe0sDx-19o0hTHqj1EXB-ZFvI/%3Fsize%3D2048/https/cdn.discordapp.com/icons/907442123123601408/c8e27684c3478cbd4293f36e56a5a49a.png?format=webp&quality=lossless" class="server-logo" alt="SBRP Logo"/>
      <div>
        <h1>Spanish Barcelona RP</h1>
        <p class="subtitle">Métricas y Rendimiento del Servidor · Hora de Madrid</p>
      </div>
    </div>
    <div class="badge"><span class="badge-dot"></span>Sincronizado</div>
  </div>

  <div id="loading"><div class="spinner"></div>Cargando base de datos...</div>

  <div id="content" style="display:none">
    <div class="kpi-grid" id="kpis"></div>

    <div class="main-grid">
      <div class="card">
        <p class="section-title">📈 Tendencia de Aperturas (Duración por día)</p>
        <div class="chart-container">
          <svg class="line-chart" id="svg-chart" viewBox="0 0 500 150" preserveAspectRatio="none">
            <defs>
              <linearGradient id="line-grad" x1="0" y1="0" x2="1" y2="0">
                <stop offset="0%" stop-color="#3b82f6"/>
                <stop offset="100%" stop-color="#22d3ee"/>
              </linearGradient>
              <linearGradient id="area-grad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stop-color="#22d3ee" stop-opacity="1"/>
                <stop offset="100%" stop-color="#22d3ee" stop-opacity="0"/>
              </linearGradient>
            </defs>
            <path class="chart-area" d=""/>
            <path class="chart-line" d=""/>
            <g id="chart-dots"></g>
          </svg>
        </div>
        <div class="chart-xaxis" id="chart-xaxis"></div>
      </div>

      <div class="card">
        <p class="section-title">👑 Eficiencia de Staff</p>
        <div class="staff-list" id="staff-ranking"></div>
      </div>
    </div>

    <div class="main-grid" style="grid-template-columns: 1fr 1fr;">
       <div class="card">
          <p class="section-title">📅 Sesiones por Día de Semana</p>
          <div class="bar-chart-compact" id="weekday-chart"></div>
       </div>
       <div class="card">
          <p class="section-title">🕐 Distribución Horaria de Aperturas</p>
          <div class="bar-chart-compact" id="hour-chart"></div>
       </div>
    </div>

    <div class="card">
      <p class="section-title">⏱️ Historial Reciente de Sesiones</p>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Día/Mes</th>
              <th>Encargado Staff</th>
              <th>Duración</th>
              <th>Votos Recibidos</th>
            </tr>
          </thead>
          <tbody id="recent-table"></tbody>
        </table>
      </div>
    </div>
  </div>

  <footer>
    <span>© 2026 SBRP Analytics Panel</span>
    <span>Desarrollado con ❤️ · <span class="made-by">Made by qproz</span></span>
  </footer>
</div>

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
    document.getElementById('loading').innerHTML='<p style="color:#ef4444">Error al conectar con MongoDB. Verifica las credenciales.</p>';
  }
}

function render(d){
  // KPIs Útiles Limpios
  const kpis=[
    {label:'Sesiones Analizadas', value:d.total_sessions, sub:'Historial evaluado', color:'#3b82f6'},
    {label:'Promedio Abierto', value:d.avg_duration+' min', sub:'Media por día', color:'#22d3ee'},
    {label:'Récord Abierto', value:d.max_duration+' min', sub:d.max_duration_date||'—', color:'#10b981'},
    {label:'Votos Acumulados', value:d.total_votes, sub:'Apoyo total de la comunidad', color:'#a855f7'}
  ];
  document.getElementById('kpis').innerHTML=kpis.map(k=>`
    <div class="card">
      <p class="kpi-label">${k.label}</p>
      <p class="kpi-value" style="color:${k.color}">${k.value}</p>
      <p class="kpi-sub">${k.sub}</p>
    </div>`).join('');

  // RENDER GRAFICO DE LINEAS (SVG AUTOMÁTICO)
  if(d.recent && d.recent.length > 0){
    const width = 500; const height = 130;
    const padding = 20;
    const maxDur = Math.max(...d.recent.map(s=>s.duration), 60);
    
    // Generar Puntos Coordenadas
    const points = d.recent.map((s, i) => {
      const x = padding + (i * (width - padding * 2) / (d.recent.length - 1));
      const y = height - padding - (s.duration * (height - padding * 2) / maxDur);
      return {x, y, ...s};
    });

    // Dibujar Línea y Área
    const linePath = points.map((p, i) => `${i===0?'M':'L'} ${p.x} ${p.y}`).join(' ');
    const areaPath = `${linePath} L ${points[points.length-1].x} ${height-padding} L ${points[0].x} ${height-padding} Z`;
    
    document.querySelector('.chart-line').setAttribute('d', linePath);
    document.querySelector('.chart-area').setAttribute('d', areaPath);

    // Añadir Círculos de interacción
    document.getElementById('chart-dots').innerHTML = points.map(p => `
      <circle class="chart-dot" cx="${p.x}" cy="${p.y}" r="5">
        <title>${p.date}: ${p.duration} min abierto</title>
      </circle>
    `).join('');

    // Eje X Leyendas
    document.getElementById('chart-xaxis').innerHTML = d.recent.map(s => `
      <span class="xaxis-lbl">${s.date}</span>
    `).join('');
  }

  // Staff Ranking
  document.getElementById('staff-ranking').innerHTML = d.staff_ranking.length
    ? d.staff_ranking.map((s,i)=>`
      <div class="staff-item">
        <div class="staff-rank ${i===0?'rank-1':''}">${i+1}</div>
        <div class="staff-info">
          <p class="staff-name">${s.name}</p>
        </div>
        <span class="staff-count">${s.count} aperturas</span>
      </div>`).join('')
    : '<p style="color:var(--muted)">Sin datos</p>';

  // Weekday Spark Bars
  const maxW = Math.max(...d.by_weekday, 1);
  document.getElementById('weekday-chart').innerHTML = d.by_weekday.map((v,i)=>`
    <div class="bar-col-c">
      <div class="bar-tooltip">${DAYS[i]}: ${v} veces</div>
      <div class="bar-c" style="height:${Math.round(v/maxW*100)}%"></div>
    </div>`).join('');

  // Hours Spark Bars
  const maxH = Math.max(...d.by_hour, 1);
  document.getElementById('hour-chart').innerHTML = d.by_hour.map((v,i)=>`
    <div class="bar-col-c">
      <div class="bar-tooltip">${i}:00h : ${v} ses.</div>
      <div class="bar-c" style="height:${Math.round(v/maxH*100)}%; background:rgba(168,85,247,0.2)"></div>
    </div>`).join('');

  // Recent Table (Invertido para mostrar las últimas reales arriba)
  const tableData = [...d.recent].reverse();
  document.getElementById('recent-table').innerHTML = tableData.length
    ? tableData.map(s=>`
      <tr>
        <td>font color="var(--cyan)"<b>${s.date}</b></font></td>
        <td><b>${s.staff}</b></td>
        <td><span class="dur-tag">${s.duration} min</span></td>
        <td style="font-weight:700;color:#f43f5e">${s.votes} votos</td>
      </tr>`).join('')
    : '<tr><td colspan="4" style="text-align:center;color:var(--muted)">Sin datos disponibles</td></tr>';
}

load();
setInterval(load, 60000);
</script>
</body>
</html>"""

# ──────────────────────────────────────────────
# HANDLER VERCEL HTTP
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
