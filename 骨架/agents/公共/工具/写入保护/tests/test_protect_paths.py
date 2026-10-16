"""写入拦截的行为测试：只在临时夹具里判断，不执行任何被检查的命令。"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "protect_paths.py"
SPEC = importlib.util.spec_from_file_location("protect_paths", SCRIPT)
MOD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MOD)


class ProtectPathsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="protect-", dir=os.environ.get("OTATO_TEST_ARTIFACT_DIR"))
        self.root = Path(self.temporary.name).resolve()
        for folder in ["交付/旧包", "发布内容/已发", "固定资产", "agents/工作/t/交付暂存/新包", "agents/工作/t/交付暂存/旧包"]:
            (self.root / folder).mkdir(parents=True)
        (self.root / "固定资产/logo.png").write_bytes(b"png")
        link, target = self.root / "agents/链接", self.root / "固定资产"
        if os.name == "nt":
            result = subprocess.run(["cmd", "/d", "/c", "mklink", "/J", str(link), str(target)], capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
        else:
            link.symlink_to(target, target_is_directory=True)
        self.original_root, MOD.ROOT = MOD.ROOT, self.root

    def tearDown(self):
        MOD.ROOT = self.original_root
        self.temporary.cleanup()

    def edit(self, tool, path, key="file_path"):
        return MOD.decide({"tool_name": tool, "tool_input": {key: str(self.root / path)}, "cwd": str(self.root)})

    def bash(self, command):
        return MOD.decide({"tool_name": "Bash", "tool_input": {"command": command, "shell": "bash"}, "cwd": str(self.root)})

    def test_edit_tools(self):
        self.assertTrue(self.edit("Write", "固定资产/新.txt"))
        self.assertTrue(self.edit("Edit", "发布内容/已发/文案.txt"))
        self.assertTrue(self.edit("MultiEdit", "交付/新包/发布文案.txt"))
        self.assertTrue(self.edit("NotebookEdit", "固定资产/a.ipynb", key="notebook_path"))
        self.assertTrue(self.edit("Write", "agents/链接/绕过.txt"))
        self.assertIsNone(self.edit("Write", "agents/工作/t/方案.md"))
        self.assertIsNone(MOD.decide({"tool_name": "Read", "tool_input": {"file_path": str(self.root / "固定资产/logo.png")}}))

    def test_delivery_only_new_packages(self):
        self.assertIsNone(self.bash("cp -R agents/工作/t/交付暂存/新包 交付/新包"))
        self.assertIsNone(self.bash("[ ! -e 交付/新包 ] && cp -R agents/工作/t/交付暂存/新包 交付/新包"))
        self.assertIsNone(self.bash("cp -R agents/工作/t/交付暂存/新包 交付/"))
        self.assertIsNone(self.bash("mkdir -p 交付/新包"))
        self.assertTrue(self.bash("cp -R agents/工作/t/交付暂存/旧包 交付/旧包"))
        self.assertTrue(self.bash("cp -R agents/工作/t/交付暂存/旧包 交付/"))
        self.assertTrue(self.bash("rsync -a --delete agents/工作/t/交付暂存/新包/ 交付/旧包/"))
        self.assertTrue(self.bash("mkdir 交付/旧包/附加"))
        self.assertTrue(self.bash("touch 交付/旧包/.x"))
        self.assertTrue(self.bash("tee 交付/旧包/x.txt"))
        self.assertTrue(self.bash("echo hi >> 交付/旧包/发布文案.txt"))
        self.assertTrue(self.bash("rm -rf 交付/旧包"))
        self.assertTrue(self.bash("rm -rf 交付/*"))
        self.assertTrue(self.bash("mv 交付/旧包 agents/工作/t/"))

    def test_read_only_directories(self):
        self.assertTrue(self.bash("echo hi > 固定资产/x.txt"))
        self.assertTrue(self.bash("mv 固定资产/logo.png agents/"))
        self.assertTrue(self.bash("chmod u+w 固定资产/logo.png"))
        self.assertTrue(self.bash("sed -i '' 's/a/b/' 发布内容/已发/文案.txt"))
        self.assertTrue(self.bash("FOO=1 rm 发布内容/已发/文案.txt"))
        self.assertTrue(self.bash("dd if=/dev/zero of=固定资产/x bs=1 count=1"))
        self.assertTrue(self.bash("cat <<'EOF' > 固定资产/a.txt\nbody\nEOF"))
        self.assertTrue(self.bash("rm -rf $PWD/固定资产/logo.png"))
        self.assertTrue(self.bash("rm agents/链接/logo.png"))

    def test_deleting_project_ancestor_cannot_remove_protected_content(self):
        self.assertTrue(self.bash("rm -rf ."))
        self.assertTrue(self.powershell("Remove-Item . -Recurse"))
        self.assertTrue(self.bash("rm -rf .."))

    def test_cd_and_newlines_are_followed(self):
        self.assertTrue(self.bash("cd 交付 && rm -rf 旧包"))
        self.assertTrue(self.bash("cd 交付\nrm -rf 旧包"))
        self.assertTrue(self.bash("find 交付 -name '*.json' -delete"))

    def test_ordinary_work_is_allowed(self):
        for command in ["ls 交付; ffprobe 交付/旧包/视频.mp4",
                        "cp 固定资产/logo.png agents/工作/t/输入/",
                        "find 交付 -name '*.mp4'",
                        "rm -rf agents/工作/t/固定资产副本",
                        "echo hi > agents/工作/t/x.txt 2>&1",
                        "python3 agents/公共/工具/项目检查/检查.py",
                        "echo 'unbalanced"]:
            self.assertIsNone(self.bash(command), command)

    def patch(self, body):
        return MOD.decide({"tool_name": "apply_patch", "tool_input": {"command": "*** Begin Patch\n" + body + "\n*** End Patch"},
                           "cwd": str(self.root)})

    def test_codex_apply_patch(self):
        self.assertTrue(self.patch("*** Add File: 固定资产/新.txt\n+内容"))
        self.assertTrue(self.patch("*** Update File: 发布内容/已发/文案.txt\n@@\n-旧\n+新"))
        self.assertTrue(self.patch("*** Delete File: 交付/旧包/发布文案.txt"))
        self.assertTrue(self.patch("*** Add File: 交付/新包/发布文案.txt\n+内容"))
        self.assertTrue(self.patch("*** Update File: agents/工作/t/方案.md\n*** Move to: 固定资产/方案.md"))
        self.assertTrue(self.patch("*** Add File: agents/链接/绕过.txt\n+内容"))
        self.assertIsNone(self.patch("*** Add File: agents/工作/t/方案.md\n+内容"))
        self.assertIsNone(self.patch(f"*** Update File: {self.root}/agents/工作/t/方案.md\n@@\n-旧\n+新"))

    def test_codex_shell_forms(self):
        heredoc = "apply_patch <<'EOF'\n*** Begin Patch\n*** Add File: 固定资产/x.txt\n+内容\n*** End Patch\nEOF"
        self.assertTrue(self.bash(heredoc))
        listed = MOD.decide({"tool_name": "Bash", "tool_input": {"command": ["bash", "-lc", "rm -rf 固定资产"]}, "cwd": str(self.root)})
        self.assertTrue(listed)
        self.assertIsNone(MOD.decide({"tool_name": "Bash", "tool_input": {"command": ["ls", "交付"]}, "cwd": str(self.root)}))

    def test_hook_output_format(self):
        payload = {"tool_name": "Bash", "tool_input": {"command": "rm -rf 固定资产"}, "cwd": str(self.original_root)}
        denied = subprocess.run([sys.executable, str(SCRIPT)], input=json.dumps(payload), capture_output=True, encoding="utf-8")
        self.assertEqual(denied.returncode, 0, denied.stderr)
        output = json.loads(denied.stdout)["hookSpecificOutput"]
        self.assertEqual((output["hookEventName"], output["permissionDecision"]), ("PreToolUse", "deny"))
        payload["tool_input"]["command"] = "ls 固定资产"
        allowed = subprocess.run([sys.executable, str(SCRIPT)], input=json.dumps(payload), capture_output=True, encoding="utf-8")
        self.assertEqual((allowed.returncode, allowed.stdout), (0, ""))

    def powershell(self, command):
        return MOD.decide({"tool_name": "PowerShell", "tool_input": {"command": command}, "cwd": str(self.root)})

    def test_powershell_writes_and_backslashes(self):
        for command in [
            r"Set-Content -LiteralPath '.\固定资产\x.txt' -Value 'hello'",
            r"Add-Content -Path:'.\交付\旧包\a.txt' -Value 'hello'",
            r"Remove-Item -Recurse -Force .\固定资产",
            r"New-Item -ItemType File -Path '.\发布内容\新.txt'",
            r"Rename-Item -LiteralPath '.\固定资产\logo.png' -NewName other.png",
            r"Set-ItemProperty -Path '.\固定资产\logo.png' -Name IsReadOnly -Value false",
            r"Write-Output 'hello' | Out-File -FilePath '.\固定资产\x.txt'",
            r"Write-Output 'hello' *> '.\固定资产\x.txt'",
            r"Write-Output 'hello' 2>> '.\交付\旧包\x.log'",
            r"Export-Csv -Path .\交付\旧包\report.csv -InputObject data",
            r"Set-Content -Path .\agents\链接\x.txt -Value test",
            r"Set-Location .\交付; Remove-Item .\旧包 -Recurse",
        ]:
            self.assertTrue(self.powershell(command), command)

    def test_powershell_copy_and_ordinary_work(self):
        self.assertTrue(self.powershell(r"Copy-Item -Path '.\agents\工作\t\交付暂存\旧包' -Destination '.\交付' -Recurse"))
        self.assertTrue(self.powershell(r"Move-Item -LiteralPath '.\固定资产\logo.png' -Destination '.\agents\logo.png'"))
        for command in [
            r"Copy-Item '.\agents\工作\t\交付暂存\新包' '.\交付\新包' -Recurse",
            r"Copy-Item -Path '.\agents\工作\t\交付暂存\新包' -Destination '.\交付' -Recurse",
            r"Copy-Item '.\固定资产\logo.png' '.\agents\logo.png'",
            r"Set-Content -LiteralPath '.\agents\work.txt' -Value 'test'",
            r"Get-Content '.\固定资产\logo.png'",
            r"Get-ChildItem '.\交付'",
        ]:
            self.assertIsNone(self.powershell(command), command)

    def test_codex_exec_command_and_explicit_workdir(self):
        self.assertTrue(MOD.decide({"tool_name": "functions.exec_command", "tool_input": {
            "cmd": "rm logo.png", "workdir": str(self.root / "固定资产"), "shell": "/bin/bash"}, "cwd": str(self.root)}))
        self.assertTrue(MOD.decide({"tool_name": "shell_command", "tool_input": {
            "command": ["pwsh", "-Command", r"Set-Content '.\固定资产\x.txt' test"]}, "cwd": str(self.root)}))
        self.assertTrue(self.bash("pwsh -Command 'Remove-Item 固定资产 -Recurse'"))


class WindowsLexicalTests(unittest.TestCase):
    """Foreign-path lexical tests do not claim native junction or PowerShell execution evidence."""
    def setUp(self):
        self.original_root = MOD.ROOT
        self.realpath = patch.object(MOD.os.path, "realpath", side_effect=lambda value: str(value))
        self.realpath.start()

    def tearDown(self):
        MOD.ROOT = self.original_root
        self.realpath.stop()

    def test_drive_case_and_parent_segments(self):
        MOD.ROOT = r"C:\Projects\Example"
        kind, _ = MOD.classify(r"c:\PROJECTS\example\agents\..\固定资产\file.txt")
        self.assertEqual(kind, "readonly")
        self.assertEqual(MOD.classify(r"D:\Projects\Example\固定资产\file.txt"), (None, None))
        self.assertEqual(MOD.classify(r"C:\Projects\ExampleOther\固定资产\file.txt"), (None, None))
        self.assertTrue(MOD.decide({"tool_name": "exec_command", "cwd": str(MOD.ROOT),
                                  "tool_input": {"cmd": r"Set-Content 'c:\PROJECTS\example\固定资产\file.txt' test"}}))

    def test_unc_and_extended_path(self):
        MOD.ROOT = r"\\server\share\Project"
        self.assertEqual(MOD.classify(r"\\SERVER\SHARE\project\固定资产\file.txt")[0], "readonly")
        self.assertEqual(MOD.classify(r"\\server\other\Project\固定资产\file.txt"), (None, None))
        self.assertEqual(MOD.classify(r"\\?\UNC\server\share\Project\固定资产\file.txt")[0], "readonly")
        MOD.ROOT = r"C:\Projects\Example"
        self.assertEqual(MOD.classify(r"\\?\C:\Projects\Example\固定资产\file.txt")[0], "readonly")

    def test_windows_variables_and_relative_paths(self):
        MOD.ROOT = r"C:\Projects\Example"
        self.assertEqual(str(MOD.resolve(r".\agents\..\固定资产\file.txt", MOD.ROOT)), r"C:\Projects\Example\固定资产\file.txt")
        self.assertEqual(str(MOD.resolve(r"$PWD\固定资产\file.txt", MOD.ROOT)), r"C:\Projects\Example\固定资产\file.txt")
        self.assertIsNone(MOD.resolve(r"$unknown\file.txt", MOD.ROOT))


if __name__ == "__main__":
    unittest.main(verbosity=2)
