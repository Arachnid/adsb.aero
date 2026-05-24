#!/bin/sh
set -e
SENTRY_DSN=$(cat /run/secrets/sentry_dsn 2>/dev/null | tr -d '[:space:]')
sed "s|__SENTRY_DSN__|${SENTRY_DSN}|g" /etc/ofelia/config.ini.template > /tmp/ofelia.ini
exec /usr/bin/ofelia daemon --config=/tmp/ofelia.ini
