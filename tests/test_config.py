from config import (
    ApiConfig,
    AppConfig,
    BrowserConfig,
    LimitsConfig,
    LLMConfig,
    SearchConfig,
    load_config,
)


class TestConfigLoader:
    def test_loads_config(self, mock_config_file, monkeypatch):
        monkeypatch.delenv("VK_SERVICE_TOKEN", raising=False)
        monkeypatch.delenv("VK_LLM_API_KEY", raising=False)
        config = load_config(mock_config_file, _env_file=None)

        assert isinstance(config, AppConfig)
        assert isinstance(config.api, ApiConfig)
        assert config.api.service_token.get_secret_value() == "test_token"
        assert config.api.api_version == "5.131"
        assert isinstance(config.browser, BrowserConfig)
        assert config.browser.headless is True
        assert config.browser.profile_path == "./test_chrome_profile"

    def test_search_config(self, mock_config_file, monkeypatch):
        monkeypatch.delenv("VK_SERVICE_TOKEN", raising=False)
        monkeypatch.delenv("VK_LLM_API_KEY", raising=False)
        config = load_config(mock_config_file, _env_file=None)

        assert isinstance(config.search, SearchConfig)
        assert "тест" in config.search.queries
        assert "Python" in config.search.queries
        assert "#тест" in config.search.hashtags
        assert "#Python" in config.search.hashtags
        assert config.search.max_posts_per_query == 10
        assert config.search.user_id == 12345
        assert config.search.auto_friends is False
        assert config.search.auto_groups is False
        assert config.search.max_posts_per_hashtag == 10
        assert config.search.max_posts_per_friend == 50
        assert config.search.max_friends_to_collect == 100

    def test_accounts_config(self, mock_config_file, monkeypatch):
        monkeypatch.delenv("VK_SERVICE_TOKEN", raising=False)
        monkeypatch.delenv("VK_LLM_API_KEY", raising=False)
        config = load_config(mock_config_file, _env_file=None)

        assert isinstance(config.search, SearchConfig)
        assert "magnit" in config.search.accounts
        assert config.search.max_posts_per_account == 100

    def test_limits_config(self, mock_config_file, monkeypatch):
        monkeypatch.delenv("VK_SERVICE_TOKEN", raising=False)
        monkeypatch.delenv("VK_LLM_API_KEY", raising=False)
        config = load_config(mock_config_file, _env_file=None)

        assert isinstance(config.limits, LimitsConfig)
        assert config.limits.likes_per_session_min == 3
        assert config.limits.likes_per_session_max == 5
        assert config.limits.sessions_per_day == 2
        assert config.limits.min_delay_sec == 1
        assert config.limits.max_delay_sec == 2

    def test_file_not_found(self):
        try:
            load_config("/nonexistent/config.yaml", _env_file=None)
            assert False, "Should have raised FileNotFoundError"
        except FileNotFoundError:
            pass

    def test_llm_config(self, mock_config_file, monkeypatch):
        monkeypatch.delenv("VK_SERVICE_TOKEN", raising=False)
        monkeypatch.delenv("VK_LLM_API_KEY", raising=False)
        config = load_config(mock_config_file, _env_file=None)

        assert isinstance(config.llm, LLMConfig)
        assert config.llm.model == "openai/gpt-4o-mini"
        assert config.llm.api_key.get_secret_value() == "test-llm-key"
        assert config.llm.timeout == 10
        assert config.llm.max_text_length == 500

    def test_filter_mode_default(self, mock_config_file, monkeypatch):
        monkeypatch.delenv("VK_SERVICE_TOKEN", raising=False)
        monkeypatch.delenv("VK_LLM_API_KEY", raising=False)
        config = load_config(mock_config_file, _env_file=None)

        assert config.search.filter_mode == "stop_words"

    def test_filter_mode_invalid_raises(self, mock_config_file, mock_config_data, monkeypatch):
        mock_config_data["search"]["filter_mode"] = "invalid"
        import yaml

        with open(mock_config_file, "w", encoding="utf-8") as f:
            yaml.dump(mock_config_data, f, allow_unicode=True)

        monkeypatch.delenv("VK_SERVICE_TOKEN", raising=False)
        monkeypatch.delenv("VK_LLM_API_KEY", raising=False)
        try:
            load_config(mock_config_file, _env_file=None)
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "filter_mode" in str(e)

    def test_filter_mode_llm_without_model_raises(self, mock_config_file, mock_config_data, monkeypatch):
        mock_config_data["search"]["filter_mode"] = "llm"
        mock_config_data["llm"]["model"] = ""
        import yaml

        with open(mock_config_file, "w", encoding="utf-8") as f:
            yaml.dump(mock_config_data, f, allow_unicode=True)

        monkeypatch.delenv("VK_SERVICE_TOKEN", raising=False)
        monkeypatch.delenv("VK_LLM_API_KEY", raising=False)
        try:
            load_config(mock_config_file, _env_file=None)
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "llm.model" in str(e)

    def test_env_var_overrides_yaml(self, mock_config_file, monkeypatch):
        """VK_SERVICE_TOKEN env var перекрывает api.service_token из YAML."""
        monkeypatch.setenv("VK_SERVICE_TOKEN", "env_token")
        monkeypatch.delenv("VK_LLM_API_KEY", raising=False)
        config = load_config(mock_config_file, _env_file=None)

        assert config.api.service_token.get_secret_value() == "env_token"

    def test_llm_env_var_overrides_yaml(self, mock_config_file, monkeypatch):
        """VK_LLM_API_KEY env var перекрывает llm.api_key из YAML."""
        monkeypatch.delenv("VK_SERVICE_TOKEN", raising=False)
        monkeypatch.setenv("VK_LLM_API_KEY", "env_llm_key")
        config = load_config(mock_config_file, _env_file=None)

        assert config.llm.api_key.get_secret_value() == "env_llm_key"
