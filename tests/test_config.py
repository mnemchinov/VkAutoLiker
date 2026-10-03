"""Тесты Settings (pydantic-settings): дефолты, env vars, SecretStr, валидация."""

import pytest
from pydantic import ValidationError

from settings import Settings, get_settings


class TestSettings:
    """Тесты создания Settings с явными значениями и дефолтами."""

    def test_creates_with_explicit_values(self, mock_config_data, monkeypatch):
        """Settings принимает плоские kwargs и возвращает корректные значения."""
        monkeypatch.delenv("VK_SERVICE_TOKEN", raising=False)
        monkeypatch.delenv("VK_LLM_API_KEY", raising=False)
        s = Settings(_env_file=None, **mock_config_data)

        assert s.service_token.get_secret_value() == "test_token"
        assert s.api_version == "5.131"
        assert s.base_url == "https://api.vk.ru/method"
        assert s.headless is True
        assert s.profile_path == "./test_chrome_profile"

    def test_defaults(self, monkeypatch):
        """Settings без аргументов использует дефолты класса."""
        monkeypatch.delenv("VK_SERVICE_TOKEN", raising=False)
        monkeypatch.delenv("VK_LLM_API_KEY", raising=False)
        monkeypatch.delenv("VK_QUERIES", raising=False)
        s = Settings(_env_file=None)

        assert s.service_token.get_secret_value() == ""
        assert s.api_version == "5.131"
        assert s.likes_per_session_min == 20
        assert s.likes_per_session_max == 30
        assert s.days_back == 30
        assert s.filter_mode == "stop_words"
        assert s.queries == []

    def test_secret_str_masks_token(self, mock_config_data, monkeypatch):
        """SecretStr маскирует service_token в repr."""
        monkeypatch.delenv("VK_SERVICE_TOKEN", raising=False)
        monkeypatch.delenv("VK_LLM_API_KEY", raising=False)
        s = Settings(_env_file=None, **mock_config_data)

        assert "test_token" not in repr(s)
        assert "**********" in repr(s)

    def test_search_fields(self, mock_config_data, monkeypatch):
        """Поля поиска доступны на верхнем уровне."""
        monkeypatch.delenv("VK_SERVICE_TOKEN", raising=False)
        monkeypatch.delenv("VK_LLM_API_KEY", raising=False)
        s = Settings(_env_file=None, **mock_config_data)

        assert "тест" in s.queries
        assert "Python" in s.queries
        assert "#тест" in s.hashtags
        assert s.max_posts_per_query == 10
        assert s.user_id == 12345
        assert s.auto_friends is False
        assert s.max_friends_to_collect == 100

    def test_llm_fields(self, mock_config_data, monkeypatch):
        """LLM-поля доступны на верхнем уровне с llm_ префиксом."""
        monkeypatch.delenv("VK_SERVICE_TOKEN", raising=False)
        monkeypatch.delenv("VK_LLM_API_KEY", raising=False)
        s = Settings(_env_file=None, **mock_config_data)

        assert s.llm_model == "openai/gpt-4o-mini"
        assert s.llm_api_key.get_secret_value() == "test-llm-key"
        assert s.llm_timeout == 10
        assert s.llm_max_text_length == 500

    def test_limits_fields(self, mock_config_data, monkeypatch):
        """Поля лимитов доступны на верхнем уровне."""
        monkeypatch.delenv("VK_SERVICE_TOKEN", raising=False)
        monkeypatch.delenv("VK_LLM_API_KEY", raising=False)
        s = Settings(_env_file=None, **mock_config_data)

        assert s.likes_per_session_min == 3
        assert s.likes_per_session_max == 5
        assert s.sessions_per_day == 2
        assert s.min_delay_sec == 1
        assert s.max_delay_sec == 2


