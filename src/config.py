"""Конфигурация приложения: pydantic-модели и загрузка из YAML + env vars.

Секреты (service_token, llm.api_key) загружаются из переменных окружения
VK_SERVICE_TOKEN и VK_LLM_API_KEY; остальные параметры — из config.yaml.
Env vars имеют приоритет над YAML. SecretStr маскирует секреты в repr() и логах.
ConfigLoader удалён — вместо него тонкая функция load_config().
"""

from pathlib import Path

import yaml
from pydantic import BaseModel, Field, SecretStr, ValidationError, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ApiConfig(BaseModel):
    """Параметры доступа к VK API через service-токен.

    Service-токен работает для всех методов поиска (newsfeed.search, wall.get,
    friends.get, groups.get, utils.resolveScreenName), но не подходит для likes.add.
    Получается в кабинете разработчика: https://dev.vk.ru/ru/admin/create-app
    """

    service_token: SecretStr = SecretStr("")
    api_version: str = "5.131"
    base_url: str = "https://api.vk.ru/method"


class BrowserConfig(BaseModel):
    """Параметры Selenium Chrome с персистентным профилем.

    profile_path — каталог пользовательского профиля Chrome; сохраняет сессию VK
    между запусками, чтобы логин (включая 2FA) выполнялся один раз вручную.
    headless — скрытый режим; нельзя использовать при первичном логине (нужен экран для 2FA).
    """

    profile_path: str = "./chrome_profile"
    headless: bool = False


class SearchConfig(BaseModel):
    """Параметры сбора постов: источники, лимиты глубины и фильтр по давности.

    Источники постов (комбинируются):
      queries   — текстовые запросы через newsfeed.search;
      hashtags  — поиск по хештегам через newsfeed.search;
      groups    — короткие имена сообществ (resolve_screen_name → wall.get);
      accounts  — короткие имена пользователей (resolve_screen_name → wall.get);
      auto_friends — автоматический сбор постов со стен друзей (friends.get → wall.get);
      auto_groups  — автоматический сбор постов со стен подписок (groups.get → wall.get).

    user_id — VK ID пользователя, от имени которого собираются друзья/подписки.
    days_back — не лайкать посты старше N дней (фильтр по date из API).
    """

    queries: list[str]
    user_id: int = 0
    hashtags: list[str] = Field(default_factory=list)
    groups: list[str] = Field(default_factory=list)
    accounts: list[str] = Field(default_factory=list)
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
    stop_words: list[str] = Field(default_factory=list)
    stop_words_file: str = ""
    filter_mode: str = "stop_words"


class LLMConfig(BaseModel):
    """Параметры LLM-фильтра тематики постов через litellm.

    model — идентификатор модели в формате litellm (например "openai/gpt-4o-mini").
    api_base — базовый URL API провайдера (пустая строка = дефолт litellm).
    api_key — ключ API провайдера (SecretStr, загружается из VK_LLM_API_KEY).
    system_prompt — системный промпт для классификации (пустая строка = дефолтный).
    timeout — таймаут запроса к LLM в секундах.
    max_text_length — макс. длина текста поста, отправляемого в LLM.
    """

    model: str = ""
    api_base: str = ""
    api_key: SecretStr = SecretStr("")
    system_prompt: str = ""
    timeout: int = 10
    max_text_length: int = 500


class LimitsConfig(BaseModel):
    """Лимиты и задержки для снижения риска блокировки.

    Все задержки рандомизируются через random.uniform(min, max) — фиксированных
    значений нет нигде в коде.
    """

    likes_per_session_min: int = 20
    likes_per_session_max: int = 30
    sessions_per_day: int = 3
    min_delay_sec: int = 15
    max_delay_sec: int = 60
    view_delay_min_sec: int = 3
    view_delay_max_sec: int = 10
    max_captcha_streak: int = 3


class LoggingConfig(BaseModel):
    """Настройки логирования в консоль и файл."""

    level: str = "INFO"
    file: str = "vk_autoliker.log"


