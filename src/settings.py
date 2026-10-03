"""Плоская конфигурация через pydantic-settings: env vars + .env + дефолты.

Все поля на одном уровне (без вложенных моделей). Секреты (service_token,
llm_api_key) — SecretStr, маскируются в repr() и логах.

Приоритет источников: env vars > .env > дефолты класса.
env_prefix="VK_" → VK_SERVICE_TOKEN, VK_LLM_API_KEY, VK_QUERIES и т.д.
Списки (queries, hashtags, groups, accounts, stop_words) парсятся из
comma-separated строк в env vars: VK_QUERIES='vk новости,россия,python'.

Валидация (min<=max, days_back>0, user_id>0 при auto_friends/auto_groups,
filter_mode и llm_model) — через @model_validator после создания.
ValidationError обёртывается в ValueError в get_settings() — main.py
ловит ValueError и выводит в stderr.
"""

from typing import Annotated

from pydantic import SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic_settings.sources import NoDecode


def _parse_comma_separated(v: str | list[str]) -> list[str]:
    """Парсит comma-separated строку в список; список пропускает как есть."""
    if isinstance(v, str):
        return [item.strip() for item in v.split(",") if item.strip()]
    return v


class Settings(BaseSettings):
    """Плоская конфигурация: все поля на одном уровне, env vars + .env + дефолты.

    VK API: service_token, api_version, base_url.
    Браузер: profile_path, headless.
    Поиск: queries, hashtags, groups, accounts, auto_friends, auto_groups, лимиты сбора.
    LLM: llm_model, llm_api_base, llm_api_key, llm_system_prompt, llm_timeout, llm_max_text_length.
    Лимиты/задержки: likes_per_session_min/max, sessions_per_day, delays, max_captcha_streak.
    Логирование: log_level, log_file.
    SQLite: db_path.
    """

    model_config = SettingsConfigDict(
        env_prefix="VK_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # VK API
    service_token: SecretStr = SecretStr("")
    api_version: str = "5.131"
    base_url: str = "https://api.vk.ru/method"

    # Браузер
    profile_path: str = "./chrome_profile"
    headless: bool = True

    # Поиск и сбор постов
    queries: Annotated[list[str], NoDecode] = []
    user_id: int = 0
    hashtags: Annotated[list[str], NoDecode] = []
    groups: Annotated[list[str], NoDecode] = []
    accounts: Annotated[list[str], NoDecode] = []
    auto_friends: bool = False
    auto_groups: bool = False
    max_posts_per_query: int = 100
    max_posts_per_hashtag: int = 100
    max_posts_per_group: int = 100
    max_posts_per_account: int = 100
    max_posts_per_friend: int = 10
    max_friends_to_collect: int = 200
    max_groups_to_collect: int = 200
    days_back: int = 30
    stop_words: Annotated[list[str], NoDecode] = []
    stop_words_file: str = "stop_words.txt"
    filter_mode: str = "stop_words"

    # LLM-фильтр (litellm, работает только при filter_mode=="llm")
    llm_model: str = ""
    llm_api_base: str = ""
    llm_api_key: SecretStr = SecretStr("")
    llm_system_prompt: str = ""
    llm_timeout: int = 10
    llm_max_text_length: int = 500

    # Лимиты и задержки (все рандомизируются через random.uniform)
    likes_per_session_min: int = 20
    likes_per_session_max: int = 30
    sessions_per_day: int = 3
    min_delay_sec: int = 15
    max_delay_sec: int = 60
    view_delay_min_sec: int = 5
    view_delay_max_sec: int = 15
    max_captcha_streak: int = 3

    # Логирование
    log_level: str = "INFO"
    log_file: str = "vk_autoliker.log"

    # SQLite
    db_path: str = "vk_autoliker.db"

    @field_validator("queries", "hashtags", "groups", "accounts", "stop_words", mode="before")
    @classmethod
    def _parse_list_fields(cls, v):
        """Парсит comma-separated строки из env vars в списки."""
        return _parse_comma_separated(v)

    @field_validator("filter_mode")
    @classmethod
    def _validate_filter_mode(cls, v: str) -> str:
        """Проверяет, что filter_mode — stop_words или llm."""
        if v not in ("stop_words", "llm"):
            raise ValueError("filter_mode должен быть 'stop_words' или 'llm'")
        return v

    @model_validator(mode="after")
    def _validate(self) -> "Settings":
        """Валидация зависимостей между полями после создания.

        min<=max для всех пар задержек/лимитов, days_back>0,
        user_id>0 при auto_friends/auto_groups,
        llm_model при filter_mode=="llm".
        """
        if self.likes_per_session_min > self.likes_per_session_max:
            raise ValueError("likes_per_session_min > likes_per_session_max")
        if self.min_delay_sec > self.max_delay_sec:
            raise ValueError("min_delay_sec > max_delay_sec")
        if self.view_delay_min_sec > self.view_delay_max_sec:
            raise ValueError("view_delay_min_sec > view_delay_max_sec")
        if self.days_back <= 0:
            raise ValueError("days_back должен быть > 0")
        if self.auto_friends and self.user_id <= 0:
            raise ValueError("user_id должен быть > 0 при auto_friends=True")
        if self.auto_groups and self.user_id <= 0:
            raise ValueError("user_id должен быть > 0 при auto_groups=True")
        if self.filter_mode == "llm" and not self.llm_model:
            raise ValueError("llm_model должен быть задан при filter_mode='llm'")
        return self


def get_settings() -> Settings:
    """Создаёт Settings() с обработкой ошибок валидации.

    ValidationError обёртывается в ValueError — main.py ловит ValueError
    и выводит сообщение в stderr с sys.exit(1).
    """
    from pydantic import ValidationError

    try:
        return Settings()
    except ValidationError as e:
        raise ValueError(str(e)) from e
