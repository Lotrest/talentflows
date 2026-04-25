# Applai API — FastAPI Backend

## Быстрый старт

### 1. Зависимости

```bash
cd packages/api
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Mac/Linux:
source .venv/bin/activate

pip install -r requirements.txt
```

### 2. Переменные окружения

```bash
cp .env.example .env
# Заполни:
# - либо DATABASE_URL
# - либо POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_HOST, POSTGRES_PORT, POSTGRES_DB
# и также: REDIS_URL, HH_CLIENT_ID, HH_CLIENT_SECRET, ANTHROPIC_API_KEY
```

### 3. База данных (PostgreSQL + Redis)

Самый простой способ — Docker:

```bash
docker run -d --name applai-pg -e POSTGRES_USER=postgres -e POSTGRES_PASSWORD=1234 -e POSTGRES_DB=postgres -p 5432:5432 postgres:16
docker run -d --name applai-redis -p 6379:6379 redis:7
```

### 4. Миграции

```bash
alembic upgrade head
```

### 5. Запуск

```bash
uvicorn app.main:app --reload --port 8000
```

API доступен на `http://localhost:8000`
Документация: `http://localhost:8000/docs`

---

## HH.ru OAuth

1. Зарегистрируй приложение на [dev.hh.ru](https://dev.hh.ru/applications)
2. Redirect URI: `http://localhost:8000/api/v1/auth/hh/callback`
3. Вставь `HH_CLIENT_ID` и `HH_CLIENT_SECRET` в `.env`

---

## Структура

```
app/
├── main.py              # FastAPI app + CORS + lifespan
├── core/
│   ├── config.py        # Settings из .env
│   ├── database.py      # SQLAlchemy async engine
│   ├── redis.py         # Redis connection
│   └── security.py      # JWT
├── models/              # SQLAlchemy ORM models
├── schemas/             # Pydantic v2 schemas
├── services/
│   ├── hh_client.py     # HH.ru API wrapper
│   ├── claude_service.py # Claude API: scoring + letters + replies
│   └── rate_limiter.py  # Redis-based rate limiting
└── api/v1/
    ├── auth.py          # HH.ru OAuth flow
    ├── profile.py       # Профиль пользователя
    ├── vacancies.py     # Поиск + AI scoring
    ├── applications.py  # Отклики + письма + диалоги
    └── analytics.py     # Статистика
```
