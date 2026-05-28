import logging
import platform
import time
from typing import Any

import psutil

log = logging.getLogger(__name__)

try:
    import pynvml
    pynvml.nvmlInit()
    NVML_OK = True
except Exception as e:
    log.warning("NVML init failed: %s", e)
    NVML_OK = False


def classify_status(cpu: float, ram: float, gpu_vram_max: float, gpu_util_max: float) -> str:
    if cpu > 90 or ram > 90 or gpu_vram_max > 90:
        return "Overloaded"
    if cpu > 60 or ram > 75 or gpu_util_max > 70:
        return "Busy"
    return "OK"


def _safe(fn, default=None):
    try:
        return fn()
    except Exception:
        return default


def get_system_info() -> dict[str, Any]:
    uname = platform.uname()
    driver = ""
    cuda = ""
    if NVML_OK:
        driver = _safe(lambda: pynvml.nvmlSystemGetDriverVersion(), b"") or b""
        if isinstance(driver, bytes):
            driver = driver.decode()
        cuda_int = _safe(lambda: pynvml.nvmlSystemGetCudaDriverVersion(), 0) or 0
        if cuda_int:
            cuda = f"{cuda_int // 1000}.{(cuda_int % 1000) // 10}"
    return {
        "hostname": uname.node,
        "os": f"{uname.system} {uname.release}",
        "kernel": uname.version,
        "driver": driver,
        "cuda": cuda,
        "nvml_ok": NVML_OK,
    }


