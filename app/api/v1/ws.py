import asyncio
import json
import logging
from typing import Optional
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status
from sqlalchemy.orm import Session

from app.core.security import decode_access_token
from app.core.websocket_manager import ConnectionManager
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.schemas.websocket import WSClientMessage
from app.services.ai_chat_service import AIChatService
from app.services.place_qa_service import PlaceQAService

logger = logging.getLogger(__name__)

router = APIRouter(tags=["WebSocket"])
manager = ConnectionManager()

# How long to wait for the next client message before timing out
_WS_RECEIVE_TIMEOUT = 300.0  # 5 minutes


@router.websocket("/ws/chat")
async def ws_chat_endpoint(websocket: WebSocket):
    """
    WebSocket endpoint for streaming chat and place Q&A.

    **Authentication:** Client must send a JWT token as the first message:
    ```json
    { "type": "auth", "token": "Bearer <jwt>" }
    ```

    After authentication, send messages:
    ```json
    { "type": "chat_message", "query": "Plan a trip", "session_id": null }
    { "type": "place_question", "query": "Is it open?", "place_id": "...", "session_id": null }
    ```

    Server streams responses as JSON events:
    - `{"type": "connected", ...}` — initial ack
    - `{"type": "metadata", "session_id": "...", "is_new_session": bool}`
    - `{"type": "token", "content": "..."}` — one per chunk
    - `{"type": "done", "title": "..."}` — streaming complete
    - `{"type": "error", "message": "..."}` — error occurred
    """
    await websocket.accept()
    logger.info("WebSocket connection accepted")

    user: Optional[User] = None
    db: Optional[Session] = None
    openai_client = None
    pinecone_client = None

    try:
        # ── Step 1: Authenticate ──
        try:
            raw = await asyncio.wait_for(
                websocket.receive_text(), timeout=_WS_RECEIVE_TIMEOUT
            )
        except asyncio.TimeoutError:
            await websocket.send_json(
                {
                    "type": "error",
                    "message": "Authentication timeout. Send auth within 5 minutes.",
                }
            )
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        auth_msg = json.loads(raw)

        if auth_msg.get("type") != "auth" or not auth_msg.get("token"):
            await websocket.send_json(
                {
                    "type": "error",
                    "message": (
                        'First message must be: {"type": "auth", "token": "Bearer <jwt>"}'
                    ),
                }
            )
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        from app.database.connection import SessionLocal
        from app.services.token_blacklist_service import TokenBlacklistService

        db = SessionLocal()
        # Case-insensitive Bearer token stripping
        raw_token = auth_msg["token"]
        prefix = "Bearer "
        if raw_token[: len(prefix)].lower() == prefix.lower():
            token_str = raw_token[len(prefix) :].strip()
        else:
            token_str = raw_token.strip()

        # Blacklist check
        is_blacklisted = await TokenBlacklistService.is_token_blacklisted(token_str)
        if is_blacklisted:
            await websocket.send_json(
                {
                    "type": "error",
                    "message": "Token has been revoked. Please log in again.",
                }
            )
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            db.close()
            return

        # Decode JWT
        payload = decode_access_token(token_str)
        if payload is None or not payload.get("sub"):
            await websocket.send_json(
                {
                    "type": "error",
                    "message": "Invalid or expired authentication token",
                }
            )
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            db.close()
            return

        # Load user from DB
        try:
            user_id_int = int(payload["sub"])
        except (ValueError, TypeError):
            await websocket.send_json(
                {
                    "type": "error",
                    "message": "Invalid token payload",
                }
            )
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            db.close()
            return

        user_repo = UserRepository(db)
        user = user_repo.get_active_by_id(user_id_int)
        if user is None:
            await websocket.send_json(
                {
                    "type": "error",
                    "message": "User not found or account is inactive",
                }
            )
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            db.close()
            return

        # Get clients from app state via the websocket connection
        openai_client = getattr(websocket.app.state, "openai_client", None)
        pinecone_client = getattr(websocket.app.state, "pinecone_client", None)

        if openai_client is None:
            await websocket.send_json(
                {
                    "type": "error",
                    "message": "OpenAI client not initialized. Server may still be starting.",
                }
            )
            await websocket.close(code=status.WS_1011_INTERNAL_ERROR)
            db.close()
            return

        # Register in connection manager
        await manager.connect(user.id, websocket)

        # Send connection ack
        await websocket.send_json(
            {
                "type": "connected",
                "user_id": user.id,
                "message": "Connected to Geo Map streaming server",
            }
        )

        logger.info("WebSocket authenticated — user_id=%s", user.id)

        # ── Step 2: Message loop ──
        while True:
            try:
                raw = await asyncio.wait_for(
                    websocket.receive_text(), timeout=_WS_RECEIVE_TIMEOUT
                )
            except asyncio.TimeoutError:
                logger.info("WebSocket idle timeout — user_id=%s", user.id)
                await websocket.send_json(
                    {
                        "type": "error",
                        "message": "Connection timed out due to inactivity",
                    }
                )
                await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
                return

            data = json.loads(raw)

            # Validate message format
            try:
                msg = WSClientMessage(**data)
            except Exception as exc:
                await websocket.send_json(
                    {
                        "type": "error",
                        "message": f"Invalid message format: {exc}",
                    }
                )
                continue

            # ── Route to appropriate handler ──
            try:
                if msg.type == "chat_message":
                    await _handle_chat_message(
                        websocket=websocket,
                        user=user,
                        db=db,
                        openai_client=openai_client,
                        query=msg.query,
                        session_id=msg.session_id,
                    )
                elif msg.type == "place_question":
                    if not msg.place_id:
                        await websocket.send_json(
                            {
                                "type": "error",
                                "message": "place_id is required for place_question",
                            }
                        )
                        continue

                    if pinecone_client is None:
                        await websocket.send_json(
                            {
                                "type": "error",
                                "message": "Pinecone client not initialized",
                            }
                        )
                        continue

                    await _handle_place_question(
                        websocket=websocket,
                        user=user,
                        db=db,
                        openai_client=openai_client,
                        pinecone_client=pinecone_client,
                        place_id=msg.place_id,
                        query=msg.query,
                        session_id=msg.session_id,
                        top_k=msg.top_k,
                    )
                else:
                    await websocket.send_json(
                        {
                            "type": "error",
                            "message": (
                                f"Unknown message type: {msg.type}. "
                                f"Supported: chat_message, place_question"
                            ),
                        }
                    )

            except Exception as exc:
                logger.exception(
                    "WebSocket handler error (user_id=%s, type=%s)",
                    user.id,
                    msg.type,
                )
                await websocket.send_json(
                    {
                        "type": "error",
                        "message": f"Request failed: {str(exc)}",
                    }
                )

    except WebSocketDisconnect:
        logger.info(
            "WebSocket disconnected — user_id=%s", user.id if user else "unknown"
        )
    except json.JSONDecodeError:
        logger.warning("WebSocket received invalid JSON")
        try:
            await websocket.send_json(
                {
                    "type": "error",
                    "message": "Invalid JSON received",
                }
            )
        except Exception:
            pass
    except Exception as exc:
        logger.exception("WebSocket unexpected error: %s", exc)
    finally:
        if user:
            await manager.disconnect(user.id)
        if db:
            try:
                db.close()
            except Exception:
                pass


async def _handle_chat_message(
    websocket: WebSocket,
    user: User,
    db: Session,
    openai_client,
    query: str,
    session_id: Optional[str],
) -> None:
    """Handle a chat_message type — stream AI response via the chat service."""
    service = AIChatService(db=db, openai_client=openai_client)

    async for event_json in service.stream_chat(
        user_id=user.id,
        session_id=session_id,
        query=query,
    ):
        await websocket.send_text(event_json)


async def _handle_place_question(
    websocket: WebSocket,
    user: User,
    db: Session,
    openai_client,
    pinecone_client,
    place_id: str,
    query: str,
    session_id: Optional[str],
    top_k: int,
) -> None:
    """Handle a place_question type — stream AI response via the QA service."""
    service = PlaceQAService(
        db=db,
        openai_client=openai_client,
        pinecone_client=pinecone_client,
    )

    async for event_json in service.stream_answer(
        place_id=place_id,
        question=query,
        user_id=user.id,
        session_id=session_id,
        top_k=top_k,
    ):
        await websocket.send_text(event_json)
