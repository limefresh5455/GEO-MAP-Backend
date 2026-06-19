import logging
from typing import List, Optional
from fastapi import HTTPException, status
from openai import AsyncOpenAI, APIError, APITimeoutError, RateLimitError
from app.core.config import settings

logger = logging.getLogger(__name__)

# Maximum texts per single embeddings.create() call
_BATCH_LIMIT = 100


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
    """Raised when the OpenAI Chat Completions API returns an error."""

    def __init__(self, detail: str = "Chat completion failed"):
        super().__init__(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=detail,
        )


class OpenAIEmbeddingClient:
    """
    Generates text embeddings via the OpenAI API.
    Stateless — safe to instantiate once per dependency-injection cycle.
    """

    def __init__(self) -> None:
        self.model = settings.OPENAI_EMBEDDING_MODEL
        # AsyncOpenAI automatically uses OPENAI_API_KEY env var if api_key
        # is not passed; we pass it explicitly for clarity.
        self._client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def embed_texts(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []

        # B-036 FIX: Filter out empty strings before sending to OpenAI
        # OpenAI API rejects empty strings with 400 Bad Request
        filtered_texts = [t for t in texts if t and t.strip()]
        
        if not filtered_texts:
            # All texts were empty - return empty vectors for each
            return [[0.0] * 1536 for _ in texts]

        all_embeddings: List[List[float]] = []

        for batch_start in range(0, len(filtered_texts), _BATCH_LIMIT):
            batch = filtered_texts[batch_start: batch_start + _BATCH_LIMIT]
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
                # Response data is sorted by index, matching input order
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

            except APITimeoutError:
                logger.error("OpenAI embedding request timed out")
                raise EmbeddingError("OpenAI embedding request timed out")

            except APIError as exc:
                logger.error("OpenAI API error during embedding: %s", exc)
                raise EmbeddingError(f"OpenAI API error: {exc.message}")

            except Exception as exc:
                logger.error("Unexpected error during embedding: %s", exc)
                raise EmbeddingError(str(exc))

        return all_embeddings

    async def embed_single(self, text: str) -> List[float]:
        """
        Convenience wrapper — embed a single string.
        Used during Q&A query embedding in Phase 4.
        """
        results = await self.embed_texts([text])
        return results[0]

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
        try:
            response = await self._client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user",   "content": user_message},
                ],
                temperature=temperature,
                max_tokens=max_tokens,
            )
            answer = response.choices[0].message.content or ""
            logger.info(
                "OpenAI chat completion — received %d chars", len(answer)
            )
            return answer.strip()

        except RateLimitError:
            logger.warning("OpenAI rate limit hit during chat completion")
            raise EmbeddingRateLimitError()

        except APITimeoutError:
            logger.error("OpenAI chat completion request timed out")
            raise ChatCompletionError("OpenAI chat completion request timed out")

        except APIError as exc:
            logger.error("OpenAI API error during chat completion: %s", exc)
            raise ChatCompletionError(f"OpenAI API error: {exc.message}")

        except Exception as exc:
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
            model, len(messages), max_tokens
        )
        try:
            response = await self._client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            answer = response.choices[0].message.content or ""
            logger.info(
                "OpenAI chat with history — received %d chars", len(answer)
            )
            return answer.strip()

        except RateLimitError:
            logger.warning("OpenAI rate limit hit during chat with history")
            raise EmbeddingRateLimitError()

        except APITimeoutError:
            logger.error("OpenAI chat with history request timed out")
            raise ChatCompletionError("OpenAI chat completion request timed out")

        except APIError as exc:
            logger.error("OpenAI API error during chat with history: %s", exc)
            raise ChatCompletionError(f"OpenAI API error: {exc.message}")

        except Exception as exc:
            logger.error("Unexpected error during chat with history: %s", exc)
            raise ChatCompletionError(str(exc))
