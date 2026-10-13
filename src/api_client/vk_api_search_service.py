"""Сервис поиска постов через VK API (newsfeed.search, wall.get, friends.get, groups.get)."""

from logger import AppLogger
from post import Post, build_post_url

from .vk_api_client import VKApiClient, VKApiError


class VkApiSearchService:
    """Поиск и сбор постов через VK API с service-токеном.

    Методы возвращают List[Post] с реальными датами из API (unix timestamp),
    что позволяет DateFilter корректно фильтровать по days_back.
    """

    def __init__(self, client: VKApiClient, logger: AppLogger):
        """Инициализирует сервис поиска с VK API клиентом."""
        self._client = client
        self._logger = logger

    def search(self, query: str, max_posts: int = 50) -> list[Post]:
        """Поиск постов по текстовому запросу через newsfeed.search."""
        self._logger.info(f"API-поиск: {query}")
        posts = self._newsfeed_search(query, max_posts)
        self._logger.info(f"Найдено {len(posts)} постов по запросу '{query}'")
        return posts

    def search_hashtag(self, hashtag: str, max_posts: int = 50) -> list[Post]:
        """Поиск постов по хештегу через newsfeed.search."""
        self._logger.info(f"API-поиск по хештегу: {hashtag}")
        posts = self._newsfeed_search(hashtag, max_posts)
        self._logger.info(f"Найдено {len(posts)} постов по хештегу '{hashtag}'")
        return posts

    def get_wall_posts(self, owner_id: int, max_posts: int = 100) -> list[Post]:
        """Получение постов со стены пользователя или группы (wall.get).

        owner_id положительный для пользователей, отрицательный для групп.
        """
        self._logger.info(f"API wall.get: owner_id={owner_id}")
        posts: list[Post] = []
        offset = 0
        count = 100

        while len(posts) < max_posts:
            batch = min(count, max_posts - len(posts))
            try:
                resp = self._client.call(
                    "wall.get",
                    {
                        "owner_id": owner_id,
                        "count": batch,
                        "offset": offset,
                        "filter": "owner",
                    },
                )
            except VKApiError as e:
                if e.code in (14, 15, 18, 30):
                    raise
                self._logger.warning(f"Ошибка wall.get owner_id={owner_id}: {e}")
                break
            items = resp.get("items", [])
            if not items:
                break

            for item in items:
                post = self._parse_wall_item(item)
                if post:
                    posts.append(post)

            offset += len(items)
            if len(items) < batch:
                break

        self._logger.info(f"Найдено {len(posts)} постов на стене owner_id={owner_id}")
        return posts[:max_posts]

    def get_friends(self, user_id: int) -> list[int]:
        """Возвращает полный список ID друзей пользователя (friends.get).

        Всегда запрашивает count=1000 (один API-вызов), возвращает всех друзей.
        Перемешивание и ограничение числа API-вызовов — на стороне CollectStage.
        """
        self._logger.info(f"API friends.get: user_id={user_id}")
        resp = self._client.call(
            "friends.get",
            {
                "user_id": user_id,
                "count": 1000,
            },
        )
        items = resp.get("items", [])
        friend_ids = [f for f in items if isinstance(f, int)]
        self._logger.info(f"Найдено {len(friend_ids)} друзей")
        return friend_ids

    def get_groups(self, user_id: int) -> list[int]:
        """Возвращает полный список ID групп пользователя (groups.get).

        Всегда запрашивает count=1000 (один API-вызов), возвращает все группы.
        ID возвращаются отрицательными (формат owner_id для wall.get).
        Перемешивание и ограничение числа API-вызовов — на стороне CollectStage.
        """
        self._logger.info(f"API groups.get: user_id={user_id}")
        resp = self._client.call(
            "groups.get",
            {
                "user_id": user_id,
                "count": 1000,
                "extended": 0,
            },
        )
        items = resp.get("items", [])
        group_ids = [-gid for gid in items if isinstance(gid, int)]
        self._logger.info(f"Найдено {len(group_ids)} групп")
        return group_ids

    def resolve_screen_name(self, screen_name: str) -> int | None:
        """Преобразует короткое имя (screen_name) в owner_id.

        Возвращает положительный ID для пользователя, отрицательный для группы.
        None, если имя не найдено.
        """
        resp = self._client.call(
            "utils.resolveScreenName",
            {
                "screen_name": screen_name,
            },
        )
        obj_type = resp.get("type")
        obj_id = resp.get("object_id")
        if not obj_id:
            return None
        if obj_type == "user":
            return obj_id
        elif obj_type in ("group", "page"):
            return -obj_id
        return None

    def _newsfeed_search(self, query: str, max_posts: int) -> list[Post]:
        """Пагинация по newsfeed.search через start_time (сдвиг по дате последнего поста)."""
        posts: list[Post] = []
        count = 200
        start_time = 0

        while len(posts) < max_posts:
            batch = min(count, max_posts - len(posts))
            params = {
                "q": query,
                "count": batch,
            }
            if start_time:
                params["start_time"] = start_time

            resp = self._client.call("newsfeed.search", params)
            items = resp.get("items", [])
            if not items:
                break

            for item in items:
                post = self._parse_newsfeed_item(item)
                if post:
                    posts.append(post)

            if len(items) < batch:
                break
            last_date = items[-1].get("date", 0)
            if last_date:
                start_time = last_date + 1
            else:
                break

        return posts[:max_posts]

    @staticmethod
    def _parse_newsfeed_item(item: dict) -> Post | None:
        """Парсит элемент из newsfeed.search в Post. None, если нет owner_id/item_id."""
        owner_id = item.get("owner_id") or item.get("source_id", 0)
        item_id = item.get("id") or item.get("post_id", 0)
        if not owner_id or not item_id:
            return None
        return Post(
            owner_id=owner_id,
            item_id=item_id,
            text=item.get("text", ""),
            date=item.get("date", 0),
            url=build_post_url(owner_id, item_id),
            from_id=item.get("from_id", 0),
        )

    @staticmethod
    def _parse_wall_item(item: dict) -> Post | None:
        """Парсит элемент из wall.get в Post."""
        owner_id = item.get("owner_id", 0)
        item_id = item.get("id", 0)
        if not owner_id or not item_id:
            return None
        return Post(
            owner_id=owner_id,
            item_id=item_id,
            text=item.get("text", ""),
            date=item.get("date", 0),
            url=build_post_url(owner_id, item_id),
            from_id=item.get("from_id", 0),
        )
