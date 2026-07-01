import logging
import os
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ui", tags=["UI – API Tester"])

# Paths
UI_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = UI_DIR / "templates"
STATIC_DIR = UI_DIR / "static"

# Jinja2 templates
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


# Serve the payment purchase page (main UI)


@router.get("", response_class=HTMLResponse, include_in_schema=False)
@router.get("/", response_class=HTMLResponse, include_in_schema=False)
async def payments_page(request: Request):
    """Render the credit purchase UI."""
    return templates.TemplateResponse(
        "payments.html",
        {"request": request, "page_title": "GeoMap — Buy Credits"},
    )
