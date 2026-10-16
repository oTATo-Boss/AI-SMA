"""Execute the actual hook process in temporary projects; no checked command is run."""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

DIRECTORY = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("hook_config", DIRECTORY / "hook_config.py")
CONFIG = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CONFIG)


class HookEntryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="hook-entry-", dir=os.environ.get("OTATO_TEST_ARTIFACT_DIR"))
        self.root = Path(self.temporary.name) / "项目 with spaces & symbol"
        scripts = self.root / "agents/公共/工具/写入保护"
        scripts.mkdir(parents=True)
        for filename in ("protect_paths.py", "hook_entry.py"):
            shutil.copyfile(DIRECTORY / filename, scripts / filename)
        self.entry = scripts / "hook_entry.py"
        (self.root / "固定资产").mkdir()
        self.cwd = self.root / "agents/工作/嵌套"
        self.cwd.mkdir(parents=True)
        self.payload = {"tool_name": "Write", "cwd": str(self.cwd),
                        "tool_input": {"file_path": str(self.root / "固定资产/禁止.txt")}}
        self.env = dict(os.environ)
        self.env.pop("CLAUDE_PROJECT_DIR", None)

    def tearDown(self):
        self.temporary.cleanup()

    def assert_denied(self, process):
        self.assertEqual(process.returncode, 0, process.stderr)
        decision = json.loads(process.stdout)["hookSpecificOutput"]["permissionDecision"]
        self.assertEqual(decision, "deny")

    def test_entry_locates_project_from_client_cwd(self):
        process = subprocess.run([sys.executable, str(self.entry)], cwd=self.cwd, env=self.env,
                                 input=json.dumps(self.payload), capture_output=True, encoding="utf-8")
        self.assert_denied(process)

    def test_explicit_project_protects_when_tool_runs_outside_project(self):
        self.payload["cwd"] = self.temporary.name
        process = subprocess.run([sys.executable, str(self.entry), "--project", str(self.root)],
                                 cwd=self.temporary.name, env=self.env, input=json.dumps(self.payload),
                                 capture_output=True, encoding="utf-8")
        self.assert_denied(process)

    def test_generated_hook_executes_with_spaces_and_shell_metacharacters(self):
        generated = CONFIG.render_hooks(self.root, sys.executable)
        for client in ("codex", "claude"):
            command = generated[client]["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
            process = subprocess.run(command, shell=True, cwd=self.cwd, env=self.env,
                                     input=json.dumps(self.payload), capture_output=True, encoding="utf-8")
            self.assert_denied(process)

    def test_portable_repository_hook_locates_ancestor(self):
        generated = CONFIG.render_hooks(python_executable=sys.executable)
        command = generated["codex"]["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
        process = subprocess.run(command, shell=True, cwd=self.cwd, env=self.env,
                                 input=json.dumps(self.payload), capture_output=True, encoding="utf-8")
        self.assert_denied(process)

    def test_unknown_project_reports_unchecked(self):
        self.payload["cwd"] = self.temporary.name
        process = subprocess.run([sys.executable, str(self.entry)], cwd=self.temporary.name, env=self.env,
                                 input=json.dumps(self.payload), capture_output=True, encoding="utf-8")
        self.assertEqual((process.returncode, process.stdout), (0, ""))
        self.assertIn("未找到项目", process.stderr)


class HookConfigTests(unittest.TestCase):
    def test_windows_cmd_quotes_every_argument(self):
        generated = CONFIG.render_hooks(r"C:\Projects\含空格 & 项目", r"C:\Python 3\python.exe", os_name="Windows")
        command = generated["claude"]["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
        self.assertTrue(command.startswith('"C:\\Python 3\\python.exe" '))
        self.assertIn('"C:\\Projects\\含空格 & 项目\\agents\\公共\\工具\\写入保护\\hook_entry.py"', command)
        self.assertNotIn("$PWD", command)
        self.assertNotIn("while", command)

    def test_powershell_quotes_single_quotes(self):
        command = CONFIG.quote_command(["C:\\Python\\python.exe", "C:\\O'Test\\a.py"], "powershell")
        self.assertEqual(command, "& 'C:\\Python\\python.exe' 'C:\\O''Test\\a.py'")

    def test_cmd_expansion_requires_alternative_shell(self):
        with self.assertRaisesRegex(ValueError, "powershell"):
            CONFIG.render_hooks(r"C:\Projects\%USERPROFILE%", r"C:\Python\python.exe", os_name="Windows")

    def test_merge_preserves_settings_and_unrelated_hooks(self):
        existing = {"permissions": {"deny": ["Edit(/固定资产/**)"]}, "model": "user-choice", "hooks": {
            "PostToolUse": [{"matcher": "*", "hooks": [{"command": "other-post"}]}],
            "PreToolUse": [{"matcher": "Bash", "hooks": [{"command": "user-hook"},
                {"command": "python3 agents/公共/工具/写入保护/protect_paths.py"}]}]}}
        rendered = CONFIG.render_hooks()["claude"]
        combined = CONFIG.merge_hooks(existing, rendered)
        self.assertEqual(combined["permissions"], existing["permissions"])
        self.assertEqual(combined["model"], "user-choice")
        self.assertEqual(combined["hooks"]["PostToolUse"], existing["hooks"]["PostToolUse"])
        self.assertEqual(combined["hooks"]["PreToolUse"][0]["hooks"], [{"command": "user-hook"}])
        self.assertEqual(len(existing["hooks"]["PreToolUse"][0]["hooks"]), 2)
        self.assertEqual(CONFIG.merge_hooks(combined, rendered), combined)


if __name__ == "__main__":
    unittest.main(verbosity=2)
