from unittest.mock import MagicMock

from post import Post
from api_search import ApiSearchService


class TestApiSearchService:
    def test_search_returns_posts(self, mock_config, mock_logger):
        client = MagicMock()
        client.call.return_value = {
            "items": [
                {"owner_id": -123, "id": 456, "text": "Test post", "date": 1700000000},
                {"owner_id": -789, "id": 101, "text": "Another post", "date": 1700001000},
            ]
        }

        svc = ApiSearchService(client, mock_logger)
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

        svc = ApiSearchService(client, mock_logger)
        posts = svc.search_hashtag("#test", max_posts=5)

        assert len(posts) == 1
        assert posts[0].owner_id == -1

    def test_search_no_results(self, mock_config, mock_logger):
        client = MagicMock()
        client.call.return_value = {"items": []}

        svc = ApiSearchService(client, mock_logger)
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

        svc = ApiSearchService(client, mock_logger)
        posts = svc.get_wall_posts(-123, max_posts=10)

        assert len(posts) == 2
        assert posts[0].owner_id == -123
        assert posts[0].item_id == 1

    def test_get_friends(self, mock_config, mock_logger):
        client = MagicMock()
        client.call.return_value = {"items": [111, 222, 333]}

        svc = ApiSearchService(client, mock_logger)
        friends = svc.get_friends(12345, max_count=200)

        assert friends == [111, 222, 333]
        client.call.assert_called_with("friends.get", {"user_id": 12345, "count": 1000})

    def test_get_groups(self, mock_config, mock_logger):
        client = MagicMock()
        client.call.return_value = {
            "items": [
                {"id": 100, "name": "Group 1"},
                {"id": 200, "name": "Group 2"},
            ]
        }

        svc = ApiSearchService(client, mock_logger)
        groups = svc.get_groups(12345, max_count=200)

        assert groups == [-100, -200]

    def test_resolve_screen_name_group(self, mock_config, mock_logger):
        client = MagicMock()
        client.call.return_value = {"type": "group", "object_id": 123456}

        svc = ApiSearchService(client, mock_logger)
        owner_id = svc.resolve_screen_name("magnitretail")

        assert owner_id == -123456

    def test_resolve_screen_name_user(self, mock_config, mock_logger):
        client = MagicMock()
        client.call.return_value = {"type": "user", "object_id": 789}

        svc = ApiSearchService(client, mock_logger)
        owner_id = svc.resolve_screen_name("id789")

        assert owner_id == 789

    def test_resolve_screen_name_unknown(self, mock_config, mock_logger):
        client = MagicMock()
        client.call.return_value = {}

        svc = ApiSearchService(client, mock_logger)
        owner_id = svc.resolve_screen_name("nonexistent")

        assert owner_id is None

    def test_parse_newsfeed_item_missing_fields(self, mock_config, mock_logger):
        result = ApiSearchService._parse_newsfeed_item({"text": "no ids"})
        assert result is None

    def test_date_from_api_in_post(self, mock_config, mock_logger):
        client = MagicMock()
        client.call.return_value = {
            "items": [
                {"owner_id": -1, "id": 1, "text": "dated post", "date": 1699999999},
            ]
        }

        svc = ApiSearchService(client, mock_logger)
        posts = svc.search("test", max_posts=1)

        assert posts[0].date == 1699999999
