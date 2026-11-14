#!/usr/bin/env python3
"""Interactive configuration and Docker deployment; standard library only."""

import argparse
from datetime import datetime, timezone
import getpass
import ipaddress
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from urllib.parse import urlsplit
from uuid import UUID

CONFIG_FILES = (".env", "config.yml", "hosts.yml")
ROOT = Path(__file__).resolve().parent.parent


def panel_url(value):
    parsed = urlsplit(value)
    if (parsed.scheme not in ("https", "http") or not parsed.hostname
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or parsed.path.rstrip("/").endswith("/api")):
        raise ValueError("Нужен URL панели с http:// или https://, без /api, логина и параметров.")
    safe_value(value)
    return value.rstrip("/")


def safe_value(value):
    if not value or any(c in value for c in "\r\n\x00'\\$"):
        raise ValueError("Значение пустое или содержит недопустимые специальные символы.")
    return value


def domain_name(value):
    value = value.rstrip(".").encode("idna").decode("ascii").lower()
    if len(value) > 253 or not all(re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", p)
                                    for p in value.split(".")):
        raise ValueError("Введите DNS-имя без схемы, порта и пути.")
    return value


def ipv4(value):
    try:
        return str(ipaddress.IPv4Address(value))
    except ValueError:
        raise ValueError("Нужен IPv4: этот монитор управляет A-записями.") from None


def node_address(value):
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        return domain_name(value)


def host_uuids(value):
    values = value.replace(",", " ").split()
    if not values:
        raise ValueError("Укажите хотя бы один UUID хоста.")
    try:
        return [{"uuid": u} for u in dict.fromkeys(str(UUID(v)) for v in values)]
    except ValueError:
        raise ValueError("Нужны UUID хостов через пробел или запятую.") from None


def number(value, minimum=1, maximum=86400):
    try:
        result = int(value)
    except ValueError:
        raise ValueError("Введите целое число.") from None
    if not minimum <= result <= maximum:
        raise ValueError(f"Допустимый диапазон: {minimum}–{maximum}.")
    return result


def ttl_value(value):
    return 1 if value == "1" else number(value, 60, 86400)


def prompt(label, default=None, validator=safe_value, input_fn=input):
    while True:
        value = input_fn(label + (f" [{default}]" if default is not None else "") + ": ").strip()
        if not value and default is not None:
            value = str(default)
        try:
            return validator(value)
        except (ValueError, UnicodeError) as error:
            print(f"Ошибка: {error}")


def confirm(label, default=False, input_fn=input):
    while True:
        value = input_fn(label + (" [Д/н]: " if default else " [д/Н]: ")).strip().lower()
        if not value:
            return default
        if value in ("y", "yes", "д", "да"):
            return True
        if value in ("n", "no", "н", "нет"):
            return False
        print("Введите да или нет.")


