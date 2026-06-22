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
from datetime import datetime, timezone

MONGO_URI = os.environ.get("MONGODB_URI", "")
DB_NAME   = os.environ.get("MONGO_DB_NAME", "sbrp")

# Zona horaria de Madrid
MADRID_TZ = zoneinfo.ZoneInfo("Europe/Madrid")

def get_db():
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    return client[DB_NAME]["sbrp_sessions"]

# ──────────────────────────────────────────────
# LÓGICA DE STATS
# ──────────────────────────────────────────────
def fetch_stats():
    col = get_db()
    # Traemos las últimas 15 sesiones
    sessions = list(col.find().sort("open_start", -1).limit(15))

    if not sessions:
        return {
            "server_status": "closed",
            "last_change_time": None,
            "time_elapsed_seconds": 0,
            "total_sessions": 0,
            "avg_duration": 0,
            "max_duration": 0,
            "total_votes": 0,
            "best_hour": "—",
            "best_day": "—",
            "staff_ranking": [],
            "recent": [],
            "by_weekday": [0]*7,
            "by_hour": [0]*24
        }

    # Estado dinámico y cálculo de tiempos activos
    last_session = sessions[0]
    server_status = "open" if last_session.get("status") == "open" else "closed"
    
    # Calcular cuánto lleva abierto o cuándo se cerró
    time_elapsed_seconds = 0
    last_change_time_str = "—"
    
    if server_status == "open" and last_session.get("open_start"):
        open_start = last_session["open_start"]
        if open_start.tzinfo is None:
            open_start = open_start.replace(tzinfo=timezone.utc)
        now_utc = datetime.now(timezone.utc)
        time_elapsed_seconds = int((now_utc - open_start).total_seconds())
        last_change_time_str = open_start.astimezone(MADRID_TZ).strftime("%H:%M")
    elif server_status == "closed" and last_session.get("close_time"):
        close_time = last_session["close_time"]
        if close_time.tzinfo is None:
            close_time = close_time.replace(tzinfo=timezone.utc)
        last_change_time_str = close_time.astimezone(MADRID_TZ).strftime("%d/%m a las %H:%M")

    # Filtrar cerradas para promedios
    closed_sessions = [s for s in sessions if s.get("status") == "closed"]
    durations = [s["duration_minutes"] for s in closed_sessions if s.get("duration_minutes")]
    avg_dur = round(sum(durations)/len(durations)) if durations else 0
    max_dur = max(durations) if durations else 0
    total_votes = sum((s.get("votes_now", 0) + s.get("votes_later", 0)) for s in sessions)

    # Ranking Staff
    staff_count = {}
    for s in sessions:
        name = s.get("opened_by", "Desconocido")
        staff_count[name] = staff_count.get(name, 0) + 1
    staff_ranking = sorted(staff_count.items(), key=lambda x: x[1], reverse=True)[:5]

    by_weekday = [0]*7
    by_hour = [0]*24
    recent = []

    for s in sessions:
        o_start = s.get("open_start")
        if o_start:
            if o_start.tzinfo is None:
                o_start = o_start.replace(tzinfo=timezone.utc)
            local_time = o_start.astimezone(MADRID_TZ)
            by_weekday[local_time.weekday()] += 1
            by_hour[local_time.hour] += 1

    DAYS_NAMES = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']
    best_hour = f"{by_hour.index(max(by_hour))}:00" if max(by_hour) > 0 else "18:00"
    best_day = DAYS_NAMES[by_weekday.index(max(by_weekday))] if max(by_weekday) > 0 else "Sábado"

    # Procesar historial con horas exactas de Madrid
    for s in reversed(sessions):
        o_start = s.get("open_start")
        c_time = s.get("close_time")
        
        open_exact = "—"
        close_exact = "En vivo"
        
        if o_start:
            if o_start.tzinfo is None:
                o_start = o_start.replace(tzinfo=timezone.utc)
            open_exact = o_start.astimezone(MADRID_TZ).strftime("%H:%M")
            date_str = o_start.astimezone(MADRID_TZ).strftime("%d/%m")
        else:
            date_str = "—"
            
        if c_time and s.get("status") == "closed":
            if c_time.tzinfo is None:
                c_time = c_time.replace(tzinfo=timezone.utc)
            close_exact = c_time.astimezone(MADRID_TZ).strftime("%H:%M")

        recent.append({
            "date": date_str,
            "open_exact": open_exact,
            "close_exact": close_exact,
            "duration": s.get("duration_minutes", 0) if s.get("status") == "closed" else "En vivo",
            "staff": s.get("opened_by", "—"),
            "votes": s.get("votes_now", 0) + s.get("votes_later", 0)
        })

    return {
        "server_status": server_status,
        "last_change_time": last_change_time_str,
        "time_elapsed_seconds": time_elapsed_seconds,
        "total_sessions": len(sessions),
        "avg_duration": avg_dur,
        "max_duration": max_dur,
        "total_votes": total_votes,
        "best_hour": best_hour,
        "best_day": best_day,
        "staff_ranking": [{"name": k, "count": v} for k, v in staff_ranking],
        "recent": recent,
        "by_weekday": by_weekday,
        "by_hour": by_hour
    }

