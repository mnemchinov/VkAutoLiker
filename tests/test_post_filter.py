"""Unit-тесты декомпозированных фильтров постов: DateFilter, EmptyTextFilter, StopWordsFilter, FilterChain.

Каждый фильтр реализует should_skip(post) -> bool.
FilterChain объединяет фильтры и применяется в CollectStage._accept().
"""

import time

from post import Post, build_post_url
from post_filter import DateFilter, EmptyTextFilter, FilterChain, StopWordsFilter


def make_post(owner_id: int, item_id: int, text: str = "text", days_ago: int = 0) -> Post:
    """Создаёт тестовый Post с указанными параметрами."""
    return Post(
        owner_id=owner_id,
        item_id=item_id,
        text=text,
        date=int(time.time()) - (days_ago * 86400),
        url=build_post_url(owner_id, item_id),
    )


class TestDateFilter:
    def test_skips_old_posts(self, mock_config):
        """Посты старше days_back отсеиваются."""
        f = DateFilter(mock_config.days_back)
        assert f.should_skip(make_post(1, 1, "old", days_ago=30)) is True

    def test_keeps_fresh_posts(self, mock_config):
        """Свежие посты проходят."""
        f = DateFilter(mock_config.days_back)
        assert f.should_skip(make_post(1, 1, "fresh", days_ago=1)) is False


class TestEmptyTextFilter:
    def test_skips_empty_text(self):
        """Пустой текст отсеивается."""
        f = EmptyTextFilter()
        assert f.should_skip(make_post(1, 1, "")) is True

    def test_skips_whitespace_only(self):
        """Текст из пробелов отсеивается."""
        f = EmptyTextFilter()
        assert f.should_skip(make_post(1, 1, "   ")) is True

    def test_keeps_real_text(self):
        """Непустой текст проходит."""
        f = EmptyTextFilter()
        assert f.should_skip(make_post(1, 1, "real text")) is False


class TestStopWordsFilter:
    def test_filters_stop_words(self, mock_config, mock_logger):
        """Посты со стоп-словами отсеиваются (регистронезависимо)."""
        f = StopWordsFilter(mock_config, mock_logger)
        assert f.should_skip(make_post(1, 1, "Это ПОЛИТИКА и выборы")) is True

    def test_keeps_clean_posts(self, mock_config, mock_logger):
        """Посты без стоп-слов проходят."""
        f = StopWordsFilter(mock_config, mock_logger)
        assert f.should_skip(make_post(1, 1, "обычный пост")) is False

    def test_empty_stop_words_allows_all(self, mock_config, mock_logger):
        """Пустой список стоп-слов не отсеивает ничего."""
        mock_config.stop_words = []
        mock_config.stop_words_file = ""
        f = StopWordsFilter(mock_config, mock_logger)
        assert f.should_skip(make_post(1, 1, "политика")) is False

    def test_stop_words_file_loaded(self, mock_config, mock_logger, tmp_path):
        """Стоп-слова загружаются из файла и применяются."""
        sw_file = tmp_path / "stop.txt"
        sw_file.write_text("# Комментарий\n\nнаркотики\n\nказино\n", encoding="utf-8")

        mock_config.stop_words = []
        mock_config.stop_words_file = str(sw_file)
        f = StopWordsFilter(mock_config, mock_logger)

        assert f.should_skip(make_post(1, 1, "пост про НАРКОТИКИ")) is True
        assert f.should_skip(make_post(2, 2, "заходи в казино")) is True
        assert f.should_skip(make_post(3, 3, "обычный пост")) is False

    def test_stop_words_file_not_found(self, mock_config, mock_logger):
        """Отсутствующий файл стоп-слов — warning, работа продолжается."""
        mock_config.stop_words = ["спам"]
        mock_config.stop_words_file = "/nonexistent/stop_words.txt"
        f = StopWordsFilter(mock_config, mock_logger)

        assert f.should_skip(make_post(1, 1, "пост со словом спам")) is True
        assert f.should_skip(make_post(2, 2, "нормальный пост")) is False

    def test_stop_words_file_and_inline_merged(self, mock_config, mock_logger, tmp_path):
        """Стоп-слова из файла и inline-списка объединяются."""
        sw_file = tmp_path / "stop.txt"
        sw_file.write_text("казино\n", encoding="utf-8")

        mock_config.stop_words = ["политика"]
        mock_config.stop_words_file = str(sw_file)
        f = StopWordsFilter(mock_config, mock_logger)

        assert f.should_skip(make_post(1, 1, "пост про политика")) is True
        assert f.should_skip(make_post(2, 2, "заходи в казино")) is True
        assert f.should_skip(make_post(3, 3, "нормальный пост")) is False

    def test_stop_words_file_comments_ignored(self, mock_config, mock_logger, tmp_path):
        """Комментарии (#+) и пустые строки в файле игнорируются."""
        sw_file = tmp_path / "stop.txt"
        sw_file.write_text("# заголовок\n\nполитика\n  # ещё комментарий\n\n", encoding="utf-8")

        mock_config.stop_words = []
        mock_config.stop_words_file = str(sw_file)
        f = StopWordsFilter(mock_config, mock_logger)

        assert "политика" in f._stop_lemmas
        assert len(f._stop_lemmas) == 1

    def test_lemmatization_matches_word_forms(self, mock_config, mock_logger):
        """Лемматизация находит стоп-слово в любой форме («церковью» → «церковь»)."""
        mock_config.stop_words = ["церковь"]
        mock_config.stop_words_file = ""
        f = StopWordsFilter(mock_config, mock_logger)

        assert f.should_skip(make_post(1, 1, "зашёл в церковью")) is True
        assert f.should_skip(make_post(1, 1, "у церкви")) is True
        assert f.should_skip(make_post(1, 1, "около церковью")) is True

    def test_substring_matches_non_russian(self, mock_config, mock_logger):
        """Нерусские слова и аббревиатуры — substring-поиск («18+», «СВО»)."""
        mock_config.stop_words = ["18+", "СВО", "vape"]
        mock_config.stop_words_file = ""
        f = StopWordsFilter(mock_config, mock_logger)

        assert f.should_skip(make_post(1, 1, "контент 18+ только")) is True
        assert f.should_skip(make_post(1, 1, "на СВО мобилизовали")) is True
        assert f.should_skip(make_post(1, 1, "купил vape новый")) is True
        assert f.should_skip(make_post(1, 1, "обычный пост")) is False

    def test_multi_word_phrase_matches(self, mock_config, mock_logger):
        """Многословные фразы — substring-поиск («игровые автоматы»)."""
        mock_config.stop_words = ["игровые автоматы"]
        mock_config.stop_words_file = ""
        f = StopWordsFilter(mock_config, mock_logger)

        assert f.should_skip(make_post(1, 1, "зашёл в игровые автоматы")) is True
        assert f.should_skip(make_post(1, 1, "игровые автоматы выиграл")) is True
        assert f.should_skip(make_post(1, 1, "обычный пост")) is False

    def test_lemmatization_no_false_positive(self, mock_config, mock_logger):
        """Слово с другой леммой не вызывает ложного срабатывания."""
        mock_config.stop_words = ["политика"]
        mock_config.stop_words_file = ""
        f = StopWordsFilter(mock_config, mock_logger)

        # «политический» — прилагательное, лемма «политический» ≠ «политика»
        assert f.should_skip(make_post(1, 1, "политический анализ")) is False
        # «политику» — винительный падеж, лемма «политика» — совпадает
        assert f.should_skip(make_post(1, 1, "обсуждаем политику")) is True


