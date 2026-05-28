from datetime import datetime
from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
import json
import os
import secrets
import sqlite3
import time
import psutil
import pynvml

app = FastAPI()
security = HTTPBasic()
pynvml.nvmlInit()

# ===== SET PASSWORD KAT SINI =====
USERS = {
    "admin": "admin123",
    "client": "tukar_password_client",
}
# =================================

_last_net = {"t": time.time(), "sent": 0, "recv": 0}
_last_log_ts = 0.0
DB_PATH = os.path.join(os.path.dirname(__file__), "monitor_history.db")
LOG_INTERVAL_SECONDS = 10


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS metrics (
            ts INTEGER PRIMARY KEY,
            status TEXT NOT NULL,
            cpu REAL NOT NULL,
            ram_pct REAL NOT NULL,
            disk_pct REAL NOT NULL,
            net_up REAL NOT NULL,
            net_down REAL NOT NULL,
            gpu_util_max REAL NOT NULL,
            gpu_vram_max REAL NOT NULL,
            gpu_json TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_metrics_ts ON metrics(ts)")
    conn.commit()
    conn.close()


def parse_dt_input(dt_raw: str) -> int:
    try:
        dt = datetime.fromisoformat(dt_raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid datetime format") from exc
    return int(dt.timestamp())


def save_history(sample: dict, now_ts: float):
    global _last_log_ts
    if now_ts - _last_log_ts < LOG_INTERVAL_SECONDS:
        return

    gpu_util_max = max((g["util"] for g in sample["gpus"]), default=0.0)
    gpu_vram_max = max((g["vram_pct"] for g in sample["gpus"]), default=0.0)
    ts = int(now_ts)
    row = (
        ts,
        sample["status"],
        sample["cpu"],
        sample["ram_pct"],
        sample["disk_pct"],
        sample["net_up"],
        sample["net_down"],
        gpu_util_max,
        gpu_vram_max,
        json.dumps(sample["gpus"]),
    )
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        INSERT OR REPLACE INTO metrics
        (ts, status, cpu, ram_pct, disk_pct, net_up, net_down, gpu_util_max, gpu_vram_max, gpu_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        row,
    )
    conn.commit()
    conn.close()
    _last_log_ts = now_ts


init_db()

def check_auth(creds: HTTPBasicCredentials = Depends(security)):
    pw = USERS.get(creds.username)
    if not pw or not secrets.compare_digest(creds.password, pw):
        raise HTTPException(status_code=401, detail="Unauthorized",
                            headers={"WWW-Authenticate": "Basic"})
    return creds.username

def collect_stats():
    global _last_net
    cpu_overall = psutil.cpu_percent(interval=0.3)
    cpu_cores = psutil.cpu_percent(interval=0, percpu=True)
    freq = psutil.cpu_freq()
    load = psutil.getloadavg()
    ram = psutil.virtual_memory()
    swap = psutil.swap_memory()
    disk = psutil.disk_usage('/')

    net = psutil.net_io_counters()
    now = time.time()
    dt = max(now - _last_net["t"], 0.001)
    up = (net.bytes_sent - _last_net["sent"]) / dt / 1024**2
    down = (net.bytes_recv - _last_net["recv"]) / dt / 1024**2
    _last_net = {"t": now, "sent": net.bytes_sent, "recv": net.bytes_recv}

    gpus = []
    for i in range(pynvml.nvmlDeviceGetCount()):
        h = pynvml.nvmlDeviceGetHandleByIndex(i)
        name = pynvml.nvmlDeviceGetName(h)
        u = pynvml.nvmlDeviceGetUtilizationRates(h)
        m = pynvml.nvmlDeviceGetMemoryInfo(h)
        t = pynvml.nvmlDeviceGetTemperature(h, pynvml.NVML_TEMPERATURE_GPU)
        def safe(fn, d=0):
            try: return fn()
            except Exception: return d
        pwr = round(safe(lambda: pynvml.nvmlDeviceGetPowerUsage(h)) / 1000)
        pwr_cap = round(safe(lambda: pynvml.nvmlDeviceGetEnforcedPowerLimit(h)) / 1000)
        clk = safe(lambda: pynvml.nvmlDeviceGetClockInfo(h, pynvml.NVML_CLOCK_GRAPHICS))
        mclk = safe(lambda: pynvml.nvmlDeviceGetClockInfo(h, pynvml.NVML_CLOCK_MEM))
        fan = safe(lambda: pynvml.nvmlDeviceGetFanSpeed(h))
        gpus.append({
            "name": name if isinstance(name, str) else name.decode(),
            "util": u.gpu, "mem_util": u.memory,
            "vram_used": round(m.used / 1024**3, 2),
            "vram_total": round(m.total / 1024**3, 2),
            "vram_pct": round(m.used / m.total * 100, 1),
            "temp": t, "power": pwr, "power_cap": pwr_cap,
            "clock": clk, "mem_clock": mclk, "fan": fan,
        })

    st = "OK"
    if cpu_overall > 90 or ram.percent > 90 or any(g["vram_pct"] > 90 for g in gpus):
        st = "Overloaded"
    elif cpu_overall > 60 or ram.percent > 75 or any(g["util"] > 70 for g in gpus):
        st = "Busy"

    return {
        "status": st,
        "cpu": cpu_overall,
        "cpu_cores": [round(c, 1) for c in cpu_cores],
        "cpu_freq": round(freq.current) if freq else 0,
        "cpu_freq_max": round(freq.max) if freq else 0,
        "load": [round(x, 2) for x in load],
        "ram_used": round(ram.used / 1024**3, 2),
        "ram_total": round(ram.total / 1024**3, 2),
        "ram_pct": ram.percent,
        "ram_cached": round(ram.cached / 1024**3, 2),
        "ram_avail": round(ram.available / 1024**3, 2),
        "swap_used": round(swap.used / 1024**3, 2),
        "swap_total": round(swap.total / 1024**3, 2),
        "swap_pct": swap.percent,
        "disk_used": round(disk.used / 1024**3, 1),
        "disk_total": round(disk.total / 1024**3, 1),
        "disk_pct": disk.percent,
        "net_up": round(up, 2), "net_down": round(down, 2),
        "gpus": gpus,
    }


@app.get("/api/stats")
def get_stats(user: str = Depends(check_auth)):
    sample = collect_stats()
    save_history(sample, time.time())
    return sample


@app.get("/api/history")
def get_history(
    from_dt: str = Query(..., alias="from"),
    to_dt: str = Query(..., alias="to"),
    limit: int = Query(500, ge=1, le=5000),
    user: str = Depends(check_auth),
):
    from_ts = parse_dt_input(from_dt)
    to_ts = parse_dt_input(to_dt)
    if to_ts <= from_ts:
        raise HTTPException(status_code=400, detail="'to' must be greater than 'from'")

    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        """
        SELECT ts, status, cpu, ram_pct, disk_pct, net_up, net_down, gpu_util_max, gpu_vram_max
        FROM metrics
        WHERE ts BETWEEN ? AND ?
        ORDER BY ts DESC
        LIMIT ?
        """,
        (from_ts, to_ts, limit),
    ).fetchall()
    conn.close()

    data = [
        {
            "ts": r[0],
            "status": r[1],
            "cpu": round(r[2], 1),
            "ram_pct": round(r[3], 1),
            "disk_pct": round(r[4], 1),
            "net_up": round(r[5], 2),
            "net_down": round(r[6], 2),
            "gpu_util_max": round(r[7], 1),
            "gpu_vram_max": round(r[8], 1),
        }
        for r in rows
    ]
    return {"count": len(data), "items": data}

@app.get("/", response_class=HTMLResponse)
def page(user: str = Depends(check_auth)):
    return HTML

HTML = r"""
<!DOCTYPE html>
<html>
<head>
<title>server.monitor</title>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600;700&display=swap" rel="stylesheet">
<style>
  *{box-sizing:border-box;margin:0;padding:0}
  :root{
    --bg:#0c0e14;--panel:#11141d;--panel2:#161a26;--border:#222838;
    --txt:#c7d0e0;--dim:#5a6378;--green:#3ddc84;--yellow:#f5c451;--red:#ff5c6c;
    --blue:#4d9fff;--purple:#b073ff;--cyan:#3de0e0;
  }
  body{font-family:'JetBrains Mono',monospace;background:var(--bg);color:var(--txt);
    padding:1rem;max-width:1200px;margin:auto;font-size:13px;line-height:1.4}
  .head{display:flex;justify-content:space-between;align-items:center;
    border:1px solid var(--border);border-radius:6px 6px 0 0;padding:.6rem 1rem;background:var(--panel)}
  .head .title{font-weight:700;font-size:1rem;letter-spacing:.5px}
  .head .title span{color:var(--green)}
  .head .badge{font-size:.75rem;padding:.25rem .7rem;border-radius:4px;font-weight:600}
  .b-ok{background:rgba(61,220,132,.12);color:var(--green);border:1px solid rgba(61,220,132,.3)}
  .b-busy{background:rgba(245,196,81,.12);color:var(--yellow);border:1px solid rgba(245,196,81,.3)}
  .b-over{background:rgba(255,92,108,.12);color:var(--red);border:1px solid rgba(255,92,108,.3)}
  .tabs{display:flex;background:var(--panel);border-left:1px solid var(--border);
    border-right:1px solid var(--border)}
  .tab{flex:1;padding:.6rem;text-align:center;cursor:pointer;color:var(--dim);
    font-weight:600;font-size:.8rem;letter-spacing:1px;border-bottom:2px solid transparent;
    transition:.2s;text-transform:uppercase;user-select:none}
  .tab:hover{color:var(--txt);background:var(--panel2)}
  .tab.active{color:var(--green);border-bottom-color:var(--green);background:var(--panel2)}
  .tab .mini{display:block;font-size:.9rem;color:var(--txt);margin-top:.15rem}
  .body{border:1px solid var(--border);border-top:none;border-radius:0 0 6px 6px;
    background:var(--panel);padding:1.2rem;min-height:340px}
  .pane{display:none}.pane.active{display:block}
  .meter{margin-bottom:.9rem}
  .meter-top{display:flex;justify-content:space-between;font-size:.78rem;margin-bottom:.25rem}
  .meter-top .lbl{color:var(--dim);text-transform:uppercase;letter-spacing:.5px}
  .meter-top .val{font-weight:700}
  .blocks{font-family:'JetBrains Mono',monospace;letter-spacing:-1px;font-size:1.05rem;
    line-height:1;overflow:hidden;white-space:nowrap}
  .row2{display:grid;grid-template-columns:1fr 1fr;gap:1.5rem}
  .cores{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:.5rem .9rem}
  .core{font-size:.72rem}
  .core-top{display:flex;justify-content:space-between;color:var(--dim);margin-bottom:.1rem}
  .stat-line{display:flex;justify-content:space-between;padding:.35rem 0;
    border-bottom:1px solid var(--border);font-size:.82rem}
  .stat-line:last-child{border:none}
  .stat-line .k{color:var(--dim)}
  .stat-line .v{font-weight:600;color:var(--txt)}
  .gpu-block{border:1px solid var(--border);border-radius:6px;padding:1rem;margin-bottom:1rem;background:var(--panel2)}
  .gpu-h{display:flex;justify-content:space-between;align-items:center;margin-bottom:.8rem}
  .gpu-h .gn{color:var(--cyan);font-weight:700;font-size:.85rem}
  .gpu-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:.6rem;margin-top:.8rem;font-size:.75rem}
  .gpu-grid .cell{background:var(--panel);border:1px solid var(--border);border-radius:4px;padding:.5rem}
  .gpu-grid .cell .ck{color:var(--dim);font-size:.68rem;text-transform:uppercase}
  .gpu-grid .cell .cv{font-weight:700;font-size:.95rem;margin-top:.15rem}
  .foot{text-align:center;color:var(--dim);font-size:.72rem;margin-top:.8rem}
  .spark{height:46px;margin-top:.3rem}
  .history{margin-top:1rem;border:1px solid var(--border);border-radius:6px;padding:.8rem;background:var(--panel2)}
  .history-row{display:grid;grid-template-columns:1fr 1fr auto;gap:.6rem;align-items:end}
  .history-row label{font-size:.72rem;color:var(--dim);display:block;margin-bottom:.25rem}
  .history-row input,.history-row button{
    width:100%;padding:.45rem .5rem;background:var(--panel);border:1px solid var(--border);
    color:var(--txt);border-radius:4px;font-family:inherit;font-size:.8rem
  }
  .history-row button{cursor:pointer;background:#1b2131;font-weight:700}
  .history-meta{margin-top:.7rem;font-size:.75rem;color:var(--dim)}
  .history-list{margin-top:.6rem;max-height:180px;overflow:auto;font-size:.74rem;border-top:1px solid var(--border)}
  .history-line{display:grid;grid-template-columns:90px repeat(5,1fr);gap:.5rem;padding:.35rem 0;border-bottom:1px solid var(--border)}
</style>
</head>
<body>
  <div class="head">
    <div class="title">server<span>.monitor</span></div>
    <div id="badge" class="badge b-ok">● HEALTHY</div>
  </div>
  <div class="tabs" id="tabs">
    <div class="tab active" data-t="cpu">CPU<span class="mini" id="t-cpu">—</span></div>
    <div class="tab" data-t="gpu">GPU<span class="mini" id="t-gpu">—</span></div>
    <div class="tab" data-t="ram">RAM<span class="mini" id="t-ram">—</span></div>
    <div class="tab" data-t="disk">DISK/NET<span class="mini" id="t-disk">—</span></div>
  </div>
  <div class="body">
    <div class="pane active" id="p-cpu">
      <div class="meter">
        <div class="meter-top"><span class="lbl">Total CPU</span><span class="val" id="cpu-v">0%</span></div>
        <div class="blocks" id="cpu-bar"></div>
        <div class="spark"><canvas id="cpu-spark"></canvas></div>
      </div>
      <div class="stat-line"><span class="k">Frequency</span><span class="v" id="cpu-freq">—</span></div>
      <div class="stat-line"><span class="k">Load avg (1/5/15m)</span><span class="v" id="cpu-load">—</span></div>
      <div style="margin:1rem 0 .6rem;color:var(--dim);font-size:.75rem;text-transform:uppercase;letter-spacing:1px">Per-Core</div>
      <div class="cores" id="cores"></div>
    </div>
    <div class="pane" id="p-gpu"></div>
    <div class="pane" id="p-ram">
      <div class="row2">
        <div>
          <div class="meter"><div class="meter-top"><span class="lbl">RAM</span><span class="val" id="ram-v">0%</span></div>
          <div class="blocks" id="ram-bar"></div></div>
          <div class="spark"><canvas id="ram-spark"></canvas></div>
        </div>
        <div>
          <div class="stat-line"><span class="k">Used</span><span class="v" id="ram-used">—</span></div>
          <div class="stat-line"><span class="k">Available</span><span class="v" id="ram-avail">—</span></div>
          <div class="stat-line"><span class="k">Cached</span><span class="v" id="ram-cached">—</span></div>
          <div class="stat-line"><span class="k">Total</span><span class="v" id="ram-total">—</span></div>
        </div>
      </div>
      <div style="margin:1.2rem 0 .6rem;color:var(--dim);font-size:.75rem;text-transform:uppercase;letter-spacing:1px">Swap</div>
      <div class="meter"><div class="meter-top"><span class="lbl">Swap</span><span class="val" id="swap-v">0%</span></div>
      <div class="blocks" id="swap-bar"></div></div>
    </div>
    <div class="pane" id="p-disk">
      <div class="meter"><div class="meter-top"><span class="lbl">Disk /</span><span class="val" id="disk-v">0%</span></div>
      <div class="blocks" id="disk-bar"></div></div>
      <div class="stat-line"><span class="k">Used / Total</span><span class="v" id="disk-ut">—</span></div>
      <div style="margin:1.2rem 0 .6rem;color:var(--dim);font-size:.75rem;text-transform:uppercase;letter-spacing:1px">Network</div>
      <div class="row2">
        <div><div class="stat-line"><span class="k">⬇ Download</span><span class="v" id="net-down" style="color:var(--green)">—</span></div></div>
        <div><div class="stat-line"><span class="k">⬆ Upload</span><span class="v" id="net-up" style="color:var(--blue)">—</span></div></div>
      </div>
      <div class="spark" style="height:80px;margin-top:1rem"><canvas id="net-spark"></canvas></div>
      <div class="history">
        <div style="color:var(--dim);font-size:.75rem;text-transform:uppercase;letter-spacing:1px">History (Backdated)</div>
        <div class="history-row">
          <div>
            <label for="h-from">From</label>
            <input id="h-from" type="datetime-local">
          </div>
          <div>
            <label for="h-to">To</label>
            <input id="h-to" type="datetime-local">
          </div>
          <div>
            <button id="h-load" type="button">Load</button>
          </div>
        </div>
        <div class="history-meta" id="h-meta">No query yet.</div>
        <div class="history-list" id="h-list"></div>
      </div>
    </div>
  </div>
  <div class="foot" id="foot">connecting...</div>

<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<script>
const BLK=['','▏','▎','▍','▌','▋','▊','▉','█'];
function bar(pct,width){
  const total=width*8, filled=Math.round(pct/100*total);
  let full=Math.floor(filled/8), rem=filled%8, s='█'.repeat(full);
  if(rem>0){s+=BLK[rem];full++}
  s+='░'.repeat(Math.max(0,width-full));
  return s;
}
const col=p=>p<60?'var(--green)':p<85?'var(--yellow)':'var(--red)';
const hex=p=>p<60?'#3ddc84':p<85?'#f5c451':'#ff5c6c';

// tabs
document.querySelectorAll('.tab').forEach(t=>t.onclick=()=>{
  document.querySelectorAll('.tab').forEach(x=>x.classList.remove('active'));
  document.querySelectorAll('.pane').forEach(x=>x.classList.remove('active'));
  t.classList.add('active');
  document.getElementById('p-'+t.dataset.t).classList.add('active');
});

const MAX=40, charts={};
function spark(id,color){
  const el=document.getElementById(id); if(!el)return null;
  return new Chart(el.getContext('2d'),{type:'line',
    data:{labels:Array(MAX).fill(''),datasets:[{data:Array(MAX).fill(0),
      borderColor:color,backgroundColor:color+'18',fill:true,tension:.35,pointRadius:0,borderWidth:1.5}]},
    options:{responsive:true,maintainAspectRatio:false,animation:false,
      plugins:{legend:{display:false}},
      scales:{x:{display:false},y:{min:0,max:100,display:false}}}});
}
function push(c,v){if(!c)return;c.data.datasets[0].data.push(v);c.data.datasets[0].data.shift();c.update('none')}

function toInputLocal(d){
  const off=d.getTimezoneOffset()*60000;
  return new Date(d.getTime()-off).toISOString().slice(0,16);
}

function fmtTs(ts){
  return new Date(ts*1000).toLocaleString();
}

async function loadHistory(){
  const from=document.getElementById('h-from').value;
  const to=document.getElementById('h-to').value;
  const meta=document.getElementById('h-meta');
  const list=document.getElementById('h-list');
  if(!from||!to){meta.textContent='Please select From and To.';return}
  try{
    const q='/api/history?from='+encodeURIComponent(from)+'&to='+encodeURIComponent(to)+'&limit=500';
    const r=await fetch(q);
    const d=await r.json();
    if(!r.ok){throw new Error(d.detail||'history request failed')}
    meta.textContent='Found '+d.count+' records.';
    list.innerHTML=d.items.map(x=>`
      <div class="history-line">
        <span>${fmtTs(x.ts)}</span>
        <span>CPU ${x.cpu}%</span>
        <span>RAM ${x.ram_pct}%</span>
        <span>GPU ${x.gpu_util_max}%</span>
        <span>VRAM ${x.gpu_vram_max}%</span>
        <span>NET ${x.net_down}/${x.net_up}</span>
      </div>
    `).join('') || '<div class="history-line"><span>No data</span><span>-</span><span>-</span><span>-</span><span>-</span><span>-</span></div>';
  }catch(e){
    meta.textContent='Error: '+e.message;
    list.innerHTML='';
  }
}

let gpuBuilt=false, netChart=null;
function buildGpu(d){
  document.getElementById('p-gpu').innerHTML=d.gpus.map((g,i)=>`
    <div class="gpu-block">
      <div class="gpu-h"><span class="gn">▸ GPU${i}  ${g.name}</span><span class="val" id="g${i}-util">0%</span></div>
      <div class="meter"><div class="meter-top"><span class="lbl">Core Util</span></div>
        <div class="blocks" id="g${i}-ubar"></div></div>
      <div class="meter"><div class="meter-top"><span class="lbl">VRAM <span id="g${i}-vtxt"></span></span><span class="val" id="g${i}-vpct"></span></div>
        <div class="blocks" id="g${i}-vbar"></div></div>
      <div class="gpu-grid">
        <div class="cell"><div class="ck">Temp</div><div class="cv" id="g${i}-temp"></div></div>
        <div class="cell"><div class="ck">Power</div><div class="cv" id="g${i}-pwr"></div></div>
        <div class="cell"><div class="ck">Core Clk</div><div class="cv" id="g${i}-clk"></div></div>
        <div class="cell"><div class="ck">Fan</div><div class="cv" id="g${i}-fan"></div></div>
      </div>
    </div>`).join('');
  gpuBuilt=true;
}

async function tick(){
  try{
    const r=await fetch('/api/stats'); const d=await r.json();
    // badge
    const b=document.getElementById('badge');
    b.className='badge '+(d.status==='OK'?'b-ok':d.status==='Busy'?'b-busy':'b-over');
    b.textContent='● '+d.status.toUpperCase();
    // tab minis
    document.getElementById('t-cpu').textContent=d.cpu.toFixed(0)+'%';
    const gpuMax=d.gpus.length?Math.max(...d.gpus.map(g=>g.util)):0;
    document.getElementById('t-gpu').textContent=gpuMax+'%';
    document.getElementById('t-ram').textContent=d.ram_pct.toFixed(0)+'%';
    document.getElementById('t-disk').textContent=d.disk_pct.toFixed(0)+'%';

    // CPU
    const cw=46;
    const cb=document.getElementById('cpu-bar');cb.textContent=bar(d.cpu,cw);cb.style.color=col(d.cpu);
    document.getElementById('cpu-v').textContent=d.cpu.toFixed(1)+'%';
    document.getElementById('cpu-v').style.color=col(d.cpu);
    document.getElementById('cpu-freq').textContent=d.cpu_freq+' / '+d.cpu_freq_max+' MHz';
    document.getElementById('cpu-load').textContent=d.load.join('  ');
    document.getElementById('cores').innerHTML=d.cpu_cores.map((c,i)=>`
      <div class="core"><div class="core-top"><span>CPU${i}</span><span>${c.toFixed(0)}%</span></div>
      <div class="blocks" style="color:${hex(c)};font-size:.85rem">${bar(c,14)}</div></div>`).join('');
    push(charts.cpu,d.cpu);

    // GPU
    if(!gpuBuilt)buildGpu(d);
    d.gpus.forEach((g,i)=>{
      const ub=document.getElementById('g'+i+'-ubar');ub.textContent=bar(g.util,46);ub.style.color=col(g.util);
      const vb=document.getElementById('g'+i+'-vbar');vb.textContent=bar(g.vram_pct,46);vb.style.color=col(g.vram_pct);
      document.getElementById('g'+i+'-util').textContent=g.util+'%';
      document.getElementById('g'+i+'-util').style.color=col(g.util);
      document.getElementById('g'+i+'-vtxt').textContent=g.vram_used+'/'+g.vram_total+'GB';
      document.getElementById('g'+i+'-vpct').textContent=g.vram_pct+'%';
      document.getElementById('g'+i+'-temp').textContent=g.temp+'°C';
      document.getElementById('g'+i+'-pwr').textContent=g.power+'/'+g.power_cap+'W';
      document.getElementById('g'+i+'-clk').textContent=g.clock+' MHz';
      document.getElementById('g'+i+'-fan').textContent=g.fan+'%';
    });

    // RAM
    const rb=document.getElementById('ram-bar');rb.textContent=bar(d.ram_pct,46);rb.style.color=col(d.ram_pct);
    document.getElementById('ram-v').textContent=d.ram_pct.toFixed(1)+'%';
    document.getElementById('ram-used').textContent=d.ram_used+' GB';
    document.getElementById('ram-avail').textContent=d.ram_avail+' GB';
    document.getElementById('ram-cached').textContent=d.ram_cached+' GB';
    document.getElementById('ram-total').textContent=d.ram_total+' GB';
    const sb=document.getElementById('swap-bar');sb.textContent=bar(d.swap_pct,46);sb.style.color=col(d.swap_pct);
    document.getElementById('swap-v').textContent=d.swap_used+'/'+d.swap_total+'GB ('+d.swap_pct+'%)';
    push(charts.ram,d.ram_pct);

    // DISK/NET
    const db=document.getElementById('disk-bar');db.textContent=bar(d.disk_pct,46);db.style.color=col(d.disk_pct);
    document.getElementById('disk-v').textContent=d.disk_pct+'%';
    document.getElementById('disk-ut').textContent=d.disk_used+' / '+d.disk_total+' GB';
    document.getElementById('net-down').textContent=d.net_down+' MB/s';
    document.getElementById('net-up').textContent=d.net_up+' MB/s';
    if(netChart){netChart.data.datasets[0].data.push(d.net_down);netChart.data.datasets[0].data.shift();
      netChart.data.datasets[1].data.push(d.net_up);netChart.data.datasets[1].data.shift();netChart.update('none')}

    document.getElementById('foot').textContent='last update '+new Date().toLocaleTimeString()+'  ·  refresh 2s';
  }catch(e){document.getElementById('badge').textContent='● OFFLINE';}
}

window.onload=()=>{
  charts.cpu=spark('cpu-spark','#4d9fff');
  charts.ram=spark('ram-spark','#b073ff');
  const ne=document.getElementById('net-spark');
  netChart=new Chart(ne.getContext('2d'),{type:'line',
    data:{labels:Array(MAX).fill(''),datasets:[
      {data:Array(MAX).fill(0),borderColor:'#3ddc84',backgroundColor:'#3ddc8418',fill:true,tension:.35,pointRadius:0,borderWidth:1.5,label:'down'},
      {data:Array(MAX).fill(0),borderColor:'#4d9fff',backgroundColor:'#4d9fff18',fill:true,tension:.35,pointRadius:0,borderWidth:1.5,label:'up'}]},
    options:{responsive:true,maintainAspectRatio:false,animation:false,
      plugins:{legend:{display:false}},scales:{x:{display:false},y:{min:0,display:false}}}});
  const now=new Date();
  document.getElementById('h-to').value=toInputLocal(now);
  document.getElementById('h-from').value=toInputLocal(new Date(now.getTime()-60*60*1000));
  document.getElementById('h-load').onclick=loadHistory;
  tick(); setInterval(tick,2000);
};
</script>
</body>
</html>
"""