# ──────────────────────────────────────────────
# HTML COMPLETO Y CORREGIDO
# ──────────────────────────────────────────────
HTML = r"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>SBRP · Estado de Aperturas</title>
<link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap" rel="stylesheet"/>
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{
  --bg:#040612;
  --surface-card:#0b0f26;
  --border:rgba(255,255,255,0.06);
  --border-hover:rgba(59,130,246,0.25);
  --blue:#3b82f6;
  --cyan:#22d3ee;
  --green:#10b981;
  --red:#ef4444;
  --text:#f8fafc;
  --muted:#64748b;
  --brand-grad:linear-gradient(135deg, #58a6ff 0%, #22d3ee 100%);
}
body{
  background:var(--bg);color:var(--text);font-family:'Plus Jakarta Sans',sans-serif;
  min-height:100vh;overflow-x:hidden;
  background-image: radial-gradient(at 0% 0%, rgba(59,130,246,0.08) 0px, transparent 50%);
}
.container{max-width:1200px;margin:0 auto;padding:2rem 1.5rem}

/* CABECERA */
.header-panel{
  display:flex;align-items:center;justify-content:space-between;gap:1.5rem;
  background:rgba(11,15,38,0.6);border:1px solid var(--border);
  backdrop-filter:blur(16px);padding:1.5rem 2rem;border-radius:24px;margin-bottom:2rem;
}
@media(max-width:768px){.header-panel{flex-direction:column;text-align:center}}
.brand-wrapper{display:flex;align-items:center;gap:1.2rem}
@media(max-width:768px){.brand-wrapper{flex-direction:column}}
.server-logo{width:64px;height:64px;border-radius:20px;border:2px solid rgba(255,255,255,0.08)}
h1{font-size:1.6rem;font-weight:800;background:var(--brand-grad);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.subtitle{color:var(--muted);font-size:0.85rem;margin-top:0.15rem}

/* LIVE STATUS BAR */
.status-container{display:flex;flex-direction:column;align-items:flex-end;gap:0.3rem}
@media(max-width:768px){.status-container{align-items:center}}
.status-badge{
  display:inline-flex;align-items:center;gap:0.6rem;
  border-radius:999px;padding:0.5rem 1.2rem;font-size:0.85rem;font-weight:700;
}
.status-badge.open-style{background:rgba(16,185,129,0.12);border:1px solid rgba(16,185,129,0.3);color:var(--green)}
.status-badge.closed-style{background:rgba(239,68,68,0.12);border:1px solid rgba(239,68,68,0.3);color:var(--red)}
.badge-dot{width:10px;height:10px;border-radius:50%;animation:pulse 2s infinite}
.open-style .badge-dot{background:var(--green);box-shadow:0 0 8px var(--green)}
.closed-style .badge-dot{background:var(--red);box-shadow:0 0 8px var(--red)}
.status-info-text{font-size:0.75rem;color:var(--muted);font-weight:500}

@keyframes pulse{0%,100%{transform:scale(1);opacity:1}50%{transform:scale(1.2);opacity:0.5}}

/* DASHBOARD GRIDS */
.kpi-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:1.25rem;margin-bottom:2rem}
.main-grid{display:grid;grid-template-columns:1.6fr 1fr;gap:1.25rem;margin-bottom:2rem}
@media(max-width:900px){.main-grid{grid-template-columns:1fr}}

.card{background:var(--surface-card);border:1px solid var(--border);border-radius:20px;padding:1.5rem;transition:all 0.2s ease}
.card:hover{border-color:var(--border-hover)}

.kpi-label{font-size:0.75rem;font-weight:700;text-transform:uppercase;color:var(--muted);margin-bottom:0.4rem}
.kpi-value{font-size:1.9rem;font-weight:800}
.kpi-sub{font-size:0.75rem;color:var(--muted);margin-top:0.4rem}
.section-title{font-size:0.95rem;font-weight:700;margin-bottom:1.25rem;color:var(--text)}

/* GRÁFICO DE LÍNEAS MEJORADO */
.chart-container{position:relative;width:100%;height:160px;margin-top:1rem;display:flex}
.chart-y-axis{display:flex;flex-direction:column;justify-content:space-between;font-size:0.65rem;color:var(--muted);padding-right:8px;font-weight:600;text-align:right;width:35px}
.svg-wrap{flex:1;position:relative;height:100%}
svg.line-chart{width:100%;height:100%;overflow:visible}
.chart-line{fill:none;stroke:url(#line-grad);stroke-width:4;stroke-linecap:round}
.chart-area{fill:url(#area-grad);opacity:0.08}
.chart-dot{fill:var(--bg);stroke:var(--cyan);stroke-width:3;cursor:pointer}
.chart-dot:hover{r:6.5;fill:var(--cyan)}
.chart-xaxis{display:flex;justify-content:space-between;margin-top:0.6rem;margin-left:43px}
.xaxis-lbl{font-size:0.7rem;color:var(--muted);font-weight:700}

/* COMPACT BARS */
.bar-chart-compact{display:flex;gap:6px;height:65px;align-items:flex-end;margin-top:1rem}
.bar-col-c{flex:1;height:100%;display:flex;flex-direction:column;justify-content:flex-end;position:relative}
.bar-c{width:100%;background:rgba(59,130,246,0.12);border-radius:4px;min-height:3px}
.bar-col-c:hover .bar-c{background:var(--cyan);box-shadow:0 0 8px var(--cyan)}
.bar-tooltip{
  position:absolute;bottom:100%;left:50%;transform:translateX(-50%) translateY(-4px);
  background:#151b36;border:1px solid var(--border);padding:0.25rem 0.5rem;border-radius:6px;
  font-size:0.65rem;white-space:nowrap;opacity:0;pointer-events:none;transition:all 0.15s;z-index:10;
}
.bar-col-c:hover .bar-tooltip{opacity:1;transform:translateX(-50%) translateY(0)}

/* RANKING & TABLE */
.staff-list{display:flex;flex-direction:column;gap:0.7rem}
.staff-item{display:flex;align-items:center;justify-content:space-between;background:rgba(255,255,255,0.01);padding:0.75rem 1rem;border-radius:12px;border:1px solid var(--border)}
.staff-name{font-size:0.85rem;font-weight:600}
.staff-count{font-size:0.8rem;font-weight:700;color:var(--cyan);background:rgba(34,211,238,0.08);padding:0.2rem 0.6rem;border-radius:6px}

.table-wrap{overflow-x:auto;margin-top:0.5rem}
table{width:100%;border-collapse:collapse;font-size:0.85rem}
th{color:var(--muted);font-weight:600;padding:0.85rem 1rem;font-size:0.75rem;text-transform:uppercase;text-align:left;border-bottom:1px solid var(--border)}
td{padding:0.9rem 1rem;border-bottom:1px solid rgba(255,255,255,0.02)}
tr:hover td{background:rgba(255,255,255,0.01)}
.date-highlight{color:var(--cyan);font-weight:700}
.time-label{font-size:0.8rem;color:var(--muted);font-weight:500}
.dur-tag{background:rgba(34,211,238,0.08);color:var(--cyan);padding:0.25rem 0.6rem;border-radius:6px;font-weight:600}
.dur-live{background:rgba(16,185,129,0.12);color:var(--green);padding:0.25rem 0.6rem;border-radius:6px;font-weight:700;animation:pulse 2s infinite}

footer{display:flex;justify-content:space-between;align-items:center;margin-top:4rem;padding-top:1.5rem;border-top:1px solid var(--border);color:var(--muted);font-size:0.8rem}
.made-by{font-weight:700;background:var(--brand-grad);-webkit-background-clip:text;-webkit-text-fill-color:transparent}

#loading{display:flex;flex-direction:column;align-items:center;justify-content:center;padding:5rem 0;color:var(--muted)}
.spinner{width:26px;height:26px;border:2px solid var(--border);border-top-color:var(--cyan);border-radius:50%;animation:spin 0.8s linear infinite;margin-bottom:1rem}
@keyframes spin{to{transform:rotate(360deg)}}
</style>
</head>
<body>

<div class="container">
  <div class="header-panel">
    <div class="brand-wrapper">
      <img src="https://images-ext-1.discordapp.net/external/WmcMleh2YLFKbqQvgPKe0sDx-19o0hTHqj1EXB-ZFvI/%3Fsize%3D2048/https/cdn.discordapp.com/icons/907442123123601408/c8e27684c3478cbd4293f36e56a5a49a.png?format=webp&quality=lossless" class="server-logo" alt="Logo"/>
      <div>
        <h1>Spanish Barcelona RP</h1>
        <p class="subtitle">Estadísticas de aperturas diarios con hora de España</p>
      </div>
    </div>
    <div class="status-container">
      <div id="live-status" class="status-badge closed-style"><span class="badge-dot"></span><span id="status-text">Cargando...</span></div>
      <div id="status-info" class="status-info-text">Actualizando tiempos...</div>
    </div>
  </div>

  <div id="loading"><div class="spinner"></div>Consultando base de datos...</div>

  <div id="content" style="display:none">
    <div class="kpi-grid" id="kpis"></div>

    <div class="main-grid">
      <div class="card">
        <p class="section-title">📈 Duración histórica (Minutos que se mantuvo abierto)</p>
        <div class="chart-container">
          <div class="chart-y-axis" id="chart-y-axis"></div>
          <div class="svg-wrap">
            <svg class="line-chart" id="svg-chart" viewBox="0 0 500 130" preserveAspectRatio="none">
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
        </div>
        <div class="chart-xaxis" id="chart-xaxis"></div>
      </div>

      <div class="card">
        <p class="section-title">👑 Administradores con más aperturas</p>
        <div class="staff-list" id="staff-ranking"></div>
      </div>
    </div>

    <div class="main-grid" style="grid-template-columns: 1fr 1fr;">
       <div class="card">
          <p class="section-title">📅 Aperturas totales por día de semana</p>
          <div class="bar-chart-compact" id="weekday-chart"></div>
       </div>
       <div class="card">
          <p class="section-title">🕐 Aperturas totales por hora del día</p>
          <div class="bar-chart-compact" id="hour-chart"></div>
       </div>
    </div>

    <div class="card">
      <p class="section-title">⏱️ Lista ordenada de sesiones recientes</p>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Día</th>
              <th>Hora Apertura</th>
              <th>Hora Cierre</th>
              <th>Encargado</th>
              <th>Tiempo total</th>
              <th>Votos</th>
            </tr>
          </thead>
          <tbody id="recent-table"></tbody>
        </table>
      </div>
    </div>
  </div>

  <footer>
    <span>© 2026 SBRP Panel de Control</span>
    <span>Sello oficial · <span class="made-by">Made by qproz</span></span>
  </footer>
</div>

<script>
const DAYS = ['Lun','Mar','Mié','Jue','Vie','Sáb','Dom'];
let liveSecondsElapsed = 0;
let serverStatusGlobal = "closed";
let initialTimeStr = "";

async function load(){
  try{
    const r = await fetch('/api/stats');
    const d = await r.json();
    render(d);
    document.getElementById('loading').style.display='none';
    document.getElementById('content').style.display='block';
  }catch(e){
    document.getElementById('loading').innerHTML='<p style="color:#ef4444">Error de conexión.</p>';
  }
}

function updateLiveCounter() {
  if (serverStatusGlobal === "open") {
    liveSecondsElapsed++;
    const hrs = Math.floor(liveSecondsElapsed / 3600);
    const mins = Math.floor((liveSecondsElapsed % 3600) / 60);
    document.getElementById('status-info').innerText = `Abrió a las ${initialTimeStr}h (Lleva activo: ${hrs}h y ${mins}m)`;
  }
}

function render(d){
  serverStatusGlobal = d.server_status;
  initialTimeStr = d.last_change_time || "";
  liveSecondsElapsed = d.time_elapsed_seconds || 0;

  // Lógica del Cartel de Estado en Vivo superior
  const statusEl = document.getElementById('live-status');
  const textEl = document.getElementById('status-text');
  const infoEl = document.getElementById('status-info');

  if(d.server_status === "open"){
    statusEl.className = "status-badge open-style";
    textEl.innerText = "Servidor Abierto";
    const hrs = Math.floor(liveSecondsElapsed / 3600);
    const mins = Math.floor((liveSecondsElapsed % 3600) / 60);
    infoEl.innerText = `Abrió a las ${initialTimeStr}h (Lleva activo: ${hrs}h y ${mins}m)`;
  } else {
    statusEl.className = "status-badge closed-style";
    textEl.innerText = "Servidor Cerrado";
    infoEl.innerText = `Último cierre el ${initialTimeStr}h`;
  }

  // Cuadros principales
  const kpis=[
    {label:'Historial Registrado', value:d.total_sessions + ' ses.', sub:'Sesiones procesadas', color:'#3b82f6'},
    {label:'Tiempo Promedio', value:d.avg_duration+' min', sub:'Media abierto', color:#22d3ee'},
    {label:'Hora Más Activa', value:d.best_hour, sub:`Punto fuerte de apertura`, color:'#10b981'},
    {label:'Día Más Activo', value:d.best_day, sub:'Día con mayor frecuencia', color:'#a855f7'}
  ];
  document.getElementById('kpis').innerHTML=kpis.map(k=>`
    <div class="card">
      <p class="kpi-label">${k.label}</p>
      <p class="kpi-value" style="color:${k.color}">${k.value}</p>
      <p class="kpi-sub">${k.sub}</p>
    </div>`).join('');

  // RENDER COMPLETO DEL GRÁFICO DE LÍNEAS CON EJES EXÁCTOS
  if(d.recent && d.recent.length > 0){
    const width = 500; const height = 110; const padding = 15;
    const numericDurations = d.recent.map(s => typeof s.duration === 'number' ? s.duration : 0);
    const maxDur = Math.max(...numericDurations, 60);
    
    // Rellenar eje Y de minutos informativo
    document.getElementById('chart-y-axis').innerHTML = `
      <span>${maxDur}m</span>
      <span>${Math.round(maxDur/2)}m</span>
      <span>0m</span>
    `;

    const points = d.recent.map((s, i) => {
      const x = padding + (i * (width - padding * 2) / (d.recent.length - 1));
      const val = typeof s.duration === 'number' ? s.duration : 0;
      const y = height - padding - (val * (height - padding * 2) / maxDur);
      return {x, y, ...s};
    });

    const linePath = points.map((p, i) => `${i===0?'M':'L'} ${p.x} ${p.y}`).join(' ');
    const areaPath = `${linePath} L ${points[points.length-1].x} ${height-padding} L ${points[0].x} ${height-padding} Z`;
    
    document.querySelector('.chart-line').setAttribute('d', linePath);
    document.querySelector('.chart-area').setAttribute('d', areaPath);

    document.getElementById('chart-dots').innerHTML = points.map(p => `
      <circle class="chart-dot" cx="${p.x}" cy="${p.y}" r="4.5">
        <title>Día ${p.date} - Duración: ${p.duration} min</title>
      </circle>
    `).join('');

    document.getElementById('chart-xaxis').innerHTML = d.recent.map(s => `
      <span class="xaxis-lbl">${s.date}</span>
    `).join('');
  }

  // Lista de Staff
  document.getElementById('staff-ranking').innerHTML = d.staff_ranking.length
    ? d.staff_ranking.map((s,i)=>`
      <div class="staff-item">
        <span class="staff-name">${i+1}. 👤 <b>${s.name}</b></span>
        <span class="staff-count">${s.count} aperturas</span>
      </div>`).join('')
    : '<p style="color:var(--muted)">Sin datos</p>';

  // Días Spark
  const maxW = Math.max(...d.by_weekday, 1);
  document.getElementById('weekday-chart').innerHTML = d.by_weekday.map((v,i)=>`
    <div class="bar-col-c">
      <div class="bar-tooltip">${DAYS[i]}: ${v} veces</div>
      <div class="bar-c" style="height:${Math.round(v/maxW*100)}%"></div>
    </div>`).join('');

  // Horas Spark
  const maxH = Math.max(...d.by_hour, 1);
  document.getElementById('hour-chart').innerHTML = d.by_hour.map((v,i)=>`
    <div class="bar-col-c">
      <div class="bar-tooltip">${i}:00h : ${v} veces</div>
      <div class="bar-c" style="height:${Math.round(v/maxH*100)}%; background:rgba(168,85,247,0.15)"></div>
    </div>`).join('');

  // Tabla con Horas exactas
  const tableData = [...d.recent].reverse();
  document.getElementById('recent-table').innerHTML = tableData.length
    ? tableData.map(s=>`
      <tr>
        <td><span class="date-highlight">${s.date}</span></td>
        <td><span class="time-label">⏰ ${s.open_exact}h</span></td>
        <td><span class="time-label">${s.close_exact === "En vivo" ? '🟢 En línea' : '🚪 ' + s.close_exact + 'h'}</span></td>
        <td><b>${s.staff}</b></td>
        <td><span class="${typeof s.duration === 'number' ? 'dur-tag' : 'dur-live'}">${typeof s.duration === 'number' ? s.duration + ' min' : 'Abierto ⚡'}</span></td>
        <td style="font-weight:700;color:#f43f5e">${s.votes} votos</td>
      </tr>`).join('')
    : '<tr><td colspan="6" style="text-align:center;color:var(--muted)">Ningún registro activo</td></tr>';
}

load();
setInterval(load, 45000);        // Actualiza datos de la DB cada 45 segundos
setInterval(updateLiveCounter, 1000); // Suma un segundo al reloj local en vivo cada segundo
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
                self.send_header("Cache-Control", "s-maxage=20")
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