def collect_settings(input_fn=input, secret_fn=getpass.getpass):
    def ask(label, default=None, validator=safe_value):
        return prompt(label, default, validator, input_fn)

    def yes(label):
        return confirm(label, input_fn=input_fn)

    env = {"REMNAWAVE_API_URL": ask("URL панели Remnawave", validator=panel_url)}
    env["REMNAWAVE_API_KEY"] = prompt("Токен Remnawave (ввод скрыт)", input_fn=secret_fn)
    print("Cloudflare: нужны Zone / DNS / Edit и Zone / Zone / Read для ваших зон.")
    env["CLOUDFLARE_API_TOKEN"] = prompt("Токен Cloudflare (ввод скрыт)", input_fn=secret_fn)
    interval = ask("Интервал проверки, секунд", 30, lambda v: number(v, 5))
    domains = []
    while True:
        domain = ask("Домен зоны Cloudflare, например example.com", validator=domain_name)
        if any(d["domain"] == domain for d in domains):
            print("Этот домен уже добавлен.")
            continue
        zones = []
        while True:
            zone = ask("Имя записи: vpn, sub.vpn или @ для корня", "vpn",
                       lambda v: "@" if v == "@" else domain_name(v))
            if any(z["name"] == zone for z in zones):
                print("Эта запись уже добавлена.")
                continue
            ttl = ask("TTL: 60–86400 секунд, 1 = Auto", 60, ttl_value)
            proxied = yes("Включить Cloudflare proxy? Для прямых подключений к нодам выберите нет")
            nodes = []
            while True:
                ip = ask("Публичный IPv4 ноды для DNS", validator=ipv4)
                if any(n["ip"] == ip for n in nodes):
                    print("Этот IP уже добавлен в запись.")
                    continue
                address = ask("Адрес этой ноды в панели Remnawave", ip, node_address)
                nodes.append({"ip": ip, "address": address})
                if not yes("Добавить ещё ноду в эту запись?"):
                    break
            zones.append({"name": zone, "ttl": 1 if proxied else ttl, "proxied": proxied, "nodes": nodes})
            if not yes("Добавить ещё DNS-запись для этого домена?"):
                break
        domains.append({"domain": domain, "zones": zones})
        if not yes("Добавить ещё домен?"):
            break
    env["TELEGRAM_ENABLED"] = str(yes("Настроить уведомления Telegram?")).lower()
    if env["TELEGRAM_ENABLED"] == "true":
        env["TELEGRAM_BOT_TOKEN"] = prompt("Токен Telegram-бота (ввод скрыт)", input_fn=secret_fn)
        env["TELEGRAM_CHAT_ID"] = str(ask("Telegram chat ID", validator=lambda v: number(v, -10**16, 10**16)))
        env["TELEGRAM_TOPIC_ID"] = ask("ID топика (Enter — без топика)", "",
            lambda v: "" if not v else str(number(v, 1, 10**12)))
    enabled = yes("Автоматически включать/отключать выбранные хосты Remnawave по наличию DNS?")
    hosts = ask("UUID управляемых хостов через пробел", validator=host_uuids) if enabled else []
    env["DISABLE_UNREACHABLE_HOSTS"] = str(enabled).lower()
    env["TIMEZONE"] = ask("Часовой пояс", "Europe/Moscow", timezone_name)
    env.update({"LANGUAGE": "ru", "API_ENABLED": "false", "LOG_LEVEL": "INFO",
                "TELEGRAM_NOTIFY_HOST_CHANGES": "true"})
    return env, {"remnawave": {"check-interval": interval}, "domains": domains}, {"hosts": hosts}


def timezone_name(value):
    # The container provides tzdata via pytz; validate against host zoneinfo when present.
    safe_value(value)
    if not re.fullmatch(r"[A-Za-z0-9_+/-]+", value) or ".." in value or value.startswith("/"):
        raise ValueError("Нужен часовой пояс, например Europe/Moscow или UTC.")
    zones = Path("/usr/share/zoneinfo")
    if zones.is_dir() and not (zones / value).is_file():
        raise ValueError("Неизвестный часовой пояс.")
    return value


def render_env(env):
    lines = []
    for key, value in env.items():
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", key):
            raise ValueError("Недопустимое имя переменной.")
        if value:
            safe_value(value)
        lines.append(f"{key}='{value}'")
    return "\n".join(lines) + "\n"


