FROM python:3.12-slim

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Place the venv outside /app so a bind-mount of /app doesn't clobber it
ENV UV_PROJECT_ENVIRONMENT=/opt/venv

# Install dependencies (cached layer)
COPY pyproject.toml .
RUN uv sync --no-dev

# Download spaCy model
RUN uv run python -m spacy download en_core_web_sm

COPY . .

CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
