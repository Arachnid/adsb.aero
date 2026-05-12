FROM mobilitydb/mobilitydb:17-3.5-1.3

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        postgresql-17-partman \
    && rm -rf /var/lib/apt/lists/*
