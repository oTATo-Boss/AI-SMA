"""写入拦截的行为测试：只在临时夹具里判断，不执行任何被检查的命令。"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
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
        (self.root / "agents/链接").symlink_to(self.root / "固定资产", target_is_directory=True)
        self.original_root, MOD.ROOT = MOD.ROOT, self.root

    def tearDown(self):
        MOD.ROOT = self.original_root
        self.temporary.cleanup()

    def edit(self, tool, path, key="file_path"):
        return MOD.decide({"tool_name": tool, "tool_input": {key: str(self.root / path)}, "cwd": str(self.root)})

    def bash(self, command):
        return MOD.decide({"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(self.root)})

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
        denied = subprocess.run([sys.executable, str(SCRIPT)], input=json.dumps(payload), capture_output=True, text=True)
        self.assertEqual(denied.returncode, 0, denied.stderr)
        output = json.loads(denied.stdout)["hookSpecificOutput"]
        self.assertEqual((output["hookEventName"], output["permissionDecision"]), ("PreToolUse", "deny"))
        payload["tool_input"]["command"] = "ls 固定资产"
        allowed = subprocess.run([sys.executable, str(SCRIPT)], input=json.dumps(payload), capture_output=True, text=True)
        self.assertEqual((allowed.returncode, allowed.stdout), (0, ""))


if __name__ == "__main__":
    unittest.main(verbosity=2)
