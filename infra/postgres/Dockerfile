FROM mobilitydb/mobilitydb:17-3.5-1.3

# The base image is Debian bullseye, which is EOL: its security suite's InRelease
# file has expired, so a plain `apt-get update` exits 100. The two packages below
# come from apt.postgresql.org, so drop the security source rather than build
# against an archive that is no longer re-signed.
RUN find /etc/apt -name '*.list' -exec sed -i '/-security/d' {} + \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        postgresql-17-partman \
        postgresql-17-h3 \
    && rm -rf /var/lib/apt/lists/*
