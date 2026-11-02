ARG BRI_RUNTIME_BASE=bri-v1-runtime-base:local
FROM ${BRI_RUNTIME_BASE}
USER root
RUN apt-get update && apt-get install -y --no-install-recommends bash build-essential sed git git-lfs gh openssh-client wget ripgrep findutils patch diffutils rsync jq tar zip unzip gzip bzip2 xz-utils make gcc g++ binutils cmake ninja-build pkg-config ccache autoconf automake libtool python3-venv bc bison flex gawk gettext cpio file perl which libncurses-dev procps psmisc lsof strace gdb iproute2 socat netcat-openbsd util-linux picocom python3-serial && rm -rf /var/lib/apt/lists/*
COPY src/common/__init__.py /app/src/common/__init__.py
COPY src/common/account_contracts.py /app/src/common/account_contracts.py
COPY src/common/asgi.py /app/src/common/asgi.py
COPY src/common/audit_payloads.py /app/src/common/audit_payloads.py
COPY src/common/cache.py /app/src/common/cache.py
COPY src/common/control_panel_client.py /app/src/common/control_panel_client.py
COPY src/common/http_transport.py /app/src/common/http_transport.py
COPY src/common/models.py /app/src/common/models.py
COPY src/common/oauth_session_contracts.py /app/src/common/oauth_session_contracts.py
COPY src/common/observability.py /app/src/common/observability.py
COPY src/common/runtime_annotations.py /app/src/common/runtime_annotations.py
COPY src/common/runtime_common.py /app/src/common/runtime_common.py
COPY src/common/runtime_policy_contracts.py /app/src/common/runtime_policy_contracts.py
COPY src/common/settings.py /app/src/common/settings.py
COPY src/common/tool_observability.py /app/src/common/tool_observability.py
COPY src/modules/__init__.py /app/src/modules/__init__.py
COPY src/modules/terminal/__init__.py /app/src/modules/terminal/__init__.py
COPY src/modules/terminal/manager.py /app/src/modules/terminal/manager.py
COPY src/modules/terminal/runtime.py /app/src/modules/terminal/runtime.py
COPY src/modules/terminal/tools.py /app/src/modules/terminal/tools.py
ENV ASGI_APP=modules.terminal.runtime:app
