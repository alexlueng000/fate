# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a **FastAPI-based AI-powered Chinese fortune-telling application** (八字算命/Bazi) that combines traditional Chinese metaphysics with modern AI. The application calculates Bazi (eight characters) birth charts using true solar time and provides intelligent interpretations via the DeepSeek API.

**Domains**: yizhanmaster.site, fateinsight.site

## Common Development Commands

### Database Management
```bash
# Initialize/create database tables
python init_db.py

# Create a new migration (after model changes)
alembic revision --autogenerate -m "description"

# Apply migrations
alembic upgrade head

# Rollback one migration
alembic downgrade -1

# View migration history
alembic history
```

### Running the Application
```bash
# Development server with auto-reload
uvicorn main:app --reload --host 0.0.0.0 --port 8000

# Production server
uvicorn main:app --host 0.0.0.0 --port 8000 --workers 4
```

### Testing
```bash
# Run all tests
pytest

# Run specific test file
pytest app/test/test_utils.py

# Run with coverage
pytest --cov=app --cov-report=html
```

### Dependencies
```bash
# Install dependencies
pip install -r requirements.txt

# Create virtual environment (recommended)
python -m venv venv311
source venv311/bin/activate  # On Windows: venv311\Scripts\activate
```

## Architecture

### Core Components

1. **API Layer** (`main.py`, `app/routers/`)
   - FastAPI with modular router structure
   - RESTful endpoints organized by domain (chat, bazi, users, admin, kb)
   - CORS middleware configured for frontend origins

2. **Business Logic** (`app/services/`, `app/chat/`)
   - `app/chat/service.py`: Main chat orchestration with streaming support
   - `app/chat/deepseek_client.py`: DeepSeek API integration
   - `app/chat/rag.py`: Knowledge base retrieval (RAG)
   - `app/chat/store.py`: In-memory conversation state management

3. **Data Layer** (`app/models/`, `app/db.py`)
   - SQLAlchemy 2.0 ORM with MySQL backend
   - Connection pooling (size=10, max_overflow=20)
   - Session management via dependency injection in `app/deps.py`

4. **Authentication** (`app/security.py`, `app/routers/users.py`)
   - JWT-based authentication (7-day expiration)
   - Password hashing with bcrypt
   - Multiple login methods: email/password, phone verification, WeChat openid

### Key Business Flows

#### Bazi Calculation Flow
1. Frontend sends birth data (date, time, location)
2. Backend calculates true solar time based on longitude
3. `lunar-python` library converts to Lunar calendar and calculates:
   - Four Pillars (年月日时)
   - Ten-Year Da Yun (大运) cycles
4. Returns structured JSON for display and AI analysis

#### Chat Flow (Streaming)
1. `/api/chat/start` initializes conversation with system prompt
2. System prompt loaded from database (`app_config` table)
3. Knowledge base (RAG) retrieves relevant passages from `kb_index/`
4. DeepSeek API streams responses via Server-Sent Events (SSE)
5. Response post-processed (Markdown normalization, text cleanup)
6. Conversation history persisted to `conversations`/`messages` tables

#### Database Schema (Key Tables)
- `users` - User accounts (email, phone, openid, password_hash)
- `conversations` - Chat sessions with title and timestamps
- `messages` - Individual messages (user/assistant/system roles)
- `app_config` - System configuration including prompts (versioned)

### Streaming Implementation

The application uses Server-Sent Events (SSE) for real-time chat responses:

- Detection: `should_stream(request)` checks for `stream=true` query param
- Generator function yields chunks wrapped in `sse_pack()`
- Frontend receives events: `{"text": "...", "replace": true}` and `[DONE]`
- Time statistics tracked: first_byte, streaming, pre/post processing

See `app/chat/sse.py` and `app/chat/service.py` for implementation.

### Knowledge Base System

- **Source files**: `kb_files/` (Word documents, text files)
- **Processed index**: `kb_index/` (chunks.json, embeddings, metadata)
- **Retrieval**: Cosine similarity search via `app/chat/rag.py`
- **Integration**: Retrieved passages injected into AI prompts

Knowledge base supports multiple embedding backends (sentence-transformers, TF-IDF).

## Configuration

### Environment Variables (.env)

