#!/bin/sh
set -e
# Read Docker secrets into env vars before nginx's envsubst runs on config templates.
[ -f /run/secrets/openaip_api_key ] && export OPENAIP_API_KEY=$(cat /run/secrets/openaip_api_key)
exec /docker-entrypoint.sh "$@"
