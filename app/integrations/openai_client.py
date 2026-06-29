import asyncio
import logging
from typing import AsyncGenerator, List
from fastapi import HTTPException, status
from openai import AsyncOpenAI, APIError, APITimeoutError, RateLimitError
from app.core.config import settings

logger = logging.getLogger(__name__)

# Maximum texts per single embeddings.create() call
_BATCH_LIMIT = 100
_MAX_RETRIES = 3
_BASE_RETRY_DELAY = 0.5


class EmbeddingError(HTTPException):
    """Raised when the OpenAI Embeddings API returns an error."""

    def __init__(self, detail: str = "Embedding generation failed"):
        super().__init__(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=detail,
        )


class EmbeddingRateLimitError(HTTPException):
    """Raised when OpenAI rate-limits the embeddings request."""

    def __init__(self):
        super().__init__(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="OpenAI rate limit exceeded. Try again shortly.",
        )


class ChatCompletionError(HTTPException):

    def __init__(self, detail: str = "Chat completion failed"):
        super().__init__(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=detail,
        )


class OpenAIEmbeddingClient:
    def __init__(self) -> None:
        self.model = settings.OPENAI_EMBEDDING_MODEL
        self._client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

    # Embeddings

    async def embed_texts(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []

        filtered_texts = [t for t in texts if t and t.strip()]

        if not filtered_texts:
            return [[0.0] * 1536 for _ in texts]

        all_embeddings: List[List[float]] = []

        for batch_start in range(0, len(filtered_texts), _BATCH_LIMIT):
            batch = filtered_texts[batch_start : batch_start + _BATCH_LIMIT]
            logger.info(
                "OpenAI embed — model: %s, batch: %d texts (offset %d)",
                self.model,
                len(batch),
                batch_start,
            )
            try:
                response = await self._client.embeddings.create(
                    input=batch,
                    model=self.model,
                )
                batch_vectors = [item.embedding for item in response.data]
                all_embeddings.extend(batch_vectors)
                logger.info(
                    "OpenAI embed — received %d vectors (dim=%d)",
                    len(batch_vectors),
                    len(batch_vectors[0]) if batch_vectors else 0,
                )

            except RateLimitError:
                logger.warning("OpenAI rate limit hit during embedding")
                raise EmbeddingRateLimitError()

            except (APITimeoutError, APIError):
                for attempt in range(_MAX_RETRIES + 1):
                    try:
                        response = await self._client.embeddings.create(
                            input=batch,
                            model=self.model,
                        )
                        batch_vectors = [item.embedding for item in response.data]
                        all_embeddings.extend(batch_vectors)
                        logger.info(
                            "OpenAI embed — received %d vectors (dim=%d)%s",
                            len(batch_vectors),
                            len(batch_vectors[0]) if batch_vectors else 0,
                            " after retry" if attempt > 0 else "",
                        )
                        break
                    except (APITimeoutError, APIError) as retry_exc:
                        if attempt == _MAX_RETRIES:
                            if isinstance(retry_exc, APITimeoutError):
                                logger.error(
                                    "OpenAI embedding request timed out after retries"
                                )
                                raise EmbeddingError(
                                    "OpenAI embedding request timed out"
                                )
                            logger.error(
                                "OpenAI API error during embedding after retries: %s",
                                retry_exc,
                            )
                            raise EmbeddingError(
                                f"OpenAI API error: {retry_exc.message}"
                            )
                        delay = _BASE_RETRY_DELAY * (2**attempt)
                        logger.warning(
                            "OpenAI embed attempt %d/%d failed, retrying in %.1fs",
                            attempt + 1,
                            _MAX_RETRIES + 1,
                            delay,
                        )
                        await asyncio.sleep(delay)
                    except RateLimitError:
                        logger.warning("OpenAI rate limit hit during embedding retry")
                        raise EmbeddingRateLimitError()
            except (ValueError, TypeError, RuntimeError) as exc:
                logger.error("Unexpected error during embedding: %s", exc)
                raise EmbeddingError(str(exc))

        return all_embeddings

    async def embed_single(self, text: str) -> List[float]:
        results = await self.embed_texts([text])
        return results[0]

    # Non-streaming chat completions (kept for HTTP endpoints)

    async def chat_completion(
        self,
        system_prompt: str,
        user_message: str,
        temperature: float = 0.2,
        max_tokens: int = 800,
    ) -> str:
        model = settings.OPENAI_CHAT_MODEL
        logger.info(
            "OpenAI chat completion — model: %s, max_tokens: %d", model, max_tokens
        )
        for attempt in range(_MAX_RETRIES + 1):
            try:
                response = await self._client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_message},
                    ],
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                answer = response.choices[0].message.content or ""
                logger.info(
                    "OpenAI chat completion — received %d chars%s",
                    len(answer),
                    " after retry" if attempt > 0 else "",
                )
                return answer.strip()

            except RateLimitError:
                logger.warning("OpenAI rate limit hit during chat completion")
                raise EmbeddingRateLimitError()

            except (APITimeoutError, APIError) as exc:
                if attempt == _MAX_RETRIES:
                    if isinstance(exc, APITimeoutError):
                        logger.error("OpenAI chat completion timed out after retries")
                        raise ChatCompletionError(
                            "OpenAI chat completion request timed out"
                        )
                    logger.error(
                        "OpenAI API error during chat completion after retries: %s",
                        exc,
                    )
                    raise ChatCompletionError(f"OpenAI API error: {exc.message}")
                delay = _BASE_RETRY_DELAY * (2**attempt)
                logger.warning(
                    "OpenAI chat completion attempt %d/%d failed, retrying in %.1fs: %s",
                    attempt + 1,
                    _MAX_RETRIES + 1,
                    delay,
                    exc,
                )
                await asyncio.sleep(delay)

            except (ValueError, TypeError, RuntimeError) as exc:
                logger.error("Unexpected error during chat completion: %s", exc)
                raise ChatCompletionError(str(exc))

    async def get_chat_completion(
        self,
        messages: List[dict],
        temperature: float = 0.7,
        max_tokens: int = 1000,
    ) -> str:
        model = settings.OPENAI_CHAT_MODEL
        logger.info(
            "OpenAI chat with history — model: %s, messages: %d, max_tokens: %d",
            model,
            len(messages),
            max_tokens,
        )
        for attempt in range(_MAX_RETRIES + 1):
            try:
                response = await self._client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                answer = response.choices[0].message.content or ""
                logger.info(
                    "OpenAI chat with history — received %d chars%s",
                    len(answer),
                    " after retry" if attempt > 0 else "",
                )
                return answer.strip()

            except RateLimitError:
                logger.warning("OpenAI rate limit hit during chat with history")
                raise EmbeddingRateLimitError()

            except (APITimeoutError, APIError) as exc:
                if attempt == _MAX_RETRIES:
                    if isinstance(exc, APITimeoutError):
                        logger.error("OpenAI chat with history timed out after retries")
                        raise ChatCompletionError(
                            "OpenAI chat completion request timed out"
                        )
                    logger.error(
                        "OpenAI API error during chat with history after retries: %s",
                        exc,
                    )
                    raise ChatCompletionError(f"OpenAI API error: {exc.message}")
                delay = _BASE_RETRY_DELAY * (2**attempt)
                logger.warning(
                    "OpenAI chat with history attempt %d/%d failed, "
                    "retrying in %.1fs: %s",
                    attempt + 1,
                    _MAX_RETRIES + 1,
                    delay,
                    exc,
                )
                await asyncio.sleep(delay)

            except (ValueError, TypeError, RuntimeError) as exc:
                logger.error("Unexpected error during chat with history: %s", exc)
                raise ChatCompletionError(str(exc))

    # Streaming chat completions (for WebSocket delivery)

    async def stream_chat_completion(
        self,
        system_prompt: str,
        user_message: str,
        temperature: float = 0.2,
        max_tokens: int = 800,
    ) -> AsyncGenerator[str, None]:
        model = settings.OPENAI_CHAT_MODEL
        logger.info("OpenAI stream chat — model: %s, max_tokens: %d", model, max_tokens)

        for attempt in range(_MAX_RETRIES + 1):
            try:
                stream = await self._client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_message},
                    ],
                    temperature=temperature,
                    max_tokens=max_tokens,
                    stream=True,
                )
                async for chunk in stream:
                    delta = chunk.choices[0].delta if chunk.choices else None
                    if delta and delta.content:
                        yield delta.content
                return  # Success — exit generator

            except RateLimitError:
                logger.warning("OpenAI rate limit hit during stream chat")
                raise EmbeddingRateLimitError()

            except (APITimeoutError, APIError) as exc:
                if attempt == _MAX_RETRIES:
                    if isinstance(exc, APITimeoutError):
                        logger.error("OpenAI stream chat timed out after retries")
                        raise ChatCompletionError("OpenAI chat completion timed out")
                    logger.error(
                        "OpenAI API error during stream chat after retries: %s",
                        exc,
                    )
                    raise ChatCompletionError(f"OpenAI API error: {exc.message}")
                delay = _BASE_RETRY_DELAY * (2**attempt)
                logger.warning(
                    "OpenAI stream chat attempt %d/%d failed, " "retrying in %.1fs: %s",
                    attempt + 1,
                    _MAX_RETRIES + 1,
                    delay,
                    exc,
                )
                await asyncio.sleep(delay)

            except (ValueError, TypeError, RuntimeError) as exc:
                logger.error("Unexpected error during stream chat: %s", exc)
                raise ChatCompletionError(str(exc))

    async def stream_chat_with_history(
        self,
        messages: List[dict],
        temperature: float = 0.7,
        max_tokens: int = 1000,
    ) -> AsyncGenerator[str, None]:
        model = settings.OPENAI_CHAT_MODEL
        logger.info(
            "OpenAI stream chat with history — model: %s, messages: %d, "
            "max_tokens: %d",
            model,
            len(messages),
            max_tokens,
        )

        for attempt in range(_MAX_RETRIES + 1):
            try:
                stream = await self._client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    stream=True,
                )
                async for chunk in stream:
                    delta = chunk.choices[0].delta if chunk.choices else None
                    if delta and delta.content:
                        yield delta.content
                return  # Success — exit generator

            except RateLimitError:
                logger.warning("OpenAI rate limit hit during stream chat with history")
                raise EmbeddingRateLimitError()

            except (APITimeoutError, APIError) as exc:
                if attempt == _MAX_RETRIES:
                    if isinstance(exc, APITimeoutError):
                        logger.error(
                            "OpenAI stream chat with history timed out after retries"
                        )
                        raise ChatCompletionError("OpenAI chat completion timed out")
                    logger.error(
                        "OpenAI API error during stream chat with history "
                        "after retries: %s",
                        exc,
                    )
                    raise ChatCompletionError(f"OpenAI API error: {exc.message}")
                delay = _BASE_RETRY_DELAY * (2**attempt)
                logger.warning(
                    "OpenAI stream chat with history attempt %d/%d failed, "
                    "retrying in %.1fs: %s",
                    attempt + 1,
                    _MAX_RETRIES + 1,
                    delay,
                    exc,
                )
                await asyncio.sleep(delay)

            except (ValueError, TypeError, RuntimeError) as exc:
                logger.error(
                    "Unexpected error during stream chat with history: %s",
                    exc,
                )
                raise ChatCompletionError(str(exc))