class TestEnvVars:
    """Тесты приоритета env vars над дефолтами."""

    def test_service_token_env_var(self, monkeypatch):
        """VK_SERVICE_TOKEN env var перекрывает дефолт."""
        monkeypatch.setenv("VK_SERVICE_TOKEN", "env_token")
        monkeypatch.delenv("VK_LLM_API_KEY", raising=False)
        s = Settings(_env_file=None)

        assert s.service_token.get_secret_value() == "env_token"

    def test_llm_api_key_env_var(self, monkeypatch):
        """VK_LLM_API_KEY env var перекрывает дефолт."""
        monkeypatch.delenv("VK_SERVICE_TOKEN", raising=False)
        monkeypatch.setenv("VK_LLM_API_KEY", "env_llm_key")
        s = Settings(_env_file=None)

        assert s.llm_api_key.get_secret_value() == "env_llm_key"

    def test_queries_env_var_comma_separated(self, monkeypatch):
        """VK_QUERIES парсится как comma-separated список."""
        monkeypatch.delenv("VK_SERVICE_TOKEN", raising=False)
        monkeypatch.delenv("VK_LLM_API_KEY", raising=False)
        monkeypatch.setenv("VK_QUERIES", "vk новости,россия,python")
        s = Settings(_env_file=None)

        assert s.queries == ["vk новости", "россия", "python"]

    def test_stop_words_env_var_comma_separated(self, monkeypatch):
        """VK_STOP_WORDS парсится как comma-separated список."""
        monkeypatch.delenv("VK_SERVICE_TOKEN", raising=False)
        monkeypatch.delenv("VK_LLM_API_KEY", raising=False)
        monkeypatch.setenv("VK_STOP_WORDS", "политика,религия,наркотики")
        s = Settings(_env_file=None)

        assert s.stop_words == ["политика", "религия", "наркотики"]


class TestValidation:
    """Тесты валидации @model_validator и @field_validator."""

    def test_filter_mode_invalid_raises(self, monkeypatch):
        """Неверный filter_mode вызывает ValidationError."""
        monkeypatch.delenv("VK_SERVICE_TOKEN", raising=False)
        monkeypatch.delenv("VK_LLM_API_KEY", raising=False)
        with pytest.raises(ValidationError):
            Settings(_env_file=None, filter_mode="invalid")

    def test_filter_mode_llm_without_model_raises(self, monkeypatch):
        """filter_mode='llm' без llm_model вызывает ValidationError."""
        monkeypatch.delenv("VK_SERVICE_TOKEN", raising=False)
        monkeypatch.delenv("VK_LLM_API_KEY", raising=False)
        with pytest.raises(ValidationError):
            Settings(_env_file=None, filter_mode="llm", llm_model="")

    def test_min_greater_than_max_raises(self, monkeypatch):
        """likes_per_session_min > max вызывает ValidationError."""
        monkeypatch.delenv("VK_SERVICE_TOKEN", raising=False)
        monkeypatch.delenv("VK_LLM_API_KEY", raising=False)
        with pytest.raises(ValidationError):
            Settings(_env_file=None, likes_per_session_min=10, likes_per_session_max=5)

    def test_days_back_zero_raises(self, monkeypatch):
        """days_back <= 0 вызывает ValidationError."""
        monkeypatch.delenv("VK_SERVICE_TOKEN", raising=False)
        monkeypatch.delenv("VK_LLM_API_KEY", raising=False)
        with pytest.raises(ValidationError):
            Settings(_env_file=None, days_back=0)

    def test_auto_friends_without_user_id_raises(self, monkeypatch):
        """auto_friends=True без user_id вызывает ValidationError."""
        monkeypatch.delenv("VK_SERVICE_TOKEN", raising=False)
        monkeypatch.delenv("VK_LLM_API_KEY", raising=False)
        with pytest.raises(ValidationError):
            Settings(_env_file=None, auto_friends=True, user_id=0)


class TestGetSettings:
    """Тесты get_settings() — обёртка ValidationError в ValueError."""

    def test_get_settings_returns_settings(self, monkeypatch):
        """get_settings() возвращает Settings при корректных env vars."""
        monkeypatch.delenv("VK_SERVICE_TOKEN", raising=False)
        monkeypatch.delenv("VK_LLM_API_KEY", raising=False)
        s = get_settings()
        assert isinstance(s, Settings)

    def test_get_settings_wraps_validation_error(self, monkeypatch):
        """get_settings() обёртывает ValidationError в ValueError."""
        monkeypatch.delenv("VK_SERVICE_TOKEN", raising=False)
        monkeypatch.delenv("VK_LLM_API_KEY", raising=False)
        monkeypatch.setenv("VK_FILTER_MODE", "invalid")
        with pytest.raises(ValueError):
            get_settings()
