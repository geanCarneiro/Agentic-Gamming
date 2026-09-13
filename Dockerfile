FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml .
COPY src ./src
COPY game-packs ./game-packs
COPY web ./web

RUN pip install --upgrade pip \
    && pip install .

EXPOSE 8000

CMD ["uvicorn", "agentic_gaming.main:app", "--host", "0.0.0.0", "--port", "8000"]
