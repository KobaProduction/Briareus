ARG BRI_RUNTIME_BASE=bri-v1-runtime-base:local
FROM ${BRI_RUNTIME_BASE}
USER root
RUN apt-get update && apt-get install -y --no-install-recommends chromium chromium-l10n fonts-liberation fonts-noto-color-emoji locales tzdata xvfb libgbm1 libgl1-mesa-dri && sed -i 's/^# *ru_RU.UTF-8 UTF-8/ru_RU.UTF-8 UTF-8/' /etc/locale.gen && locale-gen && rm -rf /var/lib/apt/lists/*
COPY src/browser_runtime/__init__.py /app/src/browser_runtime/__init__.py
COPY src/browser_runtime/application.py /app/src/browser_runtime/application.py
COPY src/browser_runtime/configuration.py /app/src/browser_runtime/configuration.py
COPY src/browser_runtime/process.py /app/src/browser_runtime/process.py
COPY src/browser_runtime/runtime.py /app/src/browser_runtime/runtime.py
COPY src/common/__init__.py /app/src/common/__init__.py
COPY src/common/asgi.py /app/src/common/asgi.py
COPY src/common/browser_extensions.py /app/src/common/browser_extensions.py
COPY src/common/browser_profile.py /app/src/common/browser_profile.py
COPY src/common/settings.py /app/src/common/settings.py
COPY src/common/websocket_proxy.py /app/src/common/websocket_proxy.py
ENV ASGI_APP=browser_runtime.runtime:app
ENV ASGI_PORT=9222
ENV XDG_CONFIG_HOME=/browser/config XDG_CACHE_HOME=/browser/cache BREAKPAD_DUMP_LOCATION=/browser/crash
RUN mkdir -p /tmp/bri-browser-transfers && chown 1000:1000 /tmp/bri-browser-transfers
