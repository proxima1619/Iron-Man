#!/bin/bash
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
apt-get -o Acquire::Retries=10 update
apt-get -o Acquire::Retries=10 install -y ca-certificates curl git python3
install -m 0755 -d /etc/apt/keyrings
curl --fail --silent --show-error --retry 10 --retry-delay 5 https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
. /etc/os-release
cat > /etc/apt/sources.list.d/docker.sources <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: ${UBUNTU_CODENAME:-$VERSION_CODENAME}
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF
apt-get -o Acquire::Retries=10 update
apt-get -o Acquire::Retries=10 install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
systemctl enable --now docker
usermod -aG docker ubuntu
install -d -o ubuntu -g ubuntu -m 0750 /opt/iron-man
# No app or secret is deployed by cloud-init. SSH deployment follows separately.
