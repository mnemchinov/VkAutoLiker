"""Конфигурация приложения: dataclass-модели и загрузка из YAML."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import yaml


@dataclass
class ApiConfig:
    """Параметры доступа к VK API через service-токен.

    Service-токен работает для всех методов поиска (newsfeed.search, wall.get,
    friends.get, groups.get, utils.resolveScreenName), но не подходит для likes.add.
    Получается в кабинете разработчика: https://dev.vk.ru/ru/admin/create-app
    """

    service_token: str = ""
    api_version: str = "5.131"
    base_url: str = "https://api.vk.ru/method"


@dataclass
class BrowserConfig:
    """Параметры Selenium Chrome с персистентным профилем.

    profile_path — каталог пользовательского профиля Chrome; сохраняет сессию VK
    между запусками, чтобы логин (включая 2FA) выполнялся один раз вручную.
    headless — скрытый режим; нельзя использовать при первичном логине (нужен экран для 2FA).
    """

    profile_path: str = "./chrome_profile"
    headless: bool = False


@dataclass
class SearchConfig:
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

    queries: List[str]
    user_id: int = 0
    hashtags: List[str] = field(default_factory=list)
    groups: List[str] = field(default_factory=list)
    accounts: List[str] = field(default_factory=list)
    auto_friends: bool = False
    auto_groups: bool = False
    max_posts_per_query: int = 100
    max_posts_per_hashtag: int = 100
    max_posts_per_group: int = 100
    max_posts_per_account: int = 100
    max_posts_per_friend: int = 10
    max_friends_to_collect: int = 50
    max_groups_to_collect: int = 50
    days_back: int = 30


@dataclass
class LimitsConfig:
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


@dataclass
class LoggingConfig:
    """Настройки логирования в консоль и файл."""

    level: str = "INFO"
    file: str = "vk_autoliker.log"


@dataclass
class StateConfig:
    """Путь к SQLite-базе для хранения истории обработанных постов и сессий."""

    db_path: str = "vk_autoliker.db"


@dataclass
class AppConfig:
    """Корневая конфигурация приложения."""

    api: ApiConfig
    browser: BrowserConfig
    search: SearchConfig
    limits: LimitsConfig
    logging: LoggingConfig
    state: StateConfig


class ConfigLoader:
    """Загружает конфигурацию из YAML-файла и кэширует результат."""

    def __init__(self, config_path: str = "config.yaml"):
        """Инициализирует загрузчик с путём к YAML-файлу."""
        self._config_path = Path(config_path)
        self._config: Optional[AppConfig] = None

    def load(self) -> AppConfig:
        """Загружает конфигурацию из YAML, кэширует и возвращает AppConfig."""
        if not self._config_path.exists():
            raise FileNotFoundError(f"Файл конфигурации не найден: {self._config_path}")

        with open(self._config_path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)

        if raw is None:
            raise ValueError("Файл конфигурации пуст")

        api_raw = raw.get("api", {})
        browser_raw = raw.get("browser", {})
        search_raw = raw.get("search", {})
        limits_raw = raw.get("limits", {})
        logging_raw = raw.get("logging", {})
        state_raw = raw.get("state", {})

        self._config = AppConfig(
            api=ApiConfig(
                service_token=api_raw.get("service_token", ""),
                api_version=api_raw.get("api_version", "5.131"),
                base_url=api_raw.get("base_url", "https://api.vk.ru/method"),
            ),
            browser=BrowserConfig(
                profile_path=browser_raw.get("profile_path", "./chrome_profile"),
                headless=browser_raw.get("headless", False),
            ),
            search=SearchConfig(
                queries=search_raw.get("queries", []),
                user_id=search_raw.get("user_id", 0),
                hashtags=search_raw.get("hashtags", []),
                groups=search_raw.get("groups", []),
                accounts=search_raw.get("accounts", []),
                auto_friends=search_raw.get("auto_friends", False),
                auto_groups=search_raw.get("auto_groups", False),
                max_posts_per_query=search_raw.get("max_posts_per_query", 100),
                max_posts_per_hashtag=search_raw.get("max_posts_per_hashtag", 100),
                max_posts_per_group=search_raw.get("max_posts_per_group", 100),
                max_posts_per_account=search_raw.get("max_posts_per_account", 100),
                max_posts_per_friend=search_raw.get("max_posts_per_friend", 10),
                max_friends_to_collect=search_raw.get("max_friends_to_collect", 50),
                max_groups_to_collect=search_raw.get("max_groups_to_collect", 50),
                days_back=search_raw.get("days_back", 30),
            ),
            limits=LimitsConfig(
                likes_per_session_min=limits_raw.get("likes_per_session_min", 20),
                likes_per_session_max=limits_raw.get("likes_per_session_max", 30),
                sessions_per_day=limits_raw.get("sessions_per_day", 3),
                min_delay_sec=limits_raw.get("min_delay_sec", 15),
                max_delay_sec=limits_raw.get("max_delay_sec", 60),
                view_delay_min_sec=limits_raw.get("view_delay_min_sec", 3),
                view_delay_max_sec=limits_raw.get("view_delay_max_sec", 10),
                max_captcha_streak=limits_raw.get("max_captcha_streak", 3),
            ),
            logging=LoggingConfig(
                level=logging_raw.get("level", "INFO"),
                file=logging_raw.get("file", "vk_autoliker.log"),
            ),
            state=StateConfig(
                db_path=state_raw.get("db_path", "vk_autoliker.db"),
            ),
        )

        self._validate(self._config)
        return self._config

    @staticmethod
    def _validate(config: AppConfig) -> None:
        """Проверяет корректность конфигурации: min <= max, days_back > 0 и т.д.

        Raises:
            ValueError: если параметр некорректен.
        """
        limits = config.limits
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
        if config.search.days_back <= 0:
            raise ValueError(f"days_back должен быть > 0, получено {config.search.days_back}")
        if (config.search.auto_friends or config.search.auto_groups) and config.search.user_id <= 0:
            raise ValueError(
                "auto_friends/auto_groups включены, но user_id не задан (должен быть > 0)"
            )

    @property
    def config(self) -> AppConfig:
        """Возвращает кэшированную конфигурацию (загружает при первом обращении)."""
        if self._config is None:
            return self.load()
        return self._config
