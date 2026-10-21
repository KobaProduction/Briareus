#!/usr/bin/env bash
# Adapted from ArthurKoba/infrastructure@45fe89a7ec441233010f07eb522393bdcd7f8b6d
set -Eeuo pipefail
IFS=$'\n\t'
umask 077

PROGRAM="briareus-node-bootstrap"

NODE_UUID="${BRIAREUS_NODE_UUID:?}"
RUNTIME_USER="${BRIAREUS_RUNTIME_USER:?}"
RUNTIME_UID="${BRIAREUS_RUNTIME_UID:?}"
RUNTIME_GID="${BRIAREUS_RUNTIME_GID:?}"
RUNTIME_SOCKET="/run/user/$RUNTIME_UID/docker.sock"
SUBID_SIZE=65536
SHARED_DIR="/var/lib/briareus/nodes/$NODE_UUID/workspaces"
EXEC_MEMORY="${BRIAREUS_EXECUTION_MEMORY_BYTES:?}"
EXEC_CPU="${BRIAREUS_EXECUTION_CPU_MILLIS:?}"
EXEC_PIDS="${BRIAREUS_EXECUTION_PIDS:?}"
TOOLING_MODE="${BRIAREUS_ROOTLESS_TOOLING:-packages}"
TOOLING_PATH="/usr/bin"
if [[ "$TOOLING_MODE" == static-28.3.2 ]]; then
  TOOLING_PATH=/opt/briareus/docker/28.3.2
fi

CURRENT_STAGE="startup"

log() { printf '[%s] %s\n' "$PROGRAM" "$*"; }
die() { printf '[%s] ERROR: %s\n' "$PROGRAM" "$*" >&2; return 1; }
stage() {
  CURRENT_STAGE="$1"
  log "stage: $CURRENT_STAGE"
}

on_error() {
  local rc="$?"
  printf '[%s] ERROR: stage=%s line=%s exit=%s\n' \
    "$PROGRAM" "$CURRENT_STAGE" "${BASH_LINENO[0]:-${LINENO}}" "$rc" >&2
  exit "$rc"
}

trap on_error ERR

runtime_home() {
  getent passwd "$RUNTIME_USER" | awk -F: '{print $6}'
}

as_runtime() {
  local home runtime_dir
  home="$(runtime_home)"
  runtime_dir="/run/user/$RUNTIME_UID"
  runuser -u "$RUNTIME_USER" -- env \
    HOME="$home" \
    USER="$RUNTIME_USER" \
    LOGNAME="$RUNTIME_USER" \
    XDG_RUNTIME_DIR="$runtime_dir" \
    PATH="$TOOLING_PATH:$home/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin" \
    "$@"
}

validate_contract() {
  cd /
  [[ ${EUID:-$(id -u)} -eq 0 ]] || die "host bootstrap must run as root"
  [[ "$(uname -s)" == "Linux" ]] || die "Linux is required"
  [[ "$RUNTIME_UID" =~ ^[0-9]+$ ]] || die "BRIAREUS_RUNTIME_UID must be numeric"
  [[ "$RUNTIME_GID" =~ ^[0-9]+$ ]] || die "BRIAREUS_RUNTIME_GID must be numeric"
  [[ "$RUNTIME_SOCKET" == "/run/user/$RUNTIME_UID/docker.sock" ]] || \
    die "BRIAREUS_RUNTIME_SOCKET must be /run/user/$RUNTIME_UID/docker.sock"
  [[ "$NODE_UUID" =~ ^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$ ]] || die "node UUIDv4 required"
  [[ "$RUNTIME_USER" == "briareus-${NODE_UUID:0:8}" ]] || die "runtime username must match node UUID prefix"
  (( RUNTIME_UID >= 2000 && RUNTIME_GID >= 2000 )) || die "dedicated uid/gid >=2000 required"
  [[ "$EXEC_MEMORY:$EXEC_CPU:$EXEC_PIDS" =~ ^[0-9]+:[0-9]+:[0-9]+$ ]] || die "numeric limits required"
  (( EXEC_MEMORY >= 134217728 && EXEC_CPU >= 100 && EXEC_PIDS >= 64 )) || die "execution limits below minimum"

  [[ -r /etc/os-release ]] || die "/etc/os-release is required"
  local os_id os_version
  os_id="$(. /etc/os-release; printf '%s' "${ID:-}")"
  os_version="$(. /etc/os-release; printf '%s' "${VERSION_ID:-}")"
  [[ "$os_id" == "ubuntu" && "$os_version" == "24.04" ]] || \
    die "only Ubuntu 24.04 is qualified (found ${os_id:-unknown} ${os_version:-unknown})"

  command -v systemctl >/dev/null 2>&1 || die "systemd is required"
  command -v loginctl >/dev/null 2>&1 || die "systemd-logind is required"
  command -v runuser >/dev/null 2>&1 || die "runuser is required"
  command -v dpkg-query >/dev/null 2>&1 || die "dpkg-query is required"
  [[ -e /sys/fs/cgroup/cgroup.controllers ]] || die "cgroup v2 unified hierarchy is required"
  case "$TOOLING_MODE" in
    packages) dpkg-query -W docker-ce >/dev/null 2>&1 || die "docker-ce host required for package tooling" ;;
    static-28.3.2) [[ $(uname -m) == x86_64 && -r /opt/briareus/static-tooling.sh ]] || die "Pinned static tooling installer required" ;;
    *) die "Unsupported rootless tooling mode" ;;
  esac
}