```bash
# Database
DATABASE_URL=mysql+pymysql://user:pass@host:3306/fate

# JWT Authentication
JWT_SECRET=your-secret-key-here
JWT_EXPIRE_MINUTES=10080  # 7 days

# DeepSeek API (hardcoded in test files, should be externalized)
DEEPSEEK_API_KEY=sk-xxxxx

# WeChat Pay (production only)
WECHAT_PAY_MODE=prod  # or 'dev' for testing
WECHAT_API_V3_KEY=32-byte-key
WECHAT_PLATFORM_PUBLIC_KEY_PEM=...
```

### Key Settings (app/config.py)

- `db_pool_recycle=3600` - Recycle connections every hour
- `sqlalchemy_echo=False` - Set True for SQL debugging
- `wechat_pay_mode="dev"` - Controls payment webhook verification

## Development Notes

### Code Patterns

- **Dependency Injection**: FastAPI `Depends()` for database sessions
- **Service Layer Pattern**: Business logic in `app/services/`, routes just delegate
- **Time Zone Handling**: MySQL uses UTC; app converts to Asia/Shanghai for Bazi
- **Markdown Processing**: Aggressive normalization for frontend compatibility (app/chat/markdown_utils.py)

### Important Conventions

1. **System Prompts**: Stored in database (`app_config` table), not hardcoded
   - Key: `system_prompt` or fallback `rprompt`
   - Template variables: `{FOUR_PILLARS}`, `{DAYUN}`
   - Loaded via `_load_system_prompt_from_db()`

2. **Conversation State**: Currently in-memory (file-based cache in `app/chat/store.py`)
   - Each conversation has: pinned system prompt, message history, kb_index_dir
   - NOT persisted across restarts (planned migration to database)

3. **Markdown Rules**: System prompt enforces strict formatting
   - Only `###` and `####` headings allowed
   - No bold/italic/quote/hr syntax
   - Single newline between paragraphs
   - See `_append_md_rules()` in service.py

4. **Text Processing Pipeline** (order matters):
   ```python
   normalize_markdown()      # Basic cleanup
   _scrub_br_block()         # Replace <br/>\n\n with \n-
   _collapse_double_newlines()  # \n\n -> \n
   _third_sub()              # \n- - -> \n-
   ```

### Security Considerations

- JWT secrets must be changed in production
- Payment webhooks require signature verification (disabled in dev mode)
- SQL injection prevented by SQLAlchemy ORM
- Password hashing uses bcrypt
- Rate limiting should be added for SMS/login endpoints

### Known Issues & Todo

From `note.md` (development roadmap):
- Time picker accuracy issues
- Long text truncation in outputs
- Need mobile app (mini-program) version
- WeChat Pay integration testing needed
- Landing page and payment flow incomplete

## File Structure Notes

- `app/models/` - SQLAlchemy ORM models (user.py, chat.py, order.py)
- `app/routers/` - API route handlers (chat.py, bazi.py, users.py, etc.)
- `app/chat/` - Chat-specific: service.py, rag.py, deepseek_client.py, sse.py, store.py
- `app/schemas/` - Pydantic validation models
- `kb_files/` - Knowledge base source documents
- `kb_index/` - Processed knowledge base (do not edit manually)
- `migrations/` - Alembic database migration scripts
- `venv311/` - Python virtual environment (ignored by git)

## Testing

Test file located at `app/test/test_utils.py` - contains CLI-based interactive testing for:
- Geocoding (city to longitude/latitude)
- True solar time calculation
- Bazi chart calculation
- Knowledge base retrieval
- DeepSeek API integration

Run with: `python app/test/test_utils.py`

## Database Connection Troubleshooting

MySQL runs in Docker (from note.md):
```bash
docker run -d \
  --name mysql8.4 \
  -p 127.0.0.1:3306:3306 \
  -e MYSQL_ROOT_PASSWORD=turkey414 \
  -e TZ=Asia/Shanghai \
  -v mysql8-data:/var/lib/mysql \
  mysql:8.4 \
  --character-set-server=utf8mb4 \
  --collation-server=utf8mb4_0900_ai_ci
```

Common issues:
- Connection pool exhaustion → increase `db_pool_size`
- "MySQL has gone away" → check `db_pool_recycle` setting
- Timezone problems → ensure `db_time_zone` matches application
