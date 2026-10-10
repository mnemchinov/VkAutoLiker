"""LLM-фильтр тематики постов через litellm.completion.

Реализует PostFilterProtocol, но НЕ включается в FilterChain —
вызывается только через LLMFilterStage после DedupStage,
чтобы LLM работал с дедуплицированным списком (~target × 2 постов).

Системный промпт — универсальная задача арбитра (SKIP/OK-правила),
один для обоих режимов. Данные режима идут в user-сообщении:
  review — слова, найденные стоп-фильтром (found_words);
  llm — темы из config.llm_stop_topics.

should_skip возвращает True, если LLM ответил SKIP.
При таймауте — LLMTimeoutError (пост пропускается без маркировки).
При любой другой ошибке — False (не отсеивать, безопаснее оставить).
"""

import httpx
import litellm

from logger import AppLogger
from post import Post
from settings import Settings

from .protocol import PostFilterProtocol

SYSTEM_PROMPT = """Ты — фильтр контента постов ВКонтакте. \
Определи, содержит ли пост нежелательное содержимое.

Ответ SKIP — пост действительно содержит это содержимое:
— пост именно об этом слове/теме, слово используется в значении, связанном с темой.

Ответ OK — слова/темы не являются смыслом поста:
— слово в другом значении (карабин — защёлка на поводке, виски — часть лица, ром — имя);
— глагол или устойчивое выражение («время минет», «боль минет»);
— игра, метафора, бренд, название, профессиональный термин;
— слово упомянуто вскользь, а пост о чём-то другом.

Если пост действительно о теме — SKIP, даже если возможна безобидная интерпретация.

Определяй только по тексту поста. Не углубляйся в рассуждения, \
не переходи по ссылкам, не анализируй содержимое по URL.

Ответь только одним словом: SKIP или OK."""


class LLMTimeoutError(Exception):
    """Таймаут LLM-запроса — пост должен быть пропущен без маркировки."""


class LLMTopicFilter(PostFilterProtocol):
    """Фильтр тематики постов через LLM (litellm.completion)."""

    def __init__(self, config: Settings, logger: AppLogger):
        """Инициализирует LLM-фильтр с параметрами из конфигурации.

        Системный промпт — константа SYSTEM_PROMPT (универсальная задача
        арбитра), если config.llm_system_prompt не задан явно.

        При llm_ssl_verify=False устанавливает litellm.client_session с
        отключённой проверкой SSL — для корпоративных endpoint'ов с
        самоподписанным CA-сертификатом, отсутствующим в certifi.
        """
        self._config = config
        self._logger = logger
        self._system_prompt = config.llm_system_prompt or SYSTEM_PROMPT

        if not config.llm_ssl_verify:
            litellm.client_session = httpx.Client(verify=False, follow_redirects=True)

    def _build_user_message(self, post: Post, found_words: list[str] | None) -> str:
        """Собирает user-сообщение: данные режима (слова/темы) + текст поста."""
        if found_words:
            check = "Слова, найденные в посте: " + ", ".join(found_words)
        else:
            topics = "\n".join(f"— {t};" for t in self._config.llm_stop_topics)
            check = f"Темы для проверки:\n{topics}"
        text = post.text.strip()[: self._config.llm_max_text_length]
        return f"{check}\n\nПост:\n{text}"

    def should_skip(self, post: Post, found_words: list[str] | None = None) -> bool:
        """True, если LLM определил пост как нежелательный (SKIP).

        found_words — слова стоп-фильтра (режим review); без них — темы из
        llm_stop_topics (режим llm).

        При таймауте LLM — поднимает LLMTimeoutError, чтобы вызывающий код
        пропустил пост без маркировки (пост попадёт в следующую выборку).
        При другой ошибке LLM — False (не отсеивать). Текст обрезается до max_text_length.
        """
        text = post.text.strip()
        if not text:
            return False

        user_message = self._build_user_message(post, found_words)

        try:
            response = litellm.completion(
                model=self._config.llm_model,
                messages=[
                    {"role": "system", "content": self._system_prompt},
                    {"role": "user", "content": user_message},
                ],
                api_base=self._config.llm_api_base or None,
                api_key=self._config.llm_api_key.get_secret_value() or None,
                timeout=self._config.llm_timeout,
                temperature=0,
                max_tokens=self._config.llm_max_tokens,
                max_retries=0,
            )
            answer = response.choices[0].message.content.strip().upper()
            skip = "SKIP" in answer
            self._logger.info(
                f"LLM: пост {post.owner_id}_{post.item_id} → ответ={answer!r} skip={skip}"
            )
            return skip
        except litellm.Timeout as e:
            self._logger.warning(f"Таймаут LLM для поста {post.owner_id}_{post.item_id}: {e}")
            raise LLMTimeoutError(str(e)) from e
        except Exception as e:
            self._logger.warning(f"Ошибка LLM для поста {post.owner_id}_{post.item_id}: {e}")
            return False