def write_settings(root, env, config, hosts, overwrite=False):
    contents = {".env": render_env(env), "config.yml": json.dumps(config, indent=2, ensure_ascii=False) + "\n",
                "hosts.yml": json.dumps(hosts, indent=2, ensure_ascii=False) + "\n"}
    originals = {}
    for name in CONFIG_FILES:
        path = root / name
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise ValueError(f"{path} должен быть обычным файлом, не ссылкой или каталогом.")
        if path.exists():
            if not overwrite:
                raise FileExistsError(f"{path} уже существует.")
            originals[name] = path.read_bytes()
    backup = None
    if originals:
        backup_root = root / ".installer-backups"
        if backup_root.is_symlink():
            raise ValueError("Каталог резервных копий не должен быть ссылкой.")
        backup_root.mkdir(mode=0o700, exist_ok=True)
        backup = Path(tempfile.mkdtemp(prefix=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-"), dir=backup_root))
        for name, data in originals.items():
            private_write(backup / name, data)
    written = []
    with tempfile.TemporaryDirectory(prefix=".installer-", dir=root) as staging:
        try:
            for name, content in contents.items():
                private_write(Path(staging) / name, content.encode("utf-8"))
            for name in CONFIG_FILES:
                os.replace(Path(staging) / name, root / name)
                written.append(name)
        except OSError:
            for name in written:
                if name in originals:
                    private_write(root / name, originals[name])
                else:
                    (root / name).unlink()
            raise
    return backup


def private_write(path, data):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(data)
    path.chmod(0o600)


def docker_command(root):
    if not shutil.which("docker"):
        if not confirm("Docker не найден. Установить Docker Engine и Compose из официального APT-репозитория?"):
            raise RuntimeError("Установите Docker и повторите запуск: https://docs.docker.com/engine/install/")
        subprocess.run(["bash", str(root / "scripts/install-docker.sh")], check=True)
    command = ["docker"]
    if subprocess.run(command + ["info"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode:
        if os.geteuid() != 0 and shutil.which("sudo") and confirm("Проверить доступ к Docker через sudo?", True):
            command = ["sudo", "docker"]
        if subprocess.run(command + ["info"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode:
            raise RuntimeError("Docker daemon недоступен. Запустите его и проверьте права доступа.")
    if subprocess.run(command + ["compose", "version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode:
        if not confirm("Compose отсутствует. Попробовать установить docker-compose-plugin из настроенного APT-репозитория?"):
            raise RuntimeError("Установите плагин Docker Compose и повторите запуск.")
        subprocess.run(["bash", str(root / "scripts/install-docker.sh"), "--compose-only"], check=True)
        subprocess.run(command + ["compose", "version"], check=True)
    return command


def main(argv=None):
    parser = argparse.ArgumentParser(description="Интерактивная установка Remnawave Cloudflare Nodes")
    parser.add_argument("--configure-only", action="store_true", help="Только создать конфигурацию, без Docker")
    args = parser.parse_args(argv)
    if not args.configure_only and not sys.platform.startswith("linux"):
        raise RuntimeError("Автоустановка рассчитана на Linux. Для подготовки файлов есть --configure-only.")
    if not sys.stdin.isatty():
        raise RuntimeError("Нужен интерактивный терминал. Скачайте install.sh и запустите bash install.sh.")
    print(f"Remnawave Cloudflare Nodes — установка в {ROOT}")
    existing = [name for name in CONFIG_FILES if (ROOT / name).exists() or (ROOT / name).is_symlink()]
    reconfigure = True
    if existing:
        print("Найдены настройки: " + ", ".join(existing))
        reconfigure = confirm("Настроить заново с резервной копией существующих файлов?")
        if not reconfigure and (len(existing) != len(CONFIG_FILES) or any(not (ROOT / n).is_file() or (ROOT / n).is_symlink() for n in CONFIG_FILES)):
            raise RuntimeError("Набор файлов неполный или содержит ссылки/каталоги. Перезапустите с настройкой заново.")
    if reconfigure:
        env, config, hosts = collect_settings()
        print("\nНастройки (токены скрыты):")
        print("Панель: " + env["REMNAWAVE_API_URL"])
        for domain in config["domains"]:
            for zone in domain["zones"]:
                name = domain["domain"] if zone["name"] == "@" else zone["name"] + "." + domain["domain"]
                print(f"  {name}: {len(zone['nodes'])} нод, TTL={zone['ttl']}, proxy={zone['proxied']}")
        print(f"Хостов для синхронизации: {len(hosts['hosts'])}; Telegram: {env['TELEGRAM_ENABLED']}")
        if not confirm("Сохранить настройки?", True):
            print("Отменено. Настройки не изменены.")
            return 0
        backup = write_settings(ROOT, env, config, hosts, overwrite=bool(existing))
        print("Настройки сохранены с правами 600. JSON в файлах .yml совместим с YAML.")
        if backup:
            print(f"Резервная копия: {backup}")
    if args.configure_only or not confirm("Собрать образ и запустить монитор? Он будет изменять DNS выбранных имён.", True):
        print("Для запуска: docker compose up -d --build")
        return 0
    command = docker_command(ROOT)
    compose = command + ["compose", "-f", str(ROOT / "docker-compose.yml")]
    subprocess.run(compose + ["config", "--quiet"], cwd=ROOT, check=True)
    subprocess.run(compose + ["up", "-d", "--build"], cwd=ROOT, check=True)
    subprocess.run(compose + ["ps"], cwd=ROOT, check=True)
    print("Команда запуска выполнена. Проверьте состояние и логи: docker compose logs --tail=100 -f")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (KeyboardInterrupt, EOFError):
        print("\nУстановка прервана.", file=sys.stderr)
        sys.exit(130)
    except (ValueError, OSError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"Ошибка установки: {error}", file=sys.stderr)
        sys.exit(1)
