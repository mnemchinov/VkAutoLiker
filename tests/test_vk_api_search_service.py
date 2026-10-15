from unittest.mock import MagicMock

import pytest

from api_client import CaptchaError, VKApiError, VkApiSearchService
from post import Post


class TestVkApiSearchService:
    def test_search_returns_posts(self, mock_config, mock_logger):
        client = MagicMock()
        client.call.return_value = {
            "items": [
                {"owner_id": -123, "id": 456, "text": "Test post", "date": 1700000000},
                {"owner_id": -789, "id": 101, "text": "Another post", "date": 1700001000},
            ]
        }

        svc = VkApiSearchService(client, mock_logger)
        posts = svc.search("test", max_posts=10)

        assert len(posts) == 2
        assert isinstance(posts[0], Post)
        assert posts[0].owner_id == -123
        assert posts[0].item_id == 456
        assert posts[0].date == 1700000000
        assert posts[0].url == "https://vk.ru/wall-123_456"

    def test_search_hashtag(self, mock_config, mock_logger):
        client = MagicMock()
        client.call.return_value = {
            "items": [
                {"owner_id": -1, "id": 1, "text": "hashtag post", "date": 1700000000},
            ]
        }

        svc = VkApiSearchService(client, mock_logger)
        posts = svc.search_hashtag("#test", max_posts=5)

        assert len(posts) == 1
        assert posts[0].owner_id == -1

    def test_search_no_results(self, mock_config, mock_logger):
        client = MagicMock()
        client.call.return_value = {"items": []}

        svc = VkApiSearchService(client, mock_logger)
        posts = svc.search("nothing", max_posts=10)

        assert len(posts) == 0

    def test_get_wall_posts(self, mock_config, mock_logger):
        client = MagicMock()
        client.call.return_value = {
            "items": [
                {"owner_id": -123, "id": 1, "text": "wall post 1", "date": 1700000000},
                {"owner_id": -123, "id": 2, "text": "wall post 2", "date": 1700001000},
            ]
        }

        svc = VkApiSearchService(client, mock_logger)
        posts = svc.get_wall_posts(-123, max_posts=10)

        assert len(posts) == 2
        assert posts[0].owner_id == -123
        assert posts[0].item_id == 1

    def test_get_friends_returns_all(self, mock_config, mock_logger):
        """get_friends возвращает всех друзей без среза."""
        all_ids = list(range(1000, 1100))  # 100 друзей
        client = MagicMock()
        client.call.return_value = {"items": all_ids}

        svc = VkApiSearchService(client, mock_logger)
        friends = svc.get_friends(12345)

        assert friends == all_ids
        assert len(friends) == 100
        client.call.assert_called_with("friends.get", {"user_id": 12345, "count": 1000})

    def test_get_groups_returns_all(self, mock_config, mock_logger):
        """get_groups возвращает все группы без среза, ID отрицательные."""
        items = list(range(1, 51))  # extended=0 → список int
        client = MagicMock()
        client.call.return_value = {"items": items}

        svc = VkApiSearchService(client, mock_logger)
        groups = svc.get_groups(12345)

        assert len(groups) == 50
        assert groups[0] == -1
        assert groups[-1] == -50

    def test_resolve_screen_name_group(self, mock_config, mock_logger):
        client = MagicMock()
        client.call.return_value = {"type": "group", "object_id": 123456}

        svc = VkApiSearchService(client, mock_logger)
        owner_id = svc.resolve_screen_name("magnitretail")

        assert owner_id == -123456

    def test_resolve_screen_name_user(self, mock_config, mock_logger):
        client = MagicMock()
        client.call.return_value = {"type": "user", "object_id": 789}

        svc = VkApiSearchService(client, mock_logger)
        owner_id = svc.resolve_screen_name("id789")

        assert owner_id == 789

    def test_resolve_screen_name_unknown(self, mock_config, mock_logger):
        client = MagicMock()
        client.call.return_value = {}

        svc = VkApiSearchService(client, mock_logger)
        owner_id = svc.resolve_screen_name("nonexistent")

        assert owner_id is None

    def test_parse_newsfeed_item_missing_fields(self, mock_config, mock_logger):
        result = VkApiSearchService._parse_newsfeed_item({"text": "no ids"})
        assert result is None

    def test_date_from_api_in_post(self, mock_config, mock_logger):
        client = MagicMock()
        client.call.return_value = {
            "items": [
                {"owner_id": -1, "id": 1, "text": "dated post", "date": 1699999999},
            ]
        }

        svc = VkApiSearchService(client, mock_logger)
        posts = svc.search("test", max_posts=1)

        assert posts[0].date == 1699999999

    def test_parse_wall_item_from_id(self, mock_config, mock_logger):
        """_parse_wall_item парсит from_id — автор поста."""
        client = MagicMock()
        client.call.return_value = {
            "items": [
                {
                    "owner_id": -123,
                    "id": 456,
                    "text": "wall post",
                    "date": 1700000000,
                    "from_id": 999,
                },
            ]
        }

        svc = VkApiSearchService(client, mock_logger)
        posts = svc.get_wall_posts(-123, max_posts=1)

        assert posts[0].from_id == 999

    def test_parse_newsfeed_item_from_id(self, mock_config, mock_logger):
        """_parse_newsfeed_item парсит from_id — автор поста."""
        client = MagicMock()
        client.call.return_value = {
            "items": [
                {
                    "owner_id": -1,
                    "id": 1,
                    "text": "search post",
                    "date": 1700000000,
                    "from_id": 888,
                },
            ]
        }

        svc = VkApiSearchService(client, mock_logger)
        posts = svc.search("test", max_posts=1)

        assert posts[0].from_id == 888

    def test_get_wall_posts_reraises_captcha(self, mock_config, mock_logger):
        """CaptchaError (код 14) от wall.get — пробрасывается, не глотается."""
        client = MagicMock()
        client.call.side_effect = CaptchaError("captcha required")

        svc = VkApiSearchService(client, mock_logger)
        with pytest.raises(CaptchaError):
            svc.get_wall_posts(-123, max_posts=10)

    def test_get_wall_posts_reraises_access_denied(self, mock_config, mock_logger):
        """VKApiError с кодом 15 (access denied) — пробрасывается."""
        client = MagicMock()
        client.call.side_effect = VKApiError(15, "access denied")

        svc = VkApiSearchService(client, mock_logger)
        with pytest.raises(VKApiError):
            svc.get_wall_posts(-123, max_posts=10)

    def test_get_wall_posts_breaks_on_other_error(self, mock_config, mock_logger):
        """VKApiError с прочими кодами — логируется, возвращается пустой список."""
        client = MagicMock()
        client.call.side_effect = VKApiError(1, "unknown error")

        svc = VkApiSearchService(client, mock_logger)
        posts = svc.get_wall_posts(-123, max_posts=10)

        assert posts == []

    def test_extract_attachment_text_video(self, mock_config, mock_logger):
        """video даёт title и description — клип становится известным."""
        attachments = [
            {"type": "video", "video": {"title": "Clip by @viacheslavh", "description": "#орда"}},
        ]
        result = VkApiSearchService._extract_attachment_text(attachments)
        assert result == "Clip by @viacheslavh #орда"

    def test_extract_attachment_text_audio(self, mock_config, mock_logger):
        attachments = [
            {"type": "audio", "audio": {"artist": "Vox Luminis", "title": "Remember Not"}},
        ]
        result = VkApiSearchService._extract_attachment_text(attachments)
        assert result == "Vox Luminis Remember Not"

    def test_extract_attachment_text_photo_caption(self, mock_config, mock_logger):
        """Фото с caption даёт caption; без caption — пусто (неизвестно)."""
        with_caption = [{"type": "photo", "photo": {"text": "фото с подписью"}}]
        assert VkApiSearchService._extract_attachment_text(with_caption) == "фото с подписью"
        without_caption = [{"type": "photo", "photo": {"text": ""}}]
        assert VkApiSearchService._extract_attachment_text(without_caption) == ""

    def test_extract_attachment_text_poll_link_doc(self, mock_config, mock_logger):
        attachments = [
            {"type": "poll", "poll": {"question": "Кто на выпускном?"}},
            {"type": "link", "link": {"title": "Сайт события"}},
            {"type": "doc", "doc": {"filename": "билеты.pdf"}},
        ]
        result = VkApiSearchService._extract_attachment_text(attachments)
        assert result == "Кто на выпускном?\nСайт события\nбилеты.pdf"

    def test_extract_attachment_text_unknown_type(self, mock_config, mock_logger):
        """Неизвестный тип вложения ничего не даёт."""
        attachments = [
            {"type": "sticker", "sticker": {"product_id": 1}},
            {"type": "market", "market": {"id": 2}},
        ]
        assert VkApiSearchService._extract_attachment_text(attachments) == ""

    def test_extract_attachment_text_empty(self, mock_config, mock_logger):
        assert VkApiSearchService._extract_attachment_text([]) == ""

    def test_parse_wall_item_empty_text_video_attachment(self, mock_config, mock_logger):
        """Пустой текст + video — содержание извлекается, пост становится известным."""
        client = MagicMock()
        client.call.return_value = {
            "items": [
                {
                    "owner_id": -123,
                    "id": 6231,
                    "text": "",
                    "date": 1790845696,
                    "from_id": -123,
                    "attachments": [
                        {
                            "type": "video",
                            "video": {"title": "Clip by @x", "description": "#орда"},
                        },
                    ],
                },
            ]
        }

        svc = VkApiSearchService(client, mock_logger)
        posts = svc.get_wall_posts(-123, max_posts=1)

        assert posts[0].text == "Clip by @x #орда"

    def test_parse_wall_item_empty_text_photo_no_caption(self, mock_config, mock_logger):
        """Пустой текст + фото без caption — содержание неизвестно, текст остаётся пустым."""
        client = MagicMock()
        client.call.return_value = {
            "items": [
                {
                    "owner_id": -123,
                    "id": 6229,
                    "text": "",
                    "date": 1790702672,
                    "from_id": -123,
                    "attachments": [{"type": "photo", "photo": {"text": ""}}],
                },
            ]
        }

        svc = VkApiSearchService(client, mock_logger)
        posts = svc.get_wall_posts(-123, max_posts=1)

        assert posts[0].text == ""

    def test_parse_newsfeed_item_empty_text_video_attachment(self, mock_config, mock_logger):
        """Обогащение работает и для newsfeed.search (вложения там есть)."""
        client = MagicMock()
        client.call.return_value = {
            "items": [
                {
                    "owner_id": -1,
                    "id": 1,
                    "text": "",
                    "date": 1700000000,
                    "from_id": 888,
                    "attachments": [
                        {"type": "video", "video": {"title": "видео", "description": "описание"}},
                    ],
                },
            ]
        }

        svc = VkApiSearchService(client, mock_logger)
        posts = svc.search("test", max_posts=1)

        assert posts[0].text == "видео описание"

    def test_parse_wall_item_text_not_overwritten(self, mock_config, mock_logger):
        """Ненулевой текст поста не обогащается вложениями."""
        client = MagicMock()
        client.call.return_value = {
            "items": [
                {
                    "owner_id": -123,
                    "id": 1,
                    "text": "оригинальный текст",
                    "date": 1700000000,
                    "from_id": -123,
                    "attachments": [
                        {"type": "video", "video": {"title": "видео", "description": ""}},
                    ],
                },
            ]
        }

        svc = VkApiSearchService(client, mock_logger)
        posts = svc.get_wall_posts(-123, max_posts=1)

        assert posts[0].text == "оригинальный текст"