class TestFilterChain:
    def test_filters_old_posts(self, mock_config, mock_logger):
        """FilterChain отсеивает старые посты через DateFilter."""
        chain = FilterChain(
            [
                DateFilter(mock_config.days_back),
                EmptyTextFilter(),
                StopWordsFilter(mock_config, mock_logger),
            ]
        )

        posts: list[Post] = [
            make_post(1, 1, "fresh", days_ago=1),
            make_post(2, 2, "old", days_ago=30),
        ]
        result = chain.filter(posts)
        assert len(result) == 1
        assert result[0].owner_id == 1

    def test_filters_empty_text(self, mock_config, mock_logger):
        """FilterChain отсеивает пустые посты через EmptyTextFilter."""
        chain = FilterChain(
            [
                DateFilter(mock_config.days_back),
                EmptyTextFilter(),
                StopWordsFilter(mock_config, mock_logger),
            ]
        )

        posts: list[Post] = [
            make_post(1, 1, "real text"),
            make_post(2, 2, "   "),
            make_post(3, 3, ""),
        ]
        result = chain.filter(posts)
        assert len(result) == 1
        assert result[0].owner_id == 1

    def test_filters_stop_words(self, mock_config, mock_logger):
        """FilterChain отсеивает стоп-слова через StopWordsFilter."""
        chain = FilterChain(
            [
                DateFilter(mock_config.days_back),
                EmptyTextFilter(),
                StopWordsFilter(mock_config, mock_logger),
            ]
        )

        posts: list[Post] = [
            make_post(1, 1, "обычный пост"),
            make_post(2, 2, "Это ПОЛИТИКА и выборы"),
            make_post(3, 3, "нейтральный контент"),
        ]
        result = chain.filter(posts)
        assert len(result) == 2
        assert result[0].owner_id == 1
        assert result[1].owner_id == 3

    def test_all_pass(self, mock_config, mock_logger):
        """Все свежие посты с текстом и без стоп-слов проходят."""
        chain = FilterChain(
            [
                DateFilter(mock_config.days_back),
                EmptyTextFilter(),
                StopWordsFilter(mock_config, mock_logger),
            ]
        )

        posts: list[Post] = [
            make_post(1, 1, "post one"),
            make_post(2, 2, "post two"),
            make_post(3, 3, "post three"),
        ]
        result = chain.filter(posts)
        assert len(result) == 3

    def test_empty_chain_passes_all(self):
        """Пустая цепочка фильтров не отсеивает ничего."""
        chain = FilterChain([])
        posts = [make_post(1, 1, "anything", days_ago=999)]
        assert len(chain.filter(posts)) == 1
