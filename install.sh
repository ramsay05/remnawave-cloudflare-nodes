#!/usr/bin/env bash
set -euo pipefail

if [[ $(uname -s) != Linux ]]; then
    echo 'Установщик предназначен для Linux-сервера.' >&2
    exit 1
fi
if [[ ! -t 0 ]]; then
    echo 'Нужен интерактивный терминал: скачайте install.sh и запустите bash install.sh.' >&2
    exit 1
fi

root_command=()
if (( EUID != 0 )); then
    root_command=(sudo)
fi

missing=()
command -v python3 >/dev/null 2>&1 || missing+=(python3)
command -v git >/dev/null 2>&1 || missing+=(git)
if ((${#missing[@]})); then
    if ! command -v apt-get >/dev/null 2>&1; then
        echo "Установите зависимости и повторите запуск: ${missing[*]}" >&2
        exit 1
    fi
    read -r -p "Установить недостающие пакеты ${missing[*]} через APT? [д/Н]: " answer
    case "$answer" in
        д|Д|да|Да|y|Y|yes) ;;
        *) echo 'Установка отменена.'; exit 1 ;;
    esac
    "${root_command[@]}" apt-get update
    "${root_command[@]}" apt-get install -y "${missing[@]}" ca-certificates
fi
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else "Нужен Python 3.9 или новее для установщика.")'

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
if [[ -f "$script_dir/scripts/install.py" && -f "$script_dir/docker-compose.yml" ]]; then
    project_dir=$script_dir
else
    repo_url=https://github.com/ramsay05/remnawave-cloudflare-nodes.git
    default_dir="$HOME/remnawave-cloudflare-nodes"
    if (( EUID == 0 )); then default_dir=/opt/remnawave-cloudflare-nodes; fi
    read -r -p "Каталог установки [$default_dir]: " project_dir
    project_dir=${project_dir:-$default_dir}
    if [[ "$project_dir" == -* ]]; then
        echo 'Каталог не должен начинаться с дефиса.' >&2
        exit 1
    fi
    if [[ -d "$project_dir/.git" ]]; then
        origin=$(git -C "$project_dir" remote get-url origin)
        if [[ "$origin" != "$repo_url" && "$origin" != https://github.com/ramsay05/remnawave-cloudflare-nodes ]]; then
            echo 'В выбранном каталоге находится другой репозиторий. Выберите новый каталог.' >&2
            exit 1
        fi
        echo 'Используется существующая копия. Для обновления кода отдельно выполните git pull --ff-only.'
    else
        git clone --branch master -- "$repo_url" "$project_dir"
    fi
fi

cd -- "$project_dir"
if [[ ! -f scripts/install.py ]]; then
    echo 'Установщик не найден в этой версии. Обновите репозиторий: git pull --ff-only.' >&2
    exit 1
fi
exec python3 scripts/install.py "$@"