install_prerequisites() {
  if command -v newuidmap >/dev/null 2>&1 \
    && command -v newgidmap >/dev/null 2>&1 \
    && command -v slirp4netns >/dev/null 2>&1 \
    && command -v fuse-overlayfs >/dev/null 2>&1 \
    && command -v dbus-daemon >/dev/null 2>&1 \
    && command -v modprobe >/dev/null 2>&1 \
    && command -v iptables >/dev/null 2>&1; then
    return 0
  fi

  command -v apt-get >/dev/null 2>&1 || die "apt-get is required on qualified Ubuntu 24.04 hosts"
  log "installing Docker rootless prerequisites"
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq
  apt-get install -y --no-install-recommends \
    uidmap dbus-user-session slirp4netns fuse-overlayfs kmod iptables ca-certificates curl
}

ensure_runtime_identity() {
  local existing home groups group identity_dir identity_file expected
  identity_dir="/var/lib/briareus/runtime-identities"
  identity_file="$identity_dir/$RUNTIME_USER"
  expected="$NODE_UUID:$RUNTIME_UID:$RUNTIME_GID"
  [[ ! -L "$identity_dir" && ! -L "$identity_file" ]] || die "runtime identity marker must not be a symlink"
  install -d -o root -g root -m 0700 "$identity_dir"
  if [[ -e "$identity_file" ]]; then
    [[ -f "$identity_file" && "$(stat -c %u "$identity_file")" == "0" \
       && "$(stat -c %a "$identity_file")" == "600" \
       && "$(cat "$identity_file")" == "$expected" ]] || die "runtime identity belongs to another node"
  else
    ! id "$RUNTIME_USER" >/dev/null 2>&1 || die "refusing to adopt an unmarked host user"
    [[ -z "$(getent passwd "$RUNTIME_UID" || true)" \
       && -z "$(getent group "$RUNTIME_GID" || true)" ]] || die "runtime uid/gid already in use"
    (set -o noclobber; printf '%s\n' "$expected" > "$identity_file")
    chmod 0600 "$identity_file"
  fi
  if id "$RUNTIME_USER" >/dev/null 2>&1; then
    [[ "$(id -u "$RUNTIME_USER")" == "$RUNTIME_UID" ]] || \
      die "$RUNTIME_USER exists with uid $(id -u "$RUNTIME_USER"), expected $RUNTIME_UID"
    [[ "$(id -g "$RUNTIME_USER")" == "$RUNTIME_GID" ]] || \
      die "$RUNTIME_USER exists with gid $(id -g "$RUNTIME_USER"), expected $RUNTIME_GID"
  else
    existing="$(getent passwd "$RUNTIME_UID" | cut -d: -f1 || true)"
    [[ -z "$existing" ]] || die "uid $RUNTIME_UID already belongs to $existing"
    existing="$(getent group "$RUNTIME_GID" | cut -d: -f1 || true)"
    [[ -z "$existing" ]] || die "gid $RUNTIME_GID already belongs to $existing"

    log "creating dedicated runtime identity $RUNTIME_USER ($RUNTIME_UID:$RUNTIME_GID)"
    groupadd --gid "$RUNTIME_GID" "$RUNTIME_USER"
    useradd --uid "$RUNTIME_UID" --gid "$RUNTIME_GID" --create-home --shell /bin/bash "$RUNTIME_USER"
  fi

  passwd -l "$RUNTIME_USER" >/dev/null 2>&1 || true
  home="$(runtime_home)"
  [[ -n "$home" && "$home" != "/" ]] || die "$RUNTIME_USER has no usable home directory"
  install -d -o "$RUNTIME_UID" -g "$RUNTIME_GID" -m 0700 "$home"

  groups=" $(id -nG "$RUNTIME_USER") "
  for group in docker sudo wheel; do
    if getent group "$group" >/dev/null 2>&1 && [[ "$groups" == *" $group "* ]]; then
      log "removing forbidden group $group from $RUNTIME_USER"
      gpasswd -d "$RUNTIME_USER" "$group" >/dev/null
    fi
  done

  if command -v sudo >/dev/null 2>&1 && runuser -u "$RUNTIME_USER" -- sudo -n true >/dev/null 2>&1; then
    die "$RUNTIME_USER has passwordless sudo"
  fi
}

