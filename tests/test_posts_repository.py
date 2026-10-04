"""Unit-тесты репозитория постов PostsRepository.

Тестирует: is_processed, mark_processed (LIKED/FILTERED), reset.
Использует реальную SQLite-бД через Database + run_migrations.
"""

from database import Database
from migrations import run_migrations
from post import PostStatus
from repositories import PostsRepository


class TestPostsRepository:
    def test_mark_and_check_processed(self, mock_config, tmp_path):
        """Пост маркирован LIKED → is_processed True."""
        mock_config.db_path = str(tmp_path / "test.db")
        db = Database(mock_config)
        run_migrations(db.conn)
        repo = PostsRepository(db)

        assert not repo.is_processed(1, 100)
        repo.mark_processed(1, 100, PostStatus.LIKED)
        assert repo.is_processed(1, 100)
        assert not repo.is_processed(1, 101)
        db.close()

    def test_mark_filtered_blocks_in_is_processed(self, mock_config, tmp_path):
        """Пост маркирован FILTERED → is_processed True (не повторится)."""
        mock_config.db_path = str(tmp_path / "test.db")
        db = Database(mock_config)
        run_migrations(db.conn)
        repo = PostsRepository(db)

        repo.mark_processed(1, 100, PostStatus.FILTERED)
        assert repo.is_processed(1, 100)
        db.close()

    def test_mark_processed_default_is_liked(self, mock_config, tmp_path):
        """mark_processed без status → LIKED (для цикла лайков)."""
        mock_config.db_path = str(tmp_path / "test.db")
        db = Database(mock_config)
        run_migrations(db.conn)
        repo = PostsRepository(db)

        repo.mark_processed(1, 100)
        assert repo.is_processed(1, 100)
        row = db.conn.execute(
            "SELECT status FROM processed_posts WHERE owner_id=1 AND item_id=100"
        ).fetchone()
        assert row[0] == int(PostStatus.LIKED)
        db.close()

    def test_mark_processed_overwrites_filtered_to_liked(self, mock_config, tmp_path):
        """INSERT OR REPLACE: FILTERED → LIKED (пост перетестирован и прошёл)."""
        mock_config.db_path = str(tmp_path / "test.db")
        db = Database(mock_config)
        run_migrations(db.conn)
        repo = PostsRepository(db)

        repo.mark_processed(1, 100, PostStatus.FILTERED)
        repo.mark_processed(1, 100, PostStatus.LIKED)
        row = db.conn.execute(
            "SELECT status FROM processed_posts WHERE owner_id=1 AND item_id=100"
        ).fetchone()
        assert row[0] == int(PostStatus.LIKED)
        db.close()

    def test_reset_clears_all(self, mock_config, tmp_path):
        """reset очищает таблицу processed_posts."""
        mock_config.db_path = str(tmp_path / "test.db")
        db = Database(mock_config)
        run_migrations(db.conn)
        repo = PostsRepository(db)

        repo.mark_processed(1, 1)
        repo.mark_processed(2, 2, PostStatus.FILTERED)
        repo.reset()
        assert not repo.is_processed(1, 1)
        assert not repo.is_processed(2, 2)
        db.close()