class StatsCollector:
    def __init__(self):
        self._last_net_t = time.time()
        self._last_net_sent = 0
        self._last_net_recv = 0
        self._gpu_proc_cache: tuple[float, dict[int, list[dict]]] = (0.0, {})
        self._boot_time = psutil.boot_time()
        psutil.cpu_percent(interval=None, percpu=False)
        psutil.cpu_percent(interval=None, percpu=True)

    def _net(self) -> dict[str, float]:
        n = psutil.net_io_counters()
        now = time.time()
        dt = max(now - self._last_net_t, 0.001)
        first = self._last_net_sent == 0 and self._last_net_recv == 0
        up = (n.bytes_sent - self._last_net_sent) / dt / 1024**2
        down = (n.bytes_recv - self._last_net_recv) / dt / 1024**2
        self._last_net_t = now
        self._last_net_sent = n.bytes_sent
        self._last_net_recv = n.bytes_recv
        if first:
            return {"up_mbs": 0.0, "down_mbs": 0.0}
        return {"up_mbs": round(up, 2), "down_mbs": round(down, 2)}

    def _gpu_procs(self) -> dict[int, list[dict]]:
        now = time.time()
        if now - self._gpu_proc_cache[0] < 5.0:
            return self._gpu_proc_cache[1]
        out: dict[int, list[dict]] = {}
        if NVML_OK:
            for i in range(pynvml.nvmlDeviceGetCount()):
                h = pynvml.nvmlDeviceGetHandleByIndex(i)
                procs = []
                for getter in (pynvml.nvmlDeviceGetComputeRunningProcesses,
                               pynvml.nvmlDeviceGetGraphicsRunningProcesses):
                    for p in _safe(lambda g=getter, hh=h: g(hh), []) or []:
                        pname = _safe(lambda pid=p.pid: psutil.Process(pid).name(), "?")
                        procs.append({"pid": p.pid, "name": pname,
                                      "vram_mb": round((p.usedGpuMemory or 0) / 1024**2)})
                out[i] = procs
        self._gpu_proc_cache = (now, out)
        return out

    def _gpus(self) -> list[dict]:
        if not NVML_OK:
            return []
        procs_by_gpu = self._gpu_procs()
        gpus = []
        for i in range(pynvml.nvmlDeviceGetCount()):
            h = pynvml.nvmlDeviceGetHandleByIndex(i)
            name = _safe(lambda: pynvml.nvmlDeviceGetName(h), b"GPU")
            if isinstance(name, bytes):
                name = name.decode()
            u = _safe(lambda: pynvml.nvmlDeviceGetUtilizationRates(h))
            m = _safe(lambda: pynvml.nvmlDeviceGetMemoryInfo(h))
            t = _safe(lambda: pynvml.nvmlDeviceGetTemperature(h, pynvml.NVML_TEMPERATURE_GPU), 0)
            pwr = round((_safe(lambda: pynvml.nvmlDeviceGetPowerUsage(h), 0) or 0) / 1000)
            pwr_cap = round((_safe(lambda: pynvml.nvmlDeviceGetEnforcedPowerLimit(h), 0) or 0) / 1000)
            clk = _safe(lambda: pynvml.nvmlDeviceGetClockInfo(h, pynvml.NVML_CLOCK_GRAPHICS), 0)
            mclk = _safe(lambda: pynvml.nvmlDeviceGetClockInfo(h, pynvml.NVML_CLOCK_MEM), 0)
            fan = _safe(lambda: pynvml.nvmlDeviceGetFanSpeed(h), 0)
            vram_used = round(m.used / 1024**3, 2) if m else 0
            vram_total = round(m.total / 1024**3, 2) if m else 0
            vram_pct = round(m.used / m.total * 100, 1) if m and m.total else 0
            gpus.append({
                "idx": i, "name": name,
                "util": u.gpu if u else 0, "mem_util": u.memory if u else 0,
                "vram_used": vram_used, "vram_total": vram_total, "vram_pct": vram_pct,
                "temp": t, "power": pwr, "power_cap": pwr_cap,
                "clock": clk, "mem_clock": mclk, "fan": fan,
                "procs": procs_by_gpu.get(i, []),
            })
        return gpus

    def _top_procs(self, limit: int = 10) -> list[dict]:
        rows = []
        for p in psutil.process_iter(["pid", "name", "username", "cpu_percent", "memory_info"]):
            info = p.info
            rows.append({
                "pid": info["pid"],
                "user": info.get("username") or "",
                "name": info.get("name") or "",
                "cpu": info.get("cpu_percent") or 0.0,
                "mem_mb": round((info["memory_info"].rss if info.get("memory_info") else 0) / 1024**2),
            })
        rows.sort(key=lambda r: r["cpu"], reverse=True)
        return rows[:limit]

    def tick(self) -> dict[str, Any]:
        cpu_total = psutil.cpu_percent(interval=None)
        cpu_cores = psutil.cpu_percent(interval=None, percpu=True)
        freq = _safe(psutil.cpu_freq)
        load = _safe(psutil.getloadavg, (0, 0, 0))
        ram = psutil.virtual_memory()
        swap = psutil.swap_memory()
        disk = psutil.disk_usage("/")
        net = self._net()
        gpus = self._gpus()
        top = self._top_procs()
        vram_max = max((g["vram_pct"] for g in gpus), default=0)
        util_max = max((g["util"] for g in gpus), default=0)
        return {
            "ts": int(time.time()),
            "status": classify_status(cpu_total, ram.percent, vram_max, util_max),
            "uptime_s": int(time.time() - self._boot_time),
            "cpu": {
                "total": round(cpu_total, 1),
                "cores": [round(c, 1) for c in cpu_cores],
                "freq": round(freq.current) if freq else 0,
                "freq_max": round(freq.max) if freq else 0,
                "load": [round(x, 2) for x in load],
                "proc_count": len(psutil.pids()),
            },
            "ram": {
                "used_gb": round(ram.used / 1024**3, 2),
                "total_gb": round(ram.total / 1024**3, 2),
                "pct": ram.percent,
                "cached_gb": round(ram.cached / 1024**3, 2),
                "avail_gb": round(ram.available / 1024**3, 2),
            },
            "swap": {
                "used_gb": round(swap.used / 1024**3, 2),
                "total_gb": round(swap.total / 1024**3, 2),
                "pct": swap.percent,
            },
            "disk": {
                "used_gb": round(disk.used / 1024**3, 1),
                "total_gb": round(disk.total / 1024**3, 1),
                "pct": disk.percent,
            },
            "net": net,
            "gpus": gpus,
            "top_procs": top,
        }