has_subid_range() {
  local file="$1"
  awk -F: -v u="$RUNTIME_USER" -v n="$SUBID_SIZE" \
    '$1 == u && $3 >= n { ok=1 } END { exit !ok }' "$file"
}

next_subid_start() {
  local file="$1"
  awk -F: -v n="$SUBID_SIZE" '
    BEGIN { max=231071 }
    NF >= 3 && $2 ~ /^[0-9]+$/ && $3 ~ /^[0-9]+$/ {
      end=$2+$3-1
      if (end > max) max=end
    }
    END {
      start=max+1
      rem=start % n
      if (rem != 0) start += n-rem
      print start
    }
  ' "$file"
}

ensure_subids() {
  local start end
  touch /etc/subuid /etc/subgid

  if ! has_subid_range /etc/subuid; then
    start="$(next_subid_start /etc/subuid)"
    end=$((start + SUBID_SIZE - 1))
    log "allocating subordinate uid range $start-$end"
    usermod --add-subuids "$start-$end" "$RUNTIME_USER"
  fi

  if ! has_subid_range /etc/subgid; then
    start="$(next_subid_start /etc/subgid)"
    end=$((start + SUBID_SIZE - 1))
    log "allocating subordinate gid range $start-$end"
    usermod --add-subgids "$start-$end" "$RUNTIME_USER"
  fi
}

