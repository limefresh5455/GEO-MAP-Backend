# TODO - Generic AI Chat API

- [ ] Add generic AI chat models/tables and register them in Alembic
  - [x] app/models/ai_chat_session.py
  - [x] app/models/ai_chat_message.py
  - [x] app/repositories/ai_chat_repository.py
  - [x] app/services/ai_chat_service.py
  - [x] app/schemas/ai_chat.py
  - [x] app/api/v1/ai_chat.py
  - [x] app/api/v1/__init__.py include router
  - [x] app/models/__init__.py export models
  - [x] alembic/env.py import models
  - [x] alembic migration: 20260617120000_ai_chat_generic_tables.py
- [x] Run DB migrations (alembic upgrade 20260617120000)
- [x] Run a quick smoke test by calling the new endpoint (create new session + continue)



