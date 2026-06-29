import asyncio
import json
import logging
from typing import Optional
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status
from sqlalchemy.orm import Session

from app.core.auth_utils import strip_bearer_prefix, validate_token_sub
from app.core.security import decode_access_token
from app.core.websocket_manager import ConnectionManager
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.schemas.websocket import (
    WSChunk,
    WSClientMessage,
    WSError,
    WSStreamEnd,
    WSStreamStart,
)
from app.services.ai_chat_service import AIChatService
from app.services.place_qa_service import PlaceQAService

logger = logging.getLogger(__name__)

router = APIRouter(tags=["WebSocket"])
manager = ConnectionManager()

# How long to wait for the next client message before timing out
_WS_RECEIVE_TIMEOUT = 300.0  # 5 minutes


@router.websocket("/ws/chat")
async def ws_chat_endpoint(websocket: WebSocket):
    await websocket.accept()
    logger.info("WebSocket connection accepted")

    user: Optional[User] = None
    db: Optional[Session] = None
    openai_client = None
    pinecone_client = None

    try:
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
        token_str = strip_bearer_prefix(auth_msg["token"])

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
        user_id_int = validate_token_sub(payload.get("sub"))
        if user_id_int is None:
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

            # Parse JSON — if invalid, send error and keep listening
            try:
                data = json.loads(raw)
            except json.JSONDecodeError as exc:
                await websocket.send_json(
                    {
                        "type": "error",
                        "message": f"Invalid JSON received: {exc}",
                    }
                )
                continue

            # Validate message format
            try:
                msg = WSClientMessage(**data)
            except (ValueError, TypeError, KeyError) as exc:
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

            except (RuntimeError, ValueError, TypeError, KeyError) as exc:
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
        except (RuntimeError, AttributeError, OSError):
            pass
    except (RuntimeError, ValueError, TypeError, json.JSONDecodeError) as exc:
        logger.exception("WebSocket unexpected error: %s", exc)
    finally:
        if user:
            await manager.disconnect(user.id)
        if db:
            try:
                db.close()
            except (RuntimeError, AttributeError):
                pass


async def _handle_chat_message(
    websocket: WebSocket,
    user: User,
    db: Session,
    openai_client,
    query: str,
    session_id: Optional[str],
) -> None:
    service = AIChatService(db=db, openai_client=openai_client)
    current_session_id: Optional[str] = None

    try:
        async for event_json in service.stream_chat(
            user_id=user.id,
            session_id=session_id,
            query=query,
        ):
            event = json.loads(event_json)
            event_type = event.get("type")

            if event_type == "metadata":
                current_session_id = event["session_id"]
                await websocket.send_json(
                    WSStreamStart(
                        session_id=current_session_id,
                        is_new_session=event.get("is_new_session", False),
                    ).model_dump()
                )
            elif event_type == "token":
                await websocket.send_json(
                    WSChunk(
                        session_id=current_session_id or "",
                        token=event["content"],
                    ).model_dump()
                )
            elif event_type == "done":
                await websocket.send_json(
                    WSStreamEnd(
                        session_id=current_session_id or "",
                        title=event.get("title"),
                    ).model_dump()
                )
    except (RuntimeError, ValueError, TypeError, json.JSONDecodeError) as exc:
        logger.error(
            "WebSocket chat_message failed (user=%s, session=%s): %s",
            user.id,
            session_id,
            exc,
            extra={"metric": "ws.chat_message_error", "user_id": user.id},
        )
        await websocket.send_json(
            WSError(
                session_id=current_session_id,
                message=f"Chat failed: {str(exc)}",
            ).model_dump()
        )


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
    service = PlaceQAService(
        db=db,
        openai_client=openai_client,
        pinecone_client=pinecone_client,
    )
    current_session_id: Optional[str] = None

    try:
        async for event_json in service.stream_answer(
            place_id=place_id,
            question=query,
            user_id=user.id,
            session_id=session_id,
            top_k=top_k,
        ):
            event = json.loads(event_json)
            event_type = event.get("type")

            if event_type == "metadata":
                current_session_id = event["session_id"]
                await websocket.send_json(
                    WSStreamStart(
                        session_id=current_session_id,
                        is_new_session=event.get("is_new_session", False),
                    ).model_dump()
                )
            elif event_type == "token":
                await websocket.send_json(
                    WSChunk(
                        session_id=current_session_id or "",
                        token=event["content"],
                    ).model_dump()
                )
            elif event_type == "done":
                await websocket.send_json(
                    WSStreamEnd(
                        session_id=current_session_id or "",
                        title=event.get("title"),
                    ).model_dump()
                )
    except (RuntimeError, ValueError, TypeError, json.JSONDecodeError) as exc:
        logger.error(
            "WebSocket place_question failed (user=%s, place=%s): %s",
            user.id,
            place_id,
            exc,
            extra={
                "metric": "ws.place_question_error",
                "user_id": user.id,
                "place_id": place_id,
            },
        )
        await websocket.send_json(
            WSError(
                session_id=current_session_id,
                message=f"Question failed: {str(exc)}",
            ).model_dump()
        )
