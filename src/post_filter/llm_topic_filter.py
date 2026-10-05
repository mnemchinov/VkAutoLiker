"""LLM-фильтр тематики постов через litellm.completion.

Реализует PostFilterProtocol, но НЕ включается в FilterChain —
вызывается только через LLMFilterStage после DedupStage,
чтобы LLM работал с дедуплицированным списком (~target × 2 постов).

should_skip возвращает True, если LLM ответил SKIP.
При любой ошибке — False (не отсеивать, безопаснее оставить).
"""

import httpx
import litellm

from logger import AppLogger
from post import Post
from settings import Settings

from .protocol import PostFilterProtocol

DEFAULT_SYSTEM_PROMPT_TEMPLATE = """Ты — модератор постов ВКонтакте. \
Определи, подходит ли пост для автоматического лайка.

Отклоняй (ответ SKIP) посты на темы:
{topics}

Ответь только одним словом: SKIP или OK."""


class LLMTopicFilter(PostFilterProtocol):
    """Фильтр тематики постов через LLM (litellm.completion)."""

    def __init__(self, config: Settings, logger: AppLogger):
        """Инициализирует LLM-фильтр с параметрами из конфигурации.

        Промпт собирается из config.llm_stop_topics (список стоп-тем),
        если config.llm_system_prompt не задан явно.

        При llm_ssl_verify=False устанавливает litellm.client_session с
        отключённой проверкой SSL — для корпоративных endpoint'ов с
        самоподписанным CA-сертификатом, отсутствующим в certifi.
        """
        self._config = config
        self._logger = logger
        if config.llm_system_prompt:
            self._system_prompt = config.llm_system_prompt
        else:
            topics = "\n".join(f"— {t};" for t in config.llm_stop_topics)
            self._system_prompt = DEFAULT_SYSTEM_PROMPT_TEMPLATE.format(topics=topics)

        if not config.llm_ssl_verify:
            litellm.client_session = httpx.Client(verify=False, follow_redirects=True)

    def should_skip(self, post: Post) -> bool:
        """True, если LLM определил пост как нежелательный (SKIP).

        При ошибке LLM — False (не отсеивать). Текст обрезается до max_text_length.
        """
        text = post.text.strip()[: self._config.llm_max_text_length]
        if not text:
            return False

        try:
            response = litellm.completion(
                model=self._config.llm_model,
                messages=[
                    {"role": "system", "content": self._system_prompt},
                    {"role": "user", "content": text},
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
        except Exception as e:
            self._logger.warning(f"Ошибка LLM для поста {post.owner_id}_{post.item_id}: {e}")
            return False
