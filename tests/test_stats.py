from stats import StatsCollector, classify_status


def test_classify_status_ok():
    assert classify_status(cpu=10, ram=20, gpu_vram_max=30, gpu_util_max=40) == "OK"


def test_classify_status_busy():
    assert classify_status(cpu=70, ram=50, gpu_vram_max=50, gpu_util_max=50) == "Busy"


def test_classify_status_overloaded():
    assert classify_status(cpu=95, ram=50, gpu_vram_max=50, gpu_util_max=50) == "Overloaded"


def test_classify_status_overloaded_via_vram():
    assert classify_status(cpu=10, ram=20, gpu_vram_max=95, gpu_util_max=50) == "Overloaded"


def test_collector_produces_frame_with_required_keys():
    c = StatsCollector()
    c.tick()  # warm net delta
    frame = c.tick()
    for key in ("ts", "status", "uptime_s", "cpu", "ram", "swap", "disk", "net", "gpus", "top_procs"):
        assert key in frame, f"missing {key}"
    assert isinstance(frame["cpu"]["total"], (int, float))
    assert isinstance(frame["cpu"]["cores"], list)
    assert isinstance(frame["top_procs"], list)
