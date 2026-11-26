#!/bin/sh
set -eu

# Named volumes may predate the non-root image user. Repair ownership without
# deleting cached models, uploads, or any other persisted data, then drop root.
if [ "$(id -u)" = "0" ]; then
    mkdir -p /app/uploads /app/model-cache
    chown -R finassist:finassist /app/uploads /app/model-cache
    exec gosu finassist "$@"
fi

exec "$@"
