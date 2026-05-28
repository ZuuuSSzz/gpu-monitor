(function () {
  const SPARK_LEN = 60;
  const charts = {};
  let ws = null;
  let backoff = 1000;
  let gpusBuilt = false;
  let gpuCount = 0;

  // ---------------- helpers ----------------
  const $ = (id) => document.getElementById(id);
  const classFor = (pct) => (pct < 60 ? "ok" : pct < 85 ? "warn" : "crit");
  const cssVar = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

  function escape(s) {
    return String(s).replace(/[<>&"']/g, c => ({
      "<": "&lt;", ">": "&gt;", "&": "&amp;", "\"": "&quot;", "'": "&#39;"
    }[c]));
  }

  // ---------------- SVG ring ----------------
  function ensureRing(parent, size) {
    let svg = parent.querySelector("svg");
    if (svg) return svg;
    const ns = "http://www.w3.org/2000/svg";
    svg = document.createElementNS(ns, "svg");
    svg.setAttribute("viewBox", `0 0 ${size} ${size}`);
    svg.setAttribute("width", size);
    svg.setAttribute("height", size);
    svg.classList.add("ring");
    const cx = size / 2, cy = size / 2, r = size / 2 - 10;
    const bg = document.createElementNS(ns, "circle");
    bg.setAttribute("cx", cx); bg.setAttribute("cy", cy); bg.setAttribute("r", r);
    bg.setAttribute("fill", "none");
    bg.setAttribute("stroke", "var(--panel-2)");
    bg.setAttribute("stroke-width", "10");
    const fg = document.createElementNS(ns, "circle");
    fg.setAttribute("cx", cx); fg.setAttribute("cy", cy); fg.setAttribute("r", r);
    fg.setAttribute("fill", "none");
    fg.setAttribute("stroke", "var(--green)");
    fg.setAttribute("stroke-width", "10");
    fg.setAttribute("stroke-linecap", "round");
    fg.setAttribute("transform", `rotate(-90 ${cx} ${cy})`);
    const C = 2 * Math.PI * r;
    fg.setAttribute("stroke-dasharray", C);
    fg.setAttribute("stroke-dashoffset", C);
    fg.style.transition = "stroke-dashoffset 0.4s ease, stroke 0.3s";
    fg.dataset.c = C;
    fg.classList.add("ring-fg");
    const txt = document.createElementNS(ns, "text");
    txt.setAttribute("x", cx); txt.setAttribute("y", cy + 5);
    txt.setAttribute("text-anchor", "middle");
    txt.setAttribute("fill", "currentColor");
    txt.setAttribute("font-family", "JetBrains Mono, ui-monospace, monospace");
    txt.setAttribute("font-size", size > 120 ? "26" : "20");
    txt.setAttribute("font-weight", "700");
    txt.textContent = "0%";
    txt.classList.add("ring-text");
    svg.appendChild(bg); svg.appendChild(fg); svg.appendChild(txt);
    parent.appendChild(svg);
    return svg;
  }
  function setRing(svg, pct) {
    if (!svg) return;
    const fg = svg.querySelector(".ring-fg");
    const txt = svg.querySelector(".ring-text");
    const C = parseFloat(fg.dataset.c);
    fg.setAttribute("stroke-dashoffset", C * (1 - pct / 100));
    const cl = classFor(pct);
    fg.setAttribute("stroke", cl === "ok" ? "var(--green)" : cl === "warn" ? "var(--amber)" : "var(--red)");
    txt.textContent = Math.round(pct) + "%";
  }

  // ---------------- sparklines ----------------
  function makeSpark(parent, color) {
    let canvas = parent.querySelector("canvas");
    if (!canvas) {
      canvas = document.createElement("canvas");
      parent.appendChild(canvas);
    }
    return new Chart(canvas.getContext("2d"), {
      type: "line",
      data: {
        labels: Array(SPARK_LEN).fill(""),
        datasets: [{
          data: Array(SPARK_LEN).fill(0),
          borderColor: color, backgroundColor: color + "22",
          fill: true, tension: 0.35, pointRadius: 0, borderWidth: 1.5,
        }],
      },
      options: {
        responsive: true, maintainAspectRatio: false, animation: false,
        plugins: { legend: { display: false }, tooltip: { enabled: false } },
        scales: { x: { display: false }, y: { display: false, min: 0, max: 100 } },
      },
    });
  }
  function pushSpark(c, v) {
    if (!c) return;
    c.data.datasets[0].data.push(v);
    c.data.datasets[0].data.shift();
    c.update("none");
  }

  // ---------------- bar ----------------
  function setBar(id, pct, pctId) {
    const fill = $(id);
    if (fill) {
      fill.style.width = Math.min(100, Math.max(0, pct)) + "%";
      fill.className = "bar-fill fill-" + classFor(pct);
    }
    if (pctId) {
      const el = $(pctId);
      if (el) el.textContent = Math.round(pct) + "%";
    }
  }

  // ---------------- GPU cards ----------------
  function buildGpus(gpus) {
    const root = $("gpus");
    root.innerHTML = gpus.map((g, i) => `
      <article class="card gpu-card" id="gpu-${i}">
        <div class="gpu-head">
          <span class="gpu-name">▸ GPU${i}  ${escape(g.name)}</span>
          <span class="util-val" id="g${i}-util">0%</span>
        </div>
        <div class="bar-row"><span class="bar-label">Util</span><div class="bar"><div class="bar-fill" id="g${i}-ubar"></div></div><span class="bar-val mono" id="g${i}-upct">—</span></div>
        <div class="bar-row"><span class="bar-label">VRAM</span><div class="bar"><div class="bar-fill" id="g${i}-vbar"></div></div><span class="bar-val mono" id="g${i}-vpct">—</span></div>
        <div class="gpu-grid">
          <div class="gpu-cell"><div class="k">Temp</div><div class="v" id="g${i}-temp">—</div></div>
          <div class="gpu-cell"><div class="k">Power</div><div class="v" id="g${i}-pwr">—</div></div>
          <div class="gpu-cell"><div class="k">Core Clk</div><div class="v" id="g${i}-clk">—</div></div>
          <div class="gpu-cell"><div class="k">Mem Clk</div><div class="v" id="g${i}-mclk">—</div></div>
          <div class="gpu-cell"><div class="k">Fan</div><div class="v" id="g${i}-fan">—</div></div>
          <div class="gpu-cell"><div class="k">VRAM</div><div class="v" id="g${i}-vraw">—</div></div>
        </div>
        <div class="gpu-procs">
          <h3 class="subhead">Processes</h3>
          <table><tbody id="g${i}-procs"></tbody></table>
        </div>
      </article>`).join("");
    gpusBuilt = true;
    gpuCount = gpus.length;
  }

  function renderGpu(i, g) {
    setBar(`g${i}-ubar`, g.util, `g${i}-upct`);
    setBar(`g${i}-vbar`, g.vram_pct, `g${i}-vpct`);
    $(`g${i}-util`).textContent = g.util + "%";
    $(`g${i}-util`).className = "util-val color-" + classFor(g.util);
    $(`g${i}-temp`).textContent = g.temp + "°C";
    $(`g${i}-temp`).className = "v color-" + (g.temp < 70 ? "ok" : g.temp < 85 ? "warn" : "crit");
    $(`g${i}-pwr`).textContent = `${g.power}/${g.power_cap} W`;
    $(`g${i}-clk`).textContent = g.clock + " MHz";
    $(`g${i}-mclk`).textContent = g.mem_clock + " MHz";
    $(`g${i}-fan`).textContent = g.fan + "%";
    $(`g${i}-vraw`).textContent = `${g.vram_used}/${g.vram_total} GB`;
    const card = $(`gpu-${i}`);
    if (card) {
      card.classList.remove("warn", "crit");
      if (g.temp >= 85 || g.vram_pct >= 90) card.classList.add("crit");
      else if (g.temp >= 75 || g.vram_pct >= 75) card.classList.add("warn");
    }
    const procs = $(`g${i}-procs`);
    if (procs) {
      procs.innerHTML = (g.procs || []).slice(0, 5).map(p =>
        `<tr><td>${p.pid}</td><td>${escape(p.name)}</td><td>${p.vram_mb} MB</td></tr>`).join("")
        || `<tr><td colspan="3" style="color:var(--dim)">—</td></tr>`;
    }
  }

  // ---------------- frame render ----------------
  function render(d) {
    if (d.error) return;

    // badge
    const badge = $("badge");
    const map = { OK: "ok", Busy: "busy", Overloaded: "crit" };
    badge.className = "badge badge-" + (map[d.status] || "ok");
    badge.textContent = "● " + (d.status || "").toUpperCase();

    // KPI rings
    setRing(charts.cpuRing, d.cpu.total);
    setRing(charts.ramRing, d.ram.pct);
    const gpuMax = d.gpus.length ? Math.max(...d.gpus.map(g => g.util)) : 0;
    setRing(charts.gpuRing, gpuMax);
    $("kpi-net-val").textContent = `↓${d.net.down_mbs} ↑${d.net.up_mbs} MB/s`;

    // KPI sparklines
    pushSpark(charts.cpuSpark, d.cpu.total);
    pushSpark(charts.ramSpark, d.ram.pct);
    pushSpark(charts.gpuSpark, gpuMax);
    pushSpark(charts.netKpiSpark, Math.min(100, d.net.down_mbs + d.net.up_mbs));
    if (charts.netSpark) {
      const ds = charts.netSpark.data.datasets;
      ds[0].data.push(d.net.down_mbs); ds[0].data.shift();
      ds[1].data.push(d.net.up_mbs);   ds[1].data.shift();
      charts.netSpark.update("none");
    }

    // CPU detail
    $("cpu-sub").textContent = `${d.cpu.total.toFixed(1)}%`;
    $("cpu-freq").textContent = `${d.cpu.freq} / ${d.cpu.freq_max} MHz`;
    $("cpu-load").textContent = d.cpu.load.join("  ");
    $("cpu-procs").textContent = d.cpu.proc_count;
    setRing(charts.cpuBigRing, d.cpu.total);
    $("cores").innerHTML = d.cpu.cores.map((c, i) =>
      `<div class="core">
         <div class="core-top"><span>CPU${i}</span><span>${c.toFixed(0)}%</span></div>
         <div class="core-bar"><div class="fill-${classFor(c)}" style="width:${c}%"></div></div>
       </div>`).join("");

    // GPUs
    if (!gpusBuilt || gpuCount !== d.gpus.length) buildGpus(d.gpus);
    d.gpus.forEach((g, i) => renderGpu(i, g));

    // RAM + Swap
    $("ram-sub").textContent = `${d.ram.used_gb} / ${d.ram.total_gb} GB`;
    setBar("ram-bar", d.ram.pct, "ram-pct");
    setBar("swap-bar", d.swap.pct, "swap-pct");
    $("ram-used").textContent   = d.ram.used_gb + " GB";
    $("ram-cached").textContent = d.ram.cached_gb + " GB";
    $("ram-avail").textContent  = d.ram.avail_gb + " GB";
    $("ram-total").textContent  = d.ram.total_gb + " GB";

    // Disk + Net
    setBar("disk-bar", d.disk.pct, "disk-pct");
    $("disk-ut").textContent = `${d.disk.used_gb} / ${d.disk.total_gb} GB`;
    $("net-down").textContent = d.net.down_mbs + " MB/s";
    $("net-up").textContent   = d.net.up_mbs + " MB/s";

    // top procs
    $("procs-body").innerHTML = (d.top_procs || []).map(p =>
      `<tr>
         <td class="mono">${p.pid}</td>
         <td>${escape(p.user)}</td>
         <td>${escape(p.name)}</td>
         <td class="r">${p.cpu.toFixed(1)}</td>
         <td class="r">${p.mem_mb}</td>
       </tr>`).join("");

    // footer
    const uptimeStr = fmtUptime(d.uptime_s || 0);
    $("foot").textContent =
      `last update ${new Date(d.ts * 1000).toLocaleTimeString()} · uptime ${uptimeStr} · push 2s`;
  }

  function fmtUptime(s) {
    const d = Math.floor(s / 86400);
    const h = Math.floor((s % 86400) / 3600);
    const m = Math.floor((s % 3600) / 60);
    return `${d}d ${h}h ${m}m`;
  }

  // ---------------- websocket ----------------
  async function connect() {
    try {
      const sys = await fetch("/api/system", { credentials: "include" }).then(r => {
        if (!r.ok) throw new Error("auth");
        return r.json();
      });
      $("sys-line").textContent =
        `${sys.hostname} · ${sys.os} · NVIDIA ${sys.driver || "—"} · CUDA ${sys.cuda || "—"}`;
      const proto = location.protocol === "https:" ? "wss:" : "ws:";
      const url = `${proto}//${location.host}/ws/stats?token=${encodeURIComponent(sys.ws_token)}`;
      ws = new WebSocket(url);
      ws.onopen = () => { backoff = 1000; };
      ws.onmessage = (e) => {
        try { render(JSON.parse(e.data)); } catch (err) { console.error(err); }
      };
      ws.onclose = scheduleReconnect;
      ws.onerror = () => { try { ws.close(); } catch {} };
    } catch (e) {
      scheduleReconnect();
    }
  }

  function scheduleReconnect() {
    const badge = $("badge");
    if (badge) { badge.className = "badge badge-off"; badge.textContent = "● OFFLINE"; }
    setTimeout(connect, backoff);
    backoff = Math.min(backoff * 2, 10000);
  }

  // ---------------- theme ----------------
  function initTheme() {
    const saved = localStorage.getItem("theme") || "dark";
    document.documentElement.setAttribute("data-theme", saved);
    $("theme-toggle").addEventListener("click", () => {
      const cur = document.documentElement.getAttribute("data-theme");
      const next = cur === "dark" ? "light" : "dark";
      document.documentElement.setAttribute("data-theme", next);
      localStorage.setItem("theme", next);
    });
  }

  // ---------------- init ----------------
  window.addEventListener("load", () => {
    initTheme();
    // KPI rings + sparks
    charts.cpuRing = ensureRing($("kpi-cpu").querySelector(".ring-wrap"), 110);
    charts.gpuRing = ensureRing($("kpi-gpu").querySelector(".ring-wrap"), 110);
    charts.ramRing = ensureRing($("kpi-ram").querySelector(".ring-wrap"), 110);
    charts.cpuSpark = makeSpark($("kpi-cpu").querySelector(".kpi-spark"), cssVar("--blue") || "#4d9fff");
    charts.gpuSpark = makeSpark($("kpi-gpu").querySelector(".kpi-spark"), cssVar("--cyan") || "#3de0e0");
    charts.ramSpark = makeSpark($("kpi-ram").querySelector(".kpi-spark"), cssVar("--purple") || "#b073ff");
    charts.netKpiSpark = makeSpark($("kpi-net").querySelector(".kpi-spark"), cssVar("--green") || "#3ddc84");

    // Big CPU ring in the CPU card
    charts.cpuBigRing = ensureRing(document.querySelector(".cpu-ring-slot"), 140);

    // Net chart in the disk/net card (dual line)
    const netCanvas = $("net-spark");
    charts.netSpark = new Chart(netCanvas.getContext("2d"), {
      type: "line",
      data: {
        labels: Array(SPARK_LEN).fill(""),
        datasets: [
          { data: Array(SPARK_LEN).fill(0), borderColor: "#3ddc84", backgroundColor: "#3ddc8422", fill: true, tension: 0.35, pointRadius: 0, borderWidth: 1.5 },
          { data: Array(SPARK_LEN).fill(0), borderColor: "#4d9fff", backgroundColor: "#4d9fff22", fill: true, tension: 0.35, pointRadius: 0, borderWidth: 1.5 },
        ],
      },
      options: {
        responsive: true, maintainAspectRatio: false, animation: false,
        plugins: { legend: { display: false } },
        scales: { x: { display: false }, y: { display: false, min: 0 } },
      },
    });

    connect();
  });
})();
