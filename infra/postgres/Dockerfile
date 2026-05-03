FROM postgis/postgis:17-3.5

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        postgresql-17-partman \
    && rm -rf /var/lib/apt/lists/*
