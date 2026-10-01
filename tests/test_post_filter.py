"""Unit-тесты фильтра постов PostFilter.

PostFilter проверяет только давность и наличие текста — без StateStore.
"""

import time
from typing import List

from post import Post, build_post_url
from post_filter import PostFilter


def make_post(owner_id: int, item_id: int, text: str = "text", days_ago: int = 0) -> Post:
    """Создаёт тестовый Post с указанными параметрами."""
    return Post(
        owner_id=owner_id,
        item_id=item_id,
        text=text,
        date=int(time.time()) - (days_ago * 86400),
        url=build_post_url(owner_id, item_id),
    )


class TestPostFilter:
    def test_filters_old_posts(self, mock_config, mock_logger):
        """Посты старше days_back отсеиваются."""
        pf = PostFilter(mock_config, mock_logger)

        posts: List[Post] = [
            make_post(1, 1, "fresh", days_ago=1),
            make_post(2, 2, "old", days_ago=30),
        ]
        result = pf.filter(posts)
        assert len(result) == 1
        assert result[0].owner_id == 1

    def test_filters_empty_text(self, mock_config, mock_logger):
        """Посты с пустым текстом отсеиваются."""
        pf = PostFilter(mock_config, mock_logger)

        posts: List[Post] = [
            make_post(1, 1, "real text"),
            make_post(2, 2, "   "),
            make_post(3, 3, ""),
        ]
        result = pf.filter(posts)
        assert len(result) == 1
        assert result[0].owner_id == 1

    def test_all_pass(self, mock_config, mock_logger):
        """Все свежие посты с текстом проходят фильтр."""
        pf = PostFilter(mock_config, mock_logger)

        posts: List[Post] = [
            make_post(1, 1, "post one"),
            make_post(2, 2, "post two"),
            make_post(3, 3, "post three"),
        ]
        result = pf.filter(posts)
        assert len(result) == 3

    def test_filters_stop_words(self, mock_config, mock_logger):
        """Посты со стоп-словами отсеиваются (регистронезависимо)."""
        pf = PostFilter(mock_config, mock_logger)

        posts: List[Post] = [
            make_post(1, 1, "обычный пост"),
            make_post(2, 2, "Это ПОЛИТИКА и выборы"),
            make_post(3, 3, "нейтральный контент"),
        ]
        result = pf.filter(posts)
        assert len(result) == 2
        assert result[0].owner_id == 1
        assert result[1].owner_id == 3

    def test_empty_stop_words_allows_all(self, mock_config, mock_logger):
        """Пустой список стоп-слов не отсеивает ничего."""
        mock_config.search.stop_words = []
        pf = PostFilter(mock_config, mock_logger)

        posts: List[Post] = [
            make_post(1, 1, "любой текст"),
            make_post(2, 2, "политика"),
        ]
        result = pf.filter(posts)
        assert len(result) == 2
