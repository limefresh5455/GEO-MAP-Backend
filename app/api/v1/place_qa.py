import logging
from fastapi import APIRouter, Depends, Path, Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.dependencies.auth import get_current_user
from app.dependencies.place_qa import get_place_qa_service
from app.models.user import User
from app.schemas.place_qa import PlaceQuestionRequest, PlaceQuestionResponse
from app.services.place_qa_service import PlaceQAService

logger = logging.getLogger(__name__)

# Initialize rate limiter for this router
limiter = Limiter(key_func=get_remote_address)

router = APIRouter(prefix="/places", tags=["Place Q&A"])


@router.post("/{place_id}/question", response_model=PlaceQuestionResponse)
@limiter.limit("20/minute")
async def ask_place_question(
    request: Request,
    place_id: str = Path(..., min_length=1, max_length=255),
    payload: PlaceQuestionRequest = ...,
    current_user: User = Depends(get_current_user),
    service: PlaceQAService = Depends(get_place_qa_service),
) -> PlaceQuestionResponse:
    """
    Ask natural-language questions about a place using AI.
    
    **Request body:**
    ```json
    {
      "question": "Is this place wheelchair accessible?"
    }
    ```
    
    Uses RAG pipeline with Pinecone and OpenAI. Rate limited to 20/min.
    Place must exist in DB (call Details API first).
    """
    logger.info(
        "Place Q&A — user_id: %s, place_id: %s, question: %r",
        current_user.id,
        place_id,
        payload.question,
    )

    return await service.answer_question(
        place_id=place_id,
        request=payload,
        user_id=current_user.id,
    )
