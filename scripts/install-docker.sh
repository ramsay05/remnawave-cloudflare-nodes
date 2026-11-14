#!/usr/bin/env bash
# Official Docker APT repository; no removal of existing container runtimes.
set -euo pipefail

root_command=()
if (( EUID != 0 )); then
    command -v sudo >/dev/null 2>&1 || { echo 'Для установки Docker нужны root или sudo.' >&2; exit 1; }
    root_command=(sudo)
fi

if [[ ! -f /etc/os-release ]]; then
    echo 'Не удалось определить Linux-дистрибутив.' >&2
    exit 1
fi
# System-owned distribution metadata.
. /etc/os-release
case "${ID:-}" in
    ubuntu|debian) ;;
    *) echo 'Автоустановка Docker поддерживает только Ubuntu и Debian. Установите Docker вручную.' >&2; exit 1 ;;
esac
codename=${UBUNTU_CODENAME:-${VERSION_CODENAME:-}}
if [[ ! "$codename" =~ ^[a-z]+$ ]]; then
    echo 'Не удалось определить кодовое имя выпуска.' >&2
    exit 1
fi

if [[ "${1:-}" == --compose-only ]]; then
    # An existing Docker install is not replaced or migrated by this helper.
    "${root_command[@]}" apt-get update
    "${root_command[@]}" apt-get install -y docker-compose-plugin docker-buildx-plugin
    exit 0
fi

for package in docker.io docker-compose docker-compose-v2 docker-doc docker-buildx podman-docker containerd runc; do
    if [[ $(dpkg-query -W -f='${Status}' "$package" 2>/dev/null || true) == 'install ok installed' ]]; then
        echo "Обнаружен пакет $package. Автоматическое удаление отключено; настройте Docker вручную:" >&2
        echo "https://docs.docker.com/engine/install/$ID/" >&2
        exit 1
    fi
done

if [[ -e /etc/apt/sources.list.d/docker.sources || -e /etc/apt/sources.list.d/docker.list ]]; then
    echo 'APT-репозиторий Docker уже настроен; используется текущая конфигурация.'
else
    "${root_command[@]}" apt-get update
    "${root_command[@]}" apt-get install -y ca-certificates curl
    temporary_dir=$(mktemp -d)
    trap 'rm -f -- "$temporary_dir/docker.asc" "$temporary_dir/docker.sources"; rmdir -- "$temporary_dir"' EXIT
    curl --fail --show-error --silent --location "https://download.docker.com/linux/$ID/gpg" -o "$temporary_dir/docker.asc"
    architecture=$(dpkg --print-architecture)
    cat > "$temporary_dir/docker.sources" <<EOF
Types: deb
URIs: https://download.docker.com/linux/$ID
Suites: $codename
Components: stable
Architectures: $architecture
Signed-By: /etc/apt/keyrings/docker.asc
EOF
    "${root_command[@]}" install -m 0755 -d /etc/apt/keyrings
    "${root_command[@]}" install -m 0644 "$temporary_dir/docker.asc" /etc/apt/keyrings/docker.asc
    "${root_command[@]}" install -m 0644 "$temporary_dir/docker.sources" /etc/apt/sources.list.d/docker.sources
fi
"${root_command[@]}" apt-get update
"${root_command[@]}" apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
if command -v systemctl >/dev/null 2>&1; then
    "${root_command[@]}" systemctl enable --now docker
fi
