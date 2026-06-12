"""
Async wrapper around the OpenAI Embeddings API and Chat Completions API.

Models
------
  Embeddings : text-embedding-3-small  (1536 dimensions)
  Chat       : gpt-4o-mini             (Phase 4 Q&A)

SDK: openai==1.35.3 — uses AsyncOpenAI throughout.

Design rules
------------
- One AsyncOpenAI instance per client object — SDK manages the connection pool.
- Batch embeds up to 100 texts per API call.
- Chat completions use a fixed system prompt that keeps answers
  strictly grounded to the provided context.
- Raises typed HTTPException subclasses so service layers stay clean.
- Never logs embedding vector values — high-dimensional floats add nothing
  to debug output and inflate log volume.
"""

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
        """
        Generate embeddings for a list of text strings.

        Texts are processed in batches of up to _BATCH_LIMIT to stay within
        the OpenAI API's per-request limit.

        Parameters
        ----------
        texts : List[str]
            Plain-text strings to embed. Empty strings are rejected by OpenAI;
            the caller should filter them out before calling this method.

        Returns
        -------
        List[List[float]]
            One embedding vector per input text, in the same order.
            Each vector has 1536 dimensions (text-embedding-3-small).

        Raises
        ------
        EmbeddingRateLimitError   — OpenAI 429
        EmbeddingError            — all other OpenAI errors
        """
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
        """
        Generate a grounded answer via OpenAI Chat Completions.

        Parameters
        ----------
        system_prompt : str
            Instructions that constrain the model to the provided context.
            Built by PlaceQAService to include structured place facts.
        user_message  : str
            The user's natural-language question.
        temperature   : float
            0.0–1.0. Low value (0.2) keeps answers factual and deterministic.
        max_tokens    : int
            Hard cap on answer length.

        Returns
        -------
        str — the model's answer text, stripped of leading/trailing whitespace.

        Raises
        ------
        EmbeddingRateLimitError  — OpenAI 429
        ChatCompletionError      — all other OpenAI errors
        """
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
