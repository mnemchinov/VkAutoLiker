import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


@pytest.fixture
def tmp_db_path(tmp_path):
    return str(tmp_path / "test_state.db")


@pytest.fixture
def mock_config_data():
    return {
        "api": {
            "service_token": "test_token",
            "api_version": "5.131",
            "base_url": "https://api.vk.ru/method",
        },
        "browser": {
            "profile_path": "./test_chrome_profile",
            "headless": True,
        },
        "search": {
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
            "max_groups_to_collect": 100,
            "days_back": 7,
        },
        "limits": {
            "likes_per_session": 5,
            "sessions_per_day": 2,
            "min_delay_sec": 1,
            "max_delay_sec": 2,
            "view_delay_min_sec": 1,
            "view_delay_max_sec": 2,
            "max_captcha_streak": 3,
        },
        "logging": {
            "level": "DEBUG",
            "file": "test_autoliker.log",
        },
        "state": {
            "db_path": "test_state.db",
        },
    }


@pytest.fixture
def mock_config_file(tmp_path, mock_config_data):
    config_file = tmp_path / "config.yaml"
    with open(config_file, "w", encoding="utf-8") as f:
        yaml.dump(mock_config_data, f, allow_unicode=True)
    return str(config_file)


@pytest.fixture
def mock_config(mock_config_file):
    from config import ConfigLoader
    loader = ConfigLoader(mock_config_file)
    return loader.load()


@pytest.fixture
def mock_logger(mock_config):
    from logger import AppLogger
    return AppLogger(mock_config)


@pytest.fixture
def mock_driver():
    return MagicMock()


@pytest.fixture
def http_fixture_server(monkeypatch, tmp_path):
    import http.server
    import threading
    import functools

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
