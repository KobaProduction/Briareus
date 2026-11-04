FROM debian:bookworm-slim@sha256:99c0b25c46d0214d5a2091092e7908907dcaecd6a962cde0ac700acee222b6f3
RUN apt-get update && apt-get install -y --no-install-recommends chromium chromium-l10n fonts-liberation fonts-noto-color-emoji locales tzdata xvfb libgbm1 libgl1-mesa-dri supervisor nginx-light jq curl ca-certificates && sed -i 's/^# *ru_RU.UTF-8 UTF-8/ru_RU.UTF-8 UTF-8/' /etc/locale.gen && locale-gen && rm -rf /var/lib/apt/lists/*
ENV HOME=/browser DISPLAY=:99 LANG=ru_RU.UTF-8 LC_ALL=ru_RU.UTF-8 XDG_CONFIG_HOME=/browser/config XDG_CACHE_HOME=/browser/cache BREAKPAD_DUMP_LOCATION=/browser/crash TMPDIR=/tmp/briareus-browser-transfers
RUN mkdir -p /browser/profile /browser/config /browser/cache /browser/crash /tmp/briareus-browser-transfers /workspace && chown -R 1000:1000 /browser /tmp/briareus-browser-transfers /workspace
COPY supervisord.conf /etc/supervisor/supervisord.conf
COPY nginx.conf /etc/nginx/nginx.conf
COPY chromium-launch.sh /usr/local/bin/chromium-launch
RUN chmod 0755 /usr/local/bin/chromium-launch
USER 1000:1000
EXPOSE 9222 9001
ENTRYPOINT ["/usr/bin/supervisord", "-n", "-c", "/etc/supervisor/supervisord.conf"]
