#!/usr/bin/env sh
# Install Docker Engine + the compose plugin on THIS VM, then enable the daemon
# and let your user run docker without sudo. Uses Docker's official convenience
# script (get.docker.com), which supports Ubuntu/Debian/Fedora/CentOS/RHEL and
# most systemd distros. Safe to re-run.
set -eu

# Figure out how to elevate.
if [ "$(id -u)" = "0" ]; then
  SUDO=""
elif command -v sudo >/dev/null 2>&1; then
  SUDO="sudo"
else
  echo "ERROR: this needs root. Re-run as root, or install sudo first." >&2
  exit 1
fi

# Already good? (compose version does not need the daemon, so no sudo needed.)
if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  echo "Docker + compose plugin already installed:"
  docker --version
  docker compose version
  exit 0
fi

echo "==> Downloading Docker's official install script..."
if command -v curl >/dev/null 2>&1; then
  curl -fsSL https://get.docker.com -o /tmp/get-docker.sh
elif command -v wget >/dev/null 2>&1; then
  wget -qO /tmp/get-docker.sh https://get.docker.com
else
  echo "ERROR: need curl or wget to download the installer." >&2
  exit 1
fi

echo "==> Installing Docker Engine + compose plugin (via get.docker.com)..."
$SUDO sh /tmp/get-docker.sh
rm -f /tmp/get-docker.sh

echo "==> Enabling and starting the Docker daemon..."
if command -v systemctl >/dev/null 2>&1; then
  $SUDO systemctl enable --now docker || true
fi

# Let the invoking (non-root) user use docker without sudo.
TARGET_USER="${SUDO_USER:-$(id -un)}"
if [ "$TARGET_USER" != "root" ]; then
  echo "==> Adding '$TARGET_USER' to the docker group (effective on next login)..."
  $SUDO usermod -aG docker "$TARGET_USER" || true
fi

echo "==> Installed:"
docker --version
$SUDO docker compose version

cat <<'EOF'

Done. Next steps:
  1. Log out and back in (or run:  newgrp docker) so you can use docker without sudo.
  2. Deploy:                        ./scripts/deploy.sh
     ...or deploy now without re-login, using root:   sudo ./scripts/deploy.sh

If get.docker.com reported your distro is unsupported, tell me the output of
`cat /etc/os-release` and I'll give you distro-specific steps.
EOF
