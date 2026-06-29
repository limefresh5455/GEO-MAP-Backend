import logging
from typing import Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.repositories.visit_repository import VisitRepository
from app.repositories.knowledge_repository import KnowledgeRepository
from app.schemas.visits import VisitLogResponse

logger = logging.getLogger(__name__)


class VisitService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.repo = VisitRepository(db)
        self.knowledge_repo = KnowledgeRepository(db)

    def _denormalize_place(self, place_id: str) -> dict:
        """Fetch denormalized place fields for visit logging."""
        fields = {
            "display_name": None,
            "formatted_address": None,
            "primary_type": None,
            "latitude": None,
            "longitude": None,
        }
        place = self.knowledge_repo.get_place_detail(place_id)
        if place:
            fields["display_name"] = place.display_name
            fields["formatted_address"] = place.formatted_address
            fields["primary_type"] = place.primary_type
            fields["latitude"] = place.latitude
            fields["longitude"] = place.longitude
        return fields

    async def log_visit(
        self,
        user_id: int,
        place_id: str,
        rating_given: Optional[float] = None,
        review_text: Optional[str] = None,
        with_whom: Optional[str] = None,
        mood: Optional[str] = None,
    ) -> VisitLogResponse:
        place_fields = self._denormalize_place(place_id)
        record = self.repo.create(
            user_id=user_id,
            place_id=place_id,
            rating_given=rating_given,
            review_text=review_text,
            with_whom=with_whom,
            mood=mood,
            **place_fields,
        )
        self.db.commit()
        return VisitLogResponse.model_validate(record)

    async def list_visits(
        self,
        user_id: int,
        page: int = 1,
        page_size: int = 20,
        place_id: Optional[str] = None,
    ) -> Tuple[List[VisitLogResponse], int, bool]:
        offset = (page - 1) * page_size
        records, total = self.repo.list_visits(
            user_id=user_id,
            place_id=place_id,
            limit=page_size,
            offset=offset,
        )
        has_next = (offset + page_size) < total
        items = [VisitLogResponse.model_validate(r) for r in records]
        return items, total, has_next

    async def update_visit(
        self,
        visit_id: int,
        user_id: int,
        rating_given: Optional[float] = None,
        review_text: Optional[str] = None,
        with_whom: Optional[str] = None,
        mood: Optional[str] = None,
    ) -> Optional[VisitLogResponse]:
        record = self.repo.get_by_id(visit_id, user_id)
        if not record:
            return None
        record = self.repo.update(
            record,
            rating_given=rating_given,
            review_text=review_text,
            with_whom=with_whom,
            mood=mood,
        )
        self.db.commit()
        return VisitLogResponse.model_validate(record)

    async def delete_visit(self, visit_id: int, user_id: int) -> bool:
        record = self.repo.get_by_id(visit_id, user_id)
        if not record:
            return False
        self.repo.delete(record)
        self.db.commit()
        return True

    async def get_stats(self, user_id: int) -> Dict:
        return self.repo.get_stats(user_id)
