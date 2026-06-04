from config import Settings


def test_settings_defaults():
    s = Settings(_env_file=None)
    assert s.bind_host == "0.0.0.0"
    assert s.bind_port == 8000
    assert s.poll_interval == 2.0
