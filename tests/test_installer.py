import json
import os
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stdout
import io
import subprocess
from unittest.mock import patch

from dotenv import dotenv_values
import yaml

from scripts import install


class InstallerTests(unittest.TestCase):
    def setUp(self):
        output = redirect_stdout(io.StringIO())
        output.__enter__()
        self.addCleanup(output.__exit__, None, None, None)

    def settings(self):
        return ({"REMNAWAVE_API_URL": "https://panel.example.com",
                 "REMNAWAVE_API_KEY": "panel-token", "CLOUDFLARE_API_TOKEN": "cf-token",
                 "DISABLE_UNREACHABLE_HOSTS": "false", "TELEGRAM_ENABLED": "false"},
                {"remnawave": {"check-interval": 30}, "domains": [
                    {"domain": "example.com", "zones": [{"name": "vpn", "ttl": 60,
                     "proxied": False, "nodes": [{"ip": "192.0.2.1", "address": "100.64.0.1"}]}]}]},
                {"hosts": []})

    def test_panel_url_validation(self):
        self.assertEqual(install.panel_url("https://panel.example.com/"), "https://panel.example.com")
        for value in ("panel.example.com", "https://panel.example.com/api", "https://u:p@example.com", "https://example.com/?token=secret"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                install.panel_url(value)

    def test_ipv4_only(self):
        self.assertEqual(install.ipv4("192.0.2.1"), "192.0.2.1")
        for value in ("::1", "999.0.0.1", "example.com", "1.2.3.4\nBAD=1"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                install.ipv4(value)

    def test_host_uuid_is_required_and_valid(self):
        value = "123e4567-e89b-42d3-a456-426614174000"
        self.assertEqual(install.host_uuids(value), [{"uuid": value}])
        for value in ("", "not-a-uuid"):
            with self.assertRaises(ValueError):
                install.host_uuids(value)

    def test_env_rejects_injection(self):
        for value in ("x\nBAD=1", "${HOME}", "x'quote", "x\rvalue"):
            with self.assertRaises(ValueError):
                install.render_env({"TOKEN": value})

    def test_configuration_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            env, config, hosts = self.settings()
            install.write_settings(root, env, config, hosts)
            self.assertEqual(dict(dotenv_values(root / ".env")), env)
            self.assertEqual(yaml.safe_load((root / "config.yml").read_text()), config)
            self.assertEqual(yaml.safe_load((root / "hosts.yml").read_text()), hosts)
            if os.name == "posix":
                self.assertEqual((root / ".env").stat().st_mode & 0o777, 0o600)

    def test_existing_files_are_not_overwritten_by_default(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".env").write_text("existing-secret")
            with self.assertRaises(FileExistsError):
                install.write_settings(root, *self.settings())
            self.assertEqual((root / ".env").read_text(), "existing-secret")
            self.assertFalse((root / "config.yml").exists())

    def test_explicit_reconfiguration_backs_up_every_original(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in install.CONFIG_FILES:
                (root / name).write_text("old-" + name)
            backup = install.write_settings(root, *self.settings(), overwrite=True)
            self.assertTrue(backup.is_relative_to(root / ".installer-backups"))
            for name in install.CONFIG_FILES:
                self.assertEqual((backup / name).read_text(), "old-" + name)
            self.assertEqual(json.loads((root / "hosts.yml").read_text()), {"hosts": []})

    def test_configuration_write_rolls_back_on_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in install.CONFIG_FILES:
                (root / name).write_text("old-" + name)
            original = os.replace

            def fail_config(source, target):
                if Path(target).name == "config.yml":
                    raise OSError("disk failure")
                return original(source, target)

            with patch.object(install.os, "replace", side_effect=fail_config):
                with self.assertRaises(OSError):
                    install.write_settings(root, *self.settings(), overwrite=True)
            for name in install.CONFIG_FILES:
                self.assertEqual((root / name).read_text(), "old-" + name)

    def test_minimal_interactive_configuration(self):
        # URL, interval, domain, zone, TTL, proxy, IP, panel address,
        # another node/zone/domain, Telegram, host sync, timezone.
        answers = iter(["https://panel.example.com", "", "example.com", "vpn", "", "",
                        "192.0.2.1", "100.64.0.1", "", "", "", "", "", ""])
        secrets = iter(["panel-token", "cf-token"])
        env, config, hosts = install.collect_settings(
            input_fn=lambda prompt: next(answers), secret_fn=lambda prompt: next(secrets))
        self.assertEqual(env["REMNAWAVE_API_KEY"], "panel-token")
        self.assertEqual(env["API_ENABLED"], "false")
        self.assertEqual(env["DISABLE_UNREACHABLE_HOSTS"], "false")
        self.assertEqual(config["domains"][0]["zones"][0]["nodes"],
                         [{"ip": "192.0.2.1", "address": "100.64.0.1"}])
        self.assertEqual(hosts, {"hosts": []})

    def test_declining_summary_writes_nothing(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(install, "ROOT", Path(directory)), \
                patch.object(install.sys.stdin, "isatty", return_value=True), \
                patch.object(install, "collect_settings", return_value=self.settings()), \
                patch.object(install, "confirm", return_value=False), redirect_stdout(io.StringIO()) as output:
            self.assertEqual(install.main(["--configure-only"]), 0)
            self.assertEqual(list(Path(directory).iterdir()), [])
            self.assertNotIn("panel-token", output.getvalue())
            self.assertNotIn("cf-token", output.getvalue())

    def test_reuse_preserves_existing_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in install.CONFIG_FILES:
                (root / name).write_text("keep-" + name)
            with patch.object(install, "ROOT", root), patch.object(install.sys.stdin, "isatty", return_value=True), \
                    patch.object(install, "confirm", return_value=False), \
                    patch.object(install, "collect_settings", side_effect=AssertionError("must reuse")):
                self.assertEqual(install.main(["--configure-only"]), 0)
            for name in install.CONFIG_FILES:
                self.assertEqual((root / name).read_text(), "keep-" + name)

    def test_incomplete_existing_configuration_aborts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".env").write_text("keep")
            with patch.object(install, "ROOT", root), patch.object(install.sys.stdin, "isatty", return_value=True), \
                    patch.object(install, "confirm", return_value=False):
                with self.assertRaises(RuntimeError):
                    install.main(["--configure-only"])
            self.assertEqual((root / ".env").read_text(), "keep")

    def test_deployment_builds_local_code_without_secrets_in_arguments(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            commands = []

            def run(command, **kwargs):
                commands.append(command)
                self.assertEqual(kwargs["cwd"], root)
                self.assertTrue(kwargs["check"])
                return subprocess.CompletedProcess(command, 0)

            with patch.object(install, "ROOT", root), patch.object(install.sys, "platform", "linux"), \
                    patch.object(install.sys.stdin, "isatty", return_value=True), \
                    patch.object(install, "collect_settings", return_value=self.settings()), \
                    patch.object(install, "confirm", return_value=True), \
                    patch.object(install, "docker_command", return_value=["docker"]), \
                    patch.object(install.subprocess, "run", side_effect=run):
                self.assertEqual(install.main([]), 0)
            prefix = ["docker", "compose", "-f", str(root / "docker-compose.yml")]
            self.assertEqual(commands, [prefix + ["config", "--quiet"],
                                       prefix + ["up", "-d", "--build"], prefix + ["ps"]])
            self.assertNotIn("panel-token", str(commands))

    def test_build_failure_is_propagated_and_configuration_retained(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            def run(command, **kwargs):
                if "up" in command:
                    raise subprocess.CalledProcessError(1, command)
                return subprocess.CompletedProcess(command, 0)

            with patch.object(install, "ROOT", root), patch.object(install.sys, "platform", "linux"), \
                    patch.object(install.sys.stdin, "isatty", return_value=True), \
                    patch.object(install, "collect_settings", return_value=self.settings()), \
                    patch.object(install, "confirm", return_value=True), \
                    patch.object(install, "docker_command", return_value=["docker"]), \
                    patch.object(install.subprocess, "run", side_effect=run):
                with self.assertRaises(subprocess.CalledProcessError):
                    install.main([])
            self.assertTrue((root / ".env").is_file())

    def test_multiple_domains_telegram_and_host_safelist(self):
        uuid = "123e4567-e89b-42d3-a456-426614174000"
        answers = iter(["https://panel.example.com", "10", "example.com", "@", "1", "",
                        "192.0.2.1", "", "да", "192.0.2.2", "node.example.com", "", "", "да",
                        "example.net", "vpn", "120", "да", "192.0.2.3", "", "", "", "",
                        "да", "-1001234567890", "5", "да", uuid, "UTC"])
        tokens = iter(["panel-token", "cf-token", "123:telegram-token"])
        env, config, hosts = install.collect_settings(input_fn=lambda _: next(answers), secret_fn=lambda _: next(tokens))
        self.assertEqual(len(config["domains"]), 2)
        self.assertEqual(len(config["domains"][0]["zones"][0]["nodes"]), 2)
        self.assertEqual(config["domains"][1]["zones"][0]["ttl"], 1)
        self.assertEqual(env["TELEGRAM_CHAT_ID"], "-1001234567890")
        self.assertEqual(env["TELEGRAM_TOPIC_ID"], "5")
        self.assertEqual(env["DISABLE_UNREACHABLE_HOSTS"], "true")
        self.assertEqual(hosts, {"hosts": [{"uuid": uuid}]})


if __name__ == "__main__":
    unittest.main()