ensure_kernel_userns() {
  local conf="/etc/sysctl.d/99-briareus-rootless-docker.conf"
  local current
  local lines=()

  if [[ -e /proc/sys/kernel/unprivileged_userns_clone ]]; then
    lines+=("kernel.unprivileged_userns_clone=1")
    if [[ "$(cat /proc/sys/kernel/unprivileged_userns_clone)" != "1" ]]; then
      sysctl -w kernel.unprivileged_userns_clone=1 >/dev/null
    fi
  fi

  if [[ -e /proc/sys/user/max_user_namespaces ]]; then
    current="$(cat /proc/sys/user/max_user_namespaces)"
    if (( current < 28633 )); then
      sysctl -w user.max_user_namespaces=28633 >/dev/null
      current=28633
    fi
    lines+=("user.max_user_namespaces=$current")
  fi

  if ((${#lines[@]})); then
    printf '%s\n' "${lines[@]}" > "$conf"
  fi
}

ensure_user_manager() {
  local runtime_dir="/run/user/$RUNTIME_UID"

  loginctl enable-linger "$RUNTIME_USER"
  if ! systemctl is-active --quiet "user@${RUNTIME_UID}.service"; then
    systemctl start "user@${RUNTIME_UID}.service"
  fi

  for _ in {1..40}; do
    if [[ -d "$runtime_dir" && "$(stat -c %u "$runtime_dir" 2>/dev/null || true)" == "$RUNTIME_UID" ]] \
      && [[ -S "$runtime_dir/systemd/private" ]] \
      && as_runtime systemctl --user show-environment >/dev/null 2>&1; then
      return 0
    fi
    sleep 0.5
  done
  die "systemd user manager is not usable for $RUNTIME_USER at $runtime_dir"
}

rootless_setup_tool() {
  local home candidate
  home="$(runtime_home)"
  if [[ "$TOOLING_MODE" == static-28.3.2 ]]; then
    [[ -x "$TOOLING_PATH/dockerd-rootless-setuptool.sh" ]] || return 1
    printf '%s' "$TOOLING_PATH/dockerd-rootless-setuptool.sh"
    return
  fi
  candidate="$(command -v dockerd-rootless-setuptool.sh || true)"
  if [[ -n "$candidate" && -x "$candidate" ]]; then
    printf '%s' "$candidate"
    return 0
  fi
  candidate="$home/bin/dockerd-rootless-setuptool.sh"
  [[ -x "$candidate" ]] || return 1
  printf '%s' "$candidate"
}

docker_ce_package_version() {
  dpkg-query -W -f='${Version}' docker-ce 2>/dev/null || return 1
}

rootless_extras_package_version() {
  dpkg-query -W -f='${Version}' docker-ce-rootless-extras 2>/dev/null || return 1
}

install_rootless_extras_package() {
  local docker_ce_version
  docker_ce_version="$(docker_ce_package_version)" || \
    die "qualified host must use the docker-ce package so rootless extras can be pinned to the running Docker release"

  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq
  apt-get install -y --no-install-recommends "docker-ce-rootless-extras=$docker_ce_version"
}

ensure_rootless_tooling() {
  local docker_ce_version extras_version
  if [[ "$TOOLING_MODE" == static-28.3.2 ]]; then
    source /opt/briareus/static-tooling.sh
    install_static_tooling
    return
  fi
  docker_ce_version="$(docker_ce_package_version)" || \
    die "docker-ce package is not installed on this qualified host"
  extras_version="$(rootless_extras_package_version || true)"

  if [[ "$extras_version" != "$docker_ce_version" ]]; then
    log "installing docker-ce-rootless-extras matching docker-ce $docker_ce_version"
    install_rootless_extras_package || \
      die "matching docker-ce-rootless-extras $docker_ce_version is unavailable from the configured Docker repository"
  fi

  rootless_setup_tool >/dev/null 2>&1 || \
    die "dockerd-rootless-setuptool.sh is unavailable after installing docker-ce-rootless-extras"
}

ensure_rootlesskit_compat() {
  local home rootlesskit output id version filename profile
  home="$(runtime_home)"
  rootlesskit="$TOOLING_PATH/rootlesskit"
  [[ -x "$rootlesskit" ]] || rootlesskit="$(command -v rootlesskit || true)"
  [[ -n "$rootlesskit" ]] || rootlesskit="$home/bin/rootlesskit"
  [[ -x "$rootlesskit" ]] || die "rootlesskit is unavailable"

  if output="$(as_runtime "$rootlesskit" true 2>&1)"; then
    return 0
  fi

  [[ -r /etc/os-release ]] || die "rootlesskit self-test failed: ${output%%$'\n'*}"
  id="$(. /etc/os-release; printf '%s' "${ID:-}")"
  version="$(. /etc/os-release; printf '%s' "${VERSION_ID:-}")"

  if [[ "$id" == "ubuntu" ]] && command -v dpkg >/dev/null 2>&1 \
    && dpkg --compare-versions "$version" ge 24.04; then
    if ! command -v apparmor_parser >/dev/null 2>&1; then
      export DEBIAN_FRONTEND=noninteractive
      apt-get update -qq
      apt-get install -y --no-install-recommends apparmor
    fi

    filename="$(printf '%s' "$rootlesskit" | sed -e 's@^/@@' -e 's@/@.@g')"
    profile="/etc/apparmor.d/$filename"
    log "installing AppArmor userns profile for $rootlesskit"
    cat > "$profile" <<EOF_APPARMOR
abi <abi/4.0>,
include <tunables/global>

"$rootlesskit" flags=(unconfined) {
  userns,

  include if exists <local/$filename>
}
EOF_APPARMOR
    apparmor_parser -r "$profile"

    if output="$(as_runtime "$rootlesskit" true 2>&1)"; then
      return 0
    fi
  fi

  die "rootlesskit self-test failed: ${output%%$'\n'*}"
}

ensure_netfilter_modules() {
  local conf="/etc/modules-load.d/99-briareus-rootless-docker.conf"
  local module
  local modules=(ip_tables iptable_mangle iptable_nat iptable_filter)

  printf '%s\n' "${modules[@]}" > "$conf"
  for module in "${modules[@]}"; do
    modprobe "$module" || die "failed to load required rootless Docker module $module"
  done
}

prepare_socket_path() {
  local socket="$RUNTIME_SOCKET"

  if [[ -d "$socket" ]]; then
    if [[ -n "$(find "$socket" -mindepth 1 -maxdepth 1 -print -quit 2>/dev/null)" ]]; then
      die "socket path $socket is a non-empty directory; refusing to remove it"
    fi
    log "removing stale directory at socket path $socket"
    rmdir "$socket"
  fi

  if [[ -e "$socket" && ! -S "$socket" ]]; then
    die "socket path $socket exists but is not a Unix socket"
  fi
}

dump_rootless_diagnostics() {
  log "rootless Docker diagnostics begin"
  as_runtime systemctl --user status docker.service --no-pager --full || true
  as_runtime journalctl --user --unit docker.service -n 100 --no-pager || true
  journalctl -k -n 160 --no-pager 2>/dev/null \
    | grep -Ei 'apparmor|denied|rootlesskit|userns|docker|iptables' \
    | tail -n 100 || true
  log "rootless Docker diagnostics end"
}

verify_rootless_docker() {
  local security root_dir cgroup_version cgroup_driver controllers controller socket_meta socket_mode

  [[ -S "$RUNTIME_SOCKET" ]] || die "rootless Docker socket is missing at $RUNTIME_SOCKET"
  as_runtime systemctl --user is-active --quiet docker.service || die "rootless docker.service is not active"

  security="$(as_runtime env DOCKER_HOST="unix://$RUNTIME_SOCKET" docker info --format '{{json .SecurityOptions}}')" \
    || { dump_rootless_diagnostics; die "docker info failed as $RUNTIME_USER"; }
  [[ "$security" == *rootless* ]] || die "Docker daemon at $RUNTIME_SOCKET did not report rootless mode"

  cgroup_version="$(as_runtime env DOCKER_HOST="unix://$RUNTIME_SOCKET" docker info --format '{{.CgroupVersion}}')"
  [[ "$cgroup_version" == "2" ]] || die "rootless Docker is not using cgroup v2"

  cgroup_driver="$(as_runtime env DOCKER_HOST="unix://$RUNTIME_SOCKET" docker info --format '{{.CgroupDriver}}')"
  [[ "$cgroup_driver" == "systemd" ]] || die "rootless Docker cgroup driver is $cgroup_driver, expected systemd"

  controllers="$(cat "/sys/fs/cgroup/user.slice/user-${RUNTIME_UID}.slice/user@${RUNTIME_UID}.service/cgroup.controllers" 2>/dev/null || true)"
  for controller in cpu cpuset io memory pids; do
    [[ " $controllers " == *" $controller "* ]] || \
      die "cgroup controller $controller is not delegated to user@${RUNTIME_UID}.service"
  done

  root_dir="$(as_runtime env DOCKER_HOST="unix://$RUNTIME_SOCKET" docker info --format '{{.DockerRootDir}}')"
  [[ "$root_dir" != "/var/lib/docker" ]] || die "rootless Docker is using the rootful data directory"

  [[ "$(stat -c %u "$RUNTIME_SOCKET")" == "$RUNTIME_UID" ]] || \
    die "rootless Docker socket owner is not runtime uid $RUNTIME_UID"
  socket_mode="$(stat -c %a "$RUNTIME_SOCKET")"
  (( (8#$socket_mode & 0600) == 0600 )) || \
    die "rootless Docker socket does not grant read/write access to its owner"

  socket_meta="$(stat -c 'uid=%u gid=%g mode=%a' "$RUNTIME_SOCKET")"
  log "rootless Docker accepted ($socket_meta, data-root=$root_dir, cgroup-driver=$cgroup_driver)"
}

ensure_cgroup_delegation() {
  local dir="/etc/systemd/system/user@${RUNTIME_UID}.service.d"
  local file="$dir/briareus-node-delegate.conf"
  local legacy="$dir/briareus-node-legacy-delegate.conf"
  local expected
  local changed=0
  expected=$'[Service]\nDelegate=cpu cpuset io memory pids\n'

  install -d -m 0755 "$dir"

  if [[ -f "$legacy" ]]; then
    if [[ "$(cat "$legacy")"$'\n' != "$expected" ]]; then
      die "legacy cgroup delegation file $legacy has unexpected content"
    fi
    rm -f "$legacy"
    changed=1
  fi

  if [[ ! -f "$file" || "$(cat "$file")"$'\n' != "$expected" ]]; then
    printf '%s' "$expected" > "$file"
    chmod 0644 "$file"
    changed=1
  fi

  if ((changed)); then
    log "applying rootless Docker cgroup delegation"
    systemctl daemon-reload
    if systemctl is-active --quiet "user@${RUNTIME_UID}.service"; then
      systemctl restart "user@${RUNTIME_UID}.service"
    fi
  fi
}

ensure_rootless_docker() {
  local home setup_tool
  home="$(runtime_home)"
  setup_tool="$(rootless_setup_tool)"

  ensure_netfilter_modules
  prepare_socket_path

  if [[ ! -f "$home/.config/systemd/user/docker.service" ]]; then
    log "installing rootless Docker user service for $RUNTIME_USER"
    if ! as_runtime "$setup_tool" install --force; then
      dump_rootless_diagnostics
      die "dockerd-rootless-setuptool.sh could not install/start docker.service"
    fi
  fi

  as_runtime systemctl --user enable docker.service >/dev/null
  if ! as_runtime systemctl --user is-active --quiet docker.service; then
    log "starting rootless Docker user service for $RUNTIME_USER"
    if ! as_runtime systemctl --user start docker.service; then
      dump_rootless_diagnostics
      die "rootless docker.service failed to start"
    fi
  fi

  for _ in {1..60}; do
    [[ -S "$RUNTIME_SOCKET" ]] && break
    sleep 0.5
  done
  verify_rootless_docker
}

assert_no_native_agent() {
  if systemctl cat briareus-node-agent.service >/dev/null 2>&1; then
    die "native briareus-node-agent.service exists; clean-install contract requires no native agent"
  fi
}

ensure_shared_dir() {
  local dir root_owner
  local layout=("$SHARED_DIR" "/var/lib/briareus/nodes/$NODE_UUID/gateway")

  if [[ -e "$SHARED_DIR" && ! -d "$SHARED_DIR" ]]; then
    die "$SHARED_DIR exists but is not a directory"
  fi

  for dir in "${layout[@]}"; do
    [[ ! -L "$dir" ]] || die "node data directory must not be a symlink"
    if [[ ! -d "$dir" ]]; then
      install -d -o "$RUNTIME_UID" -g "$RUNTIME_GID" -m 0700 "$dir"
    fi
    [[ "$(stat -c '%u:%g:%a' "$dir")" == "$RUNTIME_UID:$RUNTIME_GID:700" ]] || \
      die "node data directory must be owner-private"
  done

  root_owner="$(stat -c '%u:%g' "$SHARED_DIR")"
  [[ "$root_owner" == "$RUNTIME_UID:$RUNTIME_GID" ]] || \
    die "$SHARED_DIR is owned by $root_owner, expected $RUNTIME_UID:$RUNTIME_GID"
}

ensure_execution_budget() {
  local quota dir file expected
  quota="$(awk -v m="$EXEC_CPU" 'BEGIN { printf "%.2f%%", m / 10 }')"
  dir="/etc/systemd/system/user-${RUNTIME_UID}.slice.d"
  file="$dir/briareus-node-budget.conf"
  printf -v expected '[Slice]\nCPUAccounting=yes\nMemoryAccounting=yes\nTasksAccounting=yes\nCPUQuota=%s\nMemoryMax=%s\nMemorySwapMax=0\nTasksMax=%s\n' "$quota" "$EXEC_MEMORY" "$EXEC_PIDS"
  install -d -m 0755 "$dir"
  if [[ ! -f "$file" || "$(cat "$file")"$'\n' != "$expected" ]]; then
    printf '%s' "$expected" > "$file"
    chmod 0644 "$file"
    systemctl daemon-reload
  fi
  systemctl set-property --runtime "user-${RUNTIME_UID}.slice" \
    "CPUQuota=$quota" "MemoryMax=$EXEC_MEMORY" "MemorySwapMax=0" "TasksMax=$EXEC_PIDS"
}

main() {
  stage "validate contract"
  validate_contract
  stage "install prerequisites"
  install_prerequisites
  stage "runtime identity"
  ensure_runtime_identity
  stage "subordinate id ranges"
  ensure_subids
  stage "kernel user namespaces"
  ensure_kernel_userns
  stage "rootless cgroup delegation"
  ensure_cgroup_delegation
  stage "systemd user manager"
  ensure_user_manager
  stage "node execution budget"
  ensure_execution_budget
  stage "rootless Docker tooling"
  ensure_rootless_tooling
  stage "rootlesskit compatibility"
  ensure_rootlesskit_compat
  stage "rootless Docker daemon"
  ensure_rootless_docker
  stage "project workspace root"
  ensure_shared_dir
  stage "native agent conflict check"
  assert_no_native_agent

  CURRENT_STAGE="accepted"
  log "bootstrap accepted: rootless Docker is ready for the Briareus node controller"
}

if [[ "${KOBA_BOOTSTRAP_LIBRARY_ONLY:-0}" != "1" ]]; then
  main "$@"
fi
