"""Integracao Git inteiramente local, usando repositorios temporarios."""

import os
from pathlib import Path
import subprocess
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "save-state.sh"


class SaveStateTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.remote = self.root / "remote.git"
        self.writer = self.root / "writer"
        self.worker = self.root / "worker"
        self.env = dict(os.environ, GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
                        GIT_TERMINAL_PROMPT="0")
        self.git(self.root, "init", "--bare", "--initial-branch=main", str(self.remote))
        self.git(self.root, "clone", str(self.remote), str(self.writer))
        self.git(self.writer, "config", "user.name", "Test")
        self.git(self.writer, "config", "user.email", "test@example.invalid")
        (self.writer / "estado.json").write_text('{"report":"old"}\n', encoding="utf-8")
        (self.writer / "bot.py").write_text("# initial\n", encoding="utf-8")
        self.git(self.writer, "add", "estado.json", "bot.py")
        self.git(self.writer, "commit", "-m", "initial")
        self.git(self.writer, "push", "origin", "main")
        self.git(self.root, "clone", str(self.remote), str(self.worker))

    def git(self, cwd, *args):
        result = subprocess.run(["git", *args], cwd=cwd, env=self.env,
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stdout.strip()

    def run_script(self):
        return subprocess.run(["bash", str(SCRIPT)], cwd=self.worker, env=self.env,
                              capture_output=True, text=True, timeout=15)

    def change_local_state(self):
        (self.worker / "estado.json").write_text('{"report":"new"}\n', encoding="utf-8")

    def change_remote(self, filename, content):
        (self.writer / filename).write_text(content, encoding="utf-8")
        self.git(self.writer, "add", filename)
        self.git(self.writer, "commit", "-m", "concurrent update")
        self.git(self.writer, "push", "origin", "main")

    def test_unchanged_state_does_not_commit(self):
        old_head = self.git(self.remote, "rev-parse", "main")
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.git(self.remote, "rev-parse", "main"), old_head)

    def test_changed_state_is_pushed(self):
        self.change_local_state()
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.git(self.remote, "show", "main:estado.json"), '{"report":"new"}')
        self.assertEqual(self.git(self.remote, "diff-tree", "--no-commit-id", "--name-only", "-r", "main"),
                         "estado.json")

    def test_concurrent_code_change_is_preserved(self):
        self.change_local_state()
        self.change_remote("bot.py", "# newer code\n")
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.git(self.remote, "show", "main:bot.py"), "# newer code")
        self.assertEqual(self.git(self.remote, "show", "main:estado.json"), '{"report":"new"}')

    def test_concurrent_state_change_is_never_overwritten(self):
        self.change_local_state()
        self.change_remote("estado.json", '{"report":"newer remote"}\n')
        old_head = self.git(self.remote, "rev-parse", "main")
        result = self.run_script()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("nao foi sobrescrito", result.stdout)
        self.assertEqual(self.git(self.remote, "rev-parse", "main"), old_head)
        self.assertEqual(self.git(self.remote, "show", "main:estado.json"), '{"report":"newer remote"}')

    def test_rejected_push_stops_after_three_attempts(self):
        self.change_local_state()
        old_head = self.git(self.remote, "rev-parse", "main")
        hook = self.remote / "hooks" / "pre-receive"
        hook.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
        hook.chmod(0o755)
        result = self.run_script()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout.count("Push nao concluido"), 3)
        self.assertEqual(self.git(self.remote, "rev-parse", "main"), old_head)


if __name__ == "__main__":
    unittest.main()
