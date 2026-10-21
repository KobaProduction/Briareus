#!/bin/sh
set -eu

# Trusted, short-lived host setup only. No HTTP server or Docker socket.
uid="${BRIAREUS_RUNTIME_UID:?}"
gid="${BRIAREUS_RUNTIME_GID:?}"
case "$uid:$gid" in *[!0-9:]*|:*|*:) echo 'Numeric UID/GID required' >&2; exit 1;; esac
[ "$uid" -ge 2000 ] && [ "$gid" -ge 2000 ] || exit 1
state=/bootstrap/node-state
[ -d "$state" ] && [ ! -L "$state" ] || exit 1
if [ "$(stat -c '%u:%g' "$state")" != "$uid:$gid" ]; then
  [ -z "$(find "$state" -mindepth 1 -maxdepth 1 -print -quit)" ] || {
    echo 'Refusing implicit migration of foreign-owned node state' >&2; exit 1;
  }
  chown "$uid:$gid" "$state"
fi
chmod 0700 "$state"
[ -r /proc/1/ns/mnt ] || exit 1
exec nsenter --target 1 --mount --uts --ipc --net --pid --cgroup -- \
  /bin/bash -s < /opt/briareus/host-bootstrap.sh
