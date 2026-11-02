#!/usr/bin/env bash
# Official Docker static distribution, pinned for local hosts without docker-ce.
# No rootful daemon/service/package is installed or enabled.
set -Eeuo pipefail

STATIC_VERSION=28.3.2
STATIC_DIR=/opt/briareus/docker/28.3.2
DOCKER_SHA=9d274a3f330764ebd9cc82fe29e5dd5d0569bc34f9f53e3ac8905444cd88b413
ROOTLESS_SHA=a5450ae88f4195d57decca52eca3ad726fff19ed8c280c5813c3a6689c471f07

install_static_tooling() {
  [[ $(uname -m) == x86_64 ]] || die "Pinned static distribution currently supports x86_64 only"
  local temporary file
  if [[ -d "$STATIC_DIR" ]]; then
    [[ ! -L "$STATIC_DIR" && -f "$STATIC_DIR/.briareus-static" \
      && "$(stat -c '%u:%g:%a' "$STATIC_DIR")" == "0:0:755" \
      && "$(cat "$STATIC_DIR/.briareus-static")" == "$DOCKER_SHA:$ROOTLESS_SHA" ]] || \
      die "Refusing conflicting static Docker installation"
    (cd "$STATIC_DIR" && sha256sum --check --status .briareus-checksums) || die "Static Docker files changed"
    return
  fi
  temporary=$(mktemp -d /var/tmp/briareus-docker.XXXXXX)
  chmod 0700 "$temporary"
  (
    trap 'rm -rf -- "$temporary"' EXIT
    wget --https-only --secure-protocol=TLSv1_2 --timeout=120 --tries=1 --quiet --show-progress \
      "https://download.docker.com/linux/static/stable/x86_64/docker-$STATIC_VERSION.tgz" -O "$temporary/docker.tgz"
    wget --https-only --secure-protocol=TLSv1_2 --timeout=120 --tries=1 --quiet --show-progress \
      "https://download.docker.com/linux/static/stable/x86_64/docker-rootless-extras-$STATIC_VERSION.tgz" -O "$temporary/rootless.tgz"
    printf '%s  %s\n%s  %s\n' "$DOCKER_SHA" "$temporary/docker.tgz" "$ROOTLESS_SHA" "$temporary/rootless.tgz" | sha256sum --check --status
    mkdir "$temporary/bin"
    tar -xzf "$temporary/docker.tgz" --strip-components=1 --no-same-owner -C "$temporary/bin"
    tar -xzf "$temporary/rootless.tgz" --strip-components=1 --no-same-owner -C "$temporary/bin"
    for file in "$temporary/bin/"*; do
      [[ -f "$file" && ! -L "$file" ]] || exit 1
      chmod 0755 "$file"
    done
    (cd "$temporary/bin" && sha256sum ./* > .briareus-checksums)
    printf '%s:%s\n' "$DOCKER_SHA" "$ROOTLESS_SHA" > "$temporary/bin/.briareus-static"
    chmod 0644 "$temporary/bin/.briareus-checksums" "$temporary/bin/.briareus-static"
    install -d -o root -g root -m 0755 /opt/briareus/docker
    chmod 0755 "$temporary/bin"
    mv -T "$temporary/bin" "$STATIC_DIR"
  )
}
