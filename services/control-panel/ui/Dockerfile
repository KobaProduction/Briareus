FROM oven/bun:1.4.2-alpine AS build

WORKDIR /app

COPY package.json bun.lock ./
RUN bun install --frozen-lockfile

COPY . ./
RUN bun run build


FROM nginx:1.28-alpine

ENV CONTROL_PANEL_UI_PREVIEW=false \
    CONTROL_PANEL_UI_TELEMETRY_ENABLED=true \
    CONTROL_PANEL_UI_TELEMETRY_ENDPOINT=/api/telemetry \
    CONTROL_PANEL_UI_TELEMETRY_SAMPLE_RATE=1 \
    CONTROL_PANEL_UI_EVENTS_MODE=hybrid \
    CONTROL_PANEL_UI_EVENTS_URL=/api/realtime

COPY nginx.conf.template /etc/nginx/templates/default.conf.template
COPY runtime-config.template.js /usr/share/nginx/html/runtime-config.template.js
COPY docker-entrypoint.d/50-control-panel-ui-runtime-config.sh /docker-entrypoint.d/50-control-panel-ui-runtime-config.sh
COPY --from=build /app/dist /usr/share/nginx/html

RUN chmod 0755 /docker-entrypoint.d/50-control-panel-ui-runtime-config.sh

EXPOSE 8080

HEALTHCHECK --interval=2s --timeout=1s --start-period=1s --retries=10 \
    CMD ["wget", "-q", "-O", "-", "http://127.0.0.1:8080/health"]
