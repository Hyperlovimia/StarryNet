#!/usr/bin/env bash

# installation script for Ubuntu, Debian and CentOS
# author: Yangtao Deng

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${VENV_DIR:-"$SCRIPT_DIR/.venv"}"

DIST=Unknown
CODENAME=Unknown
ARCH="$(uname -m)"
if [ "$ARCH" = "x86_64" ]; then ARCH="amd64"; fi
if [ "$ARCH" = "i686" ]; then ARCH="i386"; fi
if [ "$ARCH" = "aarch64" ]; then ARCH="arm64"; fi

if [ -r /etc/os-release ]; then
    . /etc/os-release
    DIST="${ID:-Unknown}"
    CODENAME="${VERSION_CODENAME:-}"
fi

install_debian_docker_repo() {
    if [ -z "$CODENAME" ]; then
        CODENAME="$(lsb_release -cs)"
    fi

    echo "Configuring Docker apt repository"
    sudo install -m 0755 -d /etc/apt/keyrings
    sudo rm -f /etc/apt/keyrings/docker.gpg
    curl -fsSL "https://download.docker.com/linux/$DIST/gpg" |
        sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    sudo chmod a+r /etc/apt/keyrings/docker.gpg

    echo "deb [arch=$ARCH signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/$DIST $CODENAME stable" |
        sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
    sudo DEBIAN_FRONTEND=noninteractive apt-get update
}

install_debian_dependencies() {
    echo "Installing apt dependencies"
    sudo DEBIAN_FRONTEND=noninteractive apt-get update
    sudo DEBIAN_FRONTEND=noninteractive apt-get -y -q install \
        ca-certificates \
        curl \
        gnupg \
        lsb-release \
        python3 \
        python3-pip \
        python3-setuptools \
        python3-venv

    if command -v docker >/dev/null 2>&1; then
        echo "Docker is already installed"
    else
        install_debian_docker_repo
        sudo DEBIAN_FRONTEND=noninteractive apt-get -y -q install \
            containerd.io \
            docker-buildx-plugin \
            docker-ce \
            docker-ce-cli \
            docker-compose-plugin
    fi
}

install_rpm_dependencies() {
    echo "Installing yum dependencies"
    sudo yum -y install python3 python3-pip python3-setuptools yum-utils

    if ! command -v docker >/dev/null 2>&1; then
        local docker_dist="centos"
        if [ "$DIST" = "fedora" ]; then
            docker_dist="fedora"
        fi

        echo "Configuring Docker yum repository"
        sudo yum-config-manager --add-repo "https://download.docker.com/linux/$docker_dist/docker-ce.repo"
    fi

    if command -v docker >/dev/null 2>&1; then
        echo "Docker is already installed"
    else
        sudo yum -y install containerd.io docker-ce docker-ce-cli docker-buildx-plugin docker-compose-plugin
    fi
}

case "$DIST" in
    ubuntu|debian)
        install_debian_dependencies
        ;;
    centos|rhel|fedora)
        install_rpm_dependencies
        ;;
    *)
        echo "Unsupported Linux distribution: $DIST" >&2
        exit 1
        ;;
esac

echo "Installing Python dependencies into $VENV_DIR"
sudo rm -rf "$SCRIPT_DIR/build" "$SCRIPT_DIR/starrynet.egg-info"
python3 -m venv "$VENV_DIR"
"$VENV_DIR/bin/python" -m pip install --upgrade pip setuptools wheel
"$VENV_DIR/bin/python" -m pip install -r "$SCRIPT_DIR/tools/requirements.txt"
"$VENV_DIR/bin/python" -m pip install "$SCRIPT_DIR"

SN_BIN_ESCAPED="$(printf '%q' "$VENV_DIR/bin/sn")"
sudo tee /usr/local/bin/sn >/dev/null <<EOF
#!/usr/bin/env bash
exec $SN_BIN_ESCAPED "\$@"
EOF
sudo chmod 0755 /usr/local/bin/sn
echo "Installed sn wrapper to /usr/local/bin/sn"

echo "Installation complete"
