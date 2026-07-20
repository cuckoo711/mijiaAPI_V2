#!/bin/sh
set -e

if [ "$(id -u)" = "0" ]; then
    mkdir -p /data/server /data/cache
    chown -R mijia:mijia /data
    exec gosu mijia:mijia "$@"
fi

exec "$@"
