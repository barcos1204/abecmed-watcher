"""Testes offline: só arquivos temporários e valores fictícios."""

import configparser
from contextlib import redirect_stderr, redirect_stdout
import io
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

from scripts import configure as cfg


ROOT = Path(__file__).resolve().parents[1]
FAKE_CPF = "0" * 11
OLD_TOPIC = "fixture-existing-topic"
SAVED = (
    "# Comentário que deve sobreviver a Enter\n"
    "[abecmed]\ncpf = 000.000.000-00\n"
    f"topico = {OLD_TOPIC}\nintervalo_min = 17\nintervalo_max = 29\n"
    "adicional = manter\n[outra]\nchave = intacta\n"
).encode("utf-8")


def read_config(path):
    config = configparser.ConfigParser(interpolation=None)
    with path.open(encoding="utf-8-sig") as source:
        config.read_file(source)
    return config


class ConfigureTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.file = Path(tmp.name) / "config.ini"

    def answer(self, *answers):
        message = io.StringIO()
        with mock.patch("builtins.input", side_effect=answers):
            with redirect_stdout(message), redirect_stderr(message):
                code = cfg.main(self.file)
        return code, message.getvalue()

    def test_first_setup_uses_sixteen_secure_bytes(self):
        with mock.patch.object(cfg.secrets, "token_hex", wraps=cfg.secrets.token_hex) as generate:
            code, output = self.answer(FAKE_CPF, "")
        self.assertEqual(code, 0)
        generate.assert_called_once_with(16)
        section = read_config(self.file)["abecmed"]
        self.assertRegex(section["topico"], r"^abecmed-[0-9a-f]{32}$")
        self.assertIn(section["topico"], output)
        self.assertNotIn(FAKE_CPF, output)
        self.assertEqual((section["intervalo_min"], section["intervalo_max"]), ("7", "12"))
        if os.name == "posix":
            self.assertEqual(self.file.stat().st_mode & 0o077, 0)

    def test_enter_keeps_exact_file_without_drawing_or_rewriting(self):
        self.file.write_bytes(SAVED)
        with mock.patch.object(cfg.secrets, "token_hex") as generate, mock.patch.object(cfg, "save_config") as save:
            code, output = self.answer("", "")
        self.assertEqual(code, 0)
        save.assert_not_called()
        generate.assert_not_called()
        self.assertEqual(self.file.read_bytes(), SAVED)
        self.assertNotIn(OLD_TOPIC, output)
        self.assertNotIn("000.000.000-00", output)

    def test_explicit_rotation_changes_only_topic_values(self):
        self.file.write_bytes(SAVED)
        before = read_config(self.file)
        with mock.patch.object(cfg.secrets, "token_hex", return_value="a" * 32) as generate:
            code, output = self.answer("", ":novo")
        self.assertEqual(code, 0)
        generate.assert_called_once_with(16)
        expected = "abecmed-" + "a" * 32
        self.assertIn(expected, output)
        self.assertNotIn(OLD_TOPIC, output)
        before.set("abecmed", "topico", expected)
        self.assertEqual(read_config(self.file), before)

    def test_custom_topic_retries_invalid_name_without_rng(self):
        self.file.write_bytes(SAVED)
        with mock.patch.object(cfg.secrets, "token_hex") as generate:
            code, _ = self.answer("", "tem espaço", "meu-canal_2")
        self.assertEqual(code, 0)
        self.assertEqual(read_config(self.file)["abecmed"]["topico"], "meu-canal_2")
        generate.assert_not_called()

    def test_rng_failure_never_falls_back_or_overwrites(self):
        for previous, error in ((None, OSError), (SAVED, NotImplementedError)):
            with self.subTest(error=error):
                if previous is not None:
                    self.file.write_bytes(previous)
                with mock.patch.object(cfg.secrets, "token_hex", side_effect=error("sensitive-marker")):
                    code, output = self.answer(FAKE_CPF, ":novo")
                self.assertNotEqual(code, 0)
                self.assertNotIn("sensitive-marker", output)
                self.assertNotIn(OLD_TOPIC, output)
                self.assertEqual(self.file.read_bytes() if self.file.exists() else None, previous)

    def test_cancel_during_setup_never_overwrites(self):
        self.file.write_bytes(SAVED)
        for error in (EOFError(), KeyboardInterrupt()):
            with self.subTest(error=type(error).__name__):
                code, output = self.answer("", error)
                self.assertNotEqual(code, 0)
                self.assertEqual(self.file.read_bytes(), SAVED)
                self.assertNotIn(OLD_TOPIC, output)

    def test_broken_config_is_neither_echoed_nor_overwritten(self):
        broken = b"private-invalid-line\n"
        self.file.write_bytes(broken)
        code, output = self.answer()
        self.assertNotEqual(code, 0)
        self.assertNotIn("private-invalid-line", output)
        self.assertEqual(self.file.read_bytes(), broken)

    def test_failed_replace_keeps_file_and_cleans_private_temporary(self):
        self.file.write_bytes(SAVED)
        with mock.patch.object(cfg.os, "replace", side_effect=PermissionError):
            code, _ = self.answer("", "replacement")
        self.assertNotEqual(code, 0)
        self.assertEqual(self.file.read_bytes(), SAVED)
        self.assertEqual(list(self.file.parent.iterdir()), [self.file])

    def test_native_launcher_from_installation_path_with_spaces(self):
        install = self.file.parent / "pasta com espacos"
        (install / "scripts").mkdir(parents=True)
        shutil.copy2(ROOT / "scripts" / "configure.py", install / "scripts")
        launcher = "configurar.bat" if os.name == "nt" else "configurar.sh"
        shutil.copy2(ROOT / launcher, install)
        cmd = ["cmd.exe", "/d", "/c", launcher] if os.name == "nt" else ["bash", launcher]

        def run(answers):
            return subprocess.run(
                cmd, cwd=install, input=answers, text=True, encoding="utf-8",
                capture_output=True, timeout=15,
                env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"},
            )

        target = install / "config.ini"
        self.assertNotEqual(run("").returncode, 0)
        self.assertFalse(target.exists())
        self.assertEqual(run(FAKE_CPF + "\n\n").returncode, 0)
        topic = read_config(target)["abecmed"]["topico"]
        self.assertRegex(topic, r"^abecmed-[0-9a-f]{32}$")
        before = target.read_bytes()
        result = run("\n\n")
        self.assertEqual(result.returncode, 0)
        self.assertNotIn(topic, result.stdout)
        self.assertEqual(target.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
