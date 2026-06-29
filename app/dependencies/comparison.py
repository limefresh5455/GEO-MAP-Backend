import logging
from fastapi import Depends
from sqlalchemy.orm import Session

from app.database.connection import get_db
from app.services.comparison_service import ComparisonService

logger = logging.getLogger(__name__)


def get_comparison_service(
    db: Session = Depends(get_db),
) -> ComparisonService:
    return ComparisonService(db=db)
