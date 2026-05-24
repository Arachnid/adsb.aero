FROM python:3.14-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends libeccodes0 libexpat1 \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
RUN pip install --no-cache-dir -e .

COPY adsb_server/ adsb_server/
COPY alembic.ini .
COPY alembic/ alembic/

ENV PYTHONUNBUFFERED=1 PYTHONPATH=/app
EXPOSE 8000

CMD ["uvicorn", "adsb_server.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
