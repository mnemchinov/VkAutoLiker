import time
from typing import List

from post import Post, build_post_url
from post_filter import PostFilter
from state_store import StateStore


def make_post(owner_id: int, item_id: int, text: str = "text", days_ago: int = 0) -> Post:
    return Post(
        owner_id=owner_id,
        item_id=item_id,
        text=text,
        date=int(time.time()) - (days_ago * 86400),
        url=build_post_url(owner_id, item_id),
    )


class TestPostFilter:
    def test_filters_old_posts(self, mock_config, mock_logger, tmp_path):
        config = mock_config
        config.state.db_path = str(tmp_path / "test.db")
        state = StateStore(config, mock_logger)
        pf = PostFilter(config, state, mock_logger)

        posts: List[Post] = [
            make_post(1, 1, "fresh", days_ago=1),
            make_post(2, 2, "old", days_ago=30),
        ]
        result = pf.filter(posts)
        assert len(result) == 1
        assert result[0].owner_id == 1
        state.close()

    def test_filters_empty_text(self, mock_config, mock_logger, tmp_path):
        config = mock_config
        config.state.db_path = str(tmp_path / "test.db")
        state = StateStore(config, mock_logger)
        pf = PostFilter(config, state, mock_logger)

        posts: List[Post] = [
            make_post(1, 1, "real text"),
            make_post(2, 2, "   "),
            make_post(3, 3, ""),
        ]
        result = pf.filter(posts)
        assert len(result) == 1
        assert result[0].owner_id == 1
        state.close()

    def test_filters_duplicates(self, mock_config, mock_logger, tmp_path):
        config = mock_config
        config.state.db_path = str(tmp_path / "test.db")
        state = StateStore(config, mock_logger)
        state.mark_processed(1, 1)
        pf = PostFilter(config, state, mock_logger)

        posts: List[Post] = [
            make_post(1, 1, "already processed"),
            make_post(2, 2, "new post"),
        ]
        result = pf.filter(posts)
        assert len(result) == 1
        assert result[0].owner_id == 2
        state.close()

    def test_all_pass(self, mock_config, mock_logger, tmp_path):
        config = mock_config
        config.state.db_path = str(tmp_path / "test.db")
        state = StateStore(config, mock_logger)
        pf = PostFilter(config, state, mock_logger)

        posts: List[Post] = [
            make_post(1, 1, "post one"),
            make_post(2, 2, "post two"),
            make_post(3, 3, "post three"),
        ]
        result = pf.filter(posts)
        assert len(result) == 3
        state.close()