class StateConfig(BaseModel):
    """Путь к SQLite-базе для хранения истории обработанных постов и сессий."""

    db_path: str = "vk_autoliker.db"


class AppConfig(BaseSettings):
    """Корневая конфигурация приложения.

    Секреты загружаются из env vars (VK_SERVICE_TOKEN, VK_LLM_API_KEY)
    и имеют приоритет над значениями в config.yaml. SecretStr маскирует
    секреты в repr() и логах — получить строку можно через .get_secret_value().
    """

    api: ApiConfig
    browser: BrowserConfig
    search: SearchConfig
    limits: LimitsConfig
    logging: LoggingConfig
    state: StateConfig
    llm: LLMConfig = Field(default_factory=LLMConfig)

    # Секреты из env vars (приоритет над YAML-значениями в под-конфигах)
    service_token: SecretStr = SecretStr("")
    llm_api_key: SecretStr = SecretStr("")

    model_config = SettingsConfigDict(
        env_prefix="VK_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls,
        init_settings,
        env_settings,
        dotenv_settings,
        file_secret_settings,
    ):
        """Приоритет источников: env vars > .env > init (YAML)."""
        return (env_settings, dotenv_settings, init_settings)

    @model_validator(mode="after")
    def _inject_secrets_and_validate(self) -> "AppConfig":
        """Внедряет секреты из env vars в под-конфиги и валидирует параметры.

        Если VK_SERVICE_TOKEN задан — перекрывает api.service_token из YAML.
        Если VK_LLM_API_KEY задан — перекрывает llm.api_key из YAML.
        """
        if self.service_token.get_secret_value():
            self.api.service_token = self.service_token
        if self.llm_api_key.get_secret_value():
            self.llm.api_key = self.llm_api_key

        limits = self.limits
        if limits.likes_per_session_min > limits.likes_per_session_max:
            raise ValueError(
                f"likes_per_session_min ({limits.likes_per_session_min}) > "
                f"likes_per_session_max ({limits.likes_per_session_max})"
            )
        if limits.min_delay_sec > limits.max_delay_sec:
            raise ValueError(
                f"min_delay_sec ({limits.min_delay_sec}) > max_delay_sec ({limits.max_delay_sec})"
            )
        if limits.view_delay_min_sec > limits.view_delay_max_sec:
            raise ValueError(
                f"view_delay_min_sec ({limits.view_delay_min_sec}) > "
                f"view_delay_max_sec ({limits.view_delay_max_sec})"
            )
        if self.search.days_back <= 0:
            raise ValueError(f"days_back должен быть > 0, получено {self.search.days_back}")
        if (self.search.auto_friends or self.search.auto_groups) and self.search.user_id <= 0:
            raise ValueError(
                "auto_friends/auto_groups включены, но user_id не задан (должен быть > 0)"
            )
        if self.search.filter_mode not in ("stop_words", "llm"):
            raise ValueError(
                f"filter_mode должен быть 'stop_words' или 'llm', "
                f"получено '{self.search.filter_mode}'"
            )
        if self.search.filter_mode == "llm" and not self.llm.model:
            raise ValueError("filter_mode='llm', но llm.model не задан")

        return self


def load_config(config_path: str = "config.yaml", **kwargs) -> AppConfig:
    """Загружает конфигурацию из YAML-файла; секреты — из env vars.

    Args:
        config_path: путь к YAML-файлу конфигурации.
        **kwargs: дополнительные аргументы для AppConfig (например, _env_file=None).

    Raises:
        FileNotFoundError: если файл конфигурации не найден.
        ValueError: если файл пуст или конфигурация невалидна.
    """
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Файл конфигурации не найден: {path}")

    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    if raw is None:
        raise ValueError("Файл конфигурации пуст")

    try:
        return AppConfig(**raw, **kwargs)
    except ValidationError as e:
        raise ValueError(str(e)) from e
