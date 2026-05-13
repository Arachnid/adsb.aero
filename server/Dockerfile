FROM python:3.12-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends libeccodes0 \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
RUN pip install --no-cache-dir -e .

COPY adsb_server/ adsb_server/

ENV PYTHONUNBUFFERED=1
EXPOSE 8000

CMD ["uvicorn", "adsb_server.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
