# Build context is the repository root (see docker-compose.yml), not backend/,
# so the image preserves the same backend/ nesting as local dev. app/db/duckdb.py
# resolves its data path relative to the repo root three parents up from itself;
# copying only backend/ into /app would collapse that path and silently break it.
FROM python:3.12-slim

WORKDIR /app/backend

COPY backend/ ./

RUN pip install --no-cache-dir -e ".[dev]"

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
