import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


@pytest.fixture
def tmp_db_path(tmp_path):
    return str(tmp_path / "test_state.db")


@pytest.fixture
def mock_config_data():
    return {
        "service_token": "test_token",
        "api_version": "5.131",
        "base_url": "https://api.vk.ru/method",
        "profile_path": "./test_chrome_profile",
        "headless": True,
        "queries": ["тест", "Python"],
        "user_id": 12345,
        "hashtags": ["#тест", "#Python"],
        "groups": [],
        "accounts": ["magnit"],
        "auto_friends": False,
        "auto_groups": False,
        "max_posts_per_query": 10,
        "max_posts_per_hashtag": 10,
        "max_posts_per_group": 10,
        "max_posts_per_account": 100,
        "max_posts_per_friend": 50,
        "max_friends_to_collect": 100,
        "min_friends_to_poll": 0,
        "max_groups_to_collect": 100,
        "days_back": 7,
        "stop_words": ["политика!"],
        "stop_words_file": "",
        "filter_mode": "stop_words",
        "likes_per_session_min": 3,
        "likes_per_session_max": 5,
        "sessions_per_day": 2,
        "min_delay_sec": 1,
        "max_delay_sec": 2,
        "view_delay_min_sec": 1,
        "view_delay_max_sec": 2,
        "max_captcha_streak": 3,
        "log_level": "DEBUG",
        "log_file": "test_autoliker.log",
        "db_path": "test_state.db",
        "llm_model": "openai/gpt-4o-mini",
        "llm_api_base": "",
        "llm_api_key": "test-llm-key",
        "llm_system_prompt": "",
        "llm_stop_topics": ["политика", "религия"],
        "llm_timeout": 10,
        "llm_max_tokens": 1000,
        "llm_max_text_length": 1000,
        "llm_ssl_verify": True,
        "closed_wall_ttl_days": 7,
        "profile_max_size_mb": 500,
    }


@pytest.fixture
def mock_config(mock_config_data, monkeypatch):
    from settings import Settings

    monkeypatch.delenv("VK_SERVICE_TOKEN", raising=False)
    monkeypatch.delenv("VK_LLM_API_KEY", raising=False)
    return Settings(_env_file=None, **mock_config_data)


@pytest.fixture
def mock_logger(mock_config):
    from logger import AppLogger

    return AppLogger(mock_config)


@pytest.fixture
def mock_driver():
    return MagicMock()


@pytest.fixture
def http_fixture_server(monkeypatch, tmp_path):
    import functools
    import http.server
    import threading

    fixtures_dir = Path(__file__).parent / "fixtures"

    handler = functools.partial(
        http.server.SimpleHTTPRequestHandler,
        directory=str(fixtures_dir),
    )

    server = http.server.HTTPServer(("localhost", 0), handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    yield f"http://localhost:{port}"

    server.shutdown()
    server.server_close()
