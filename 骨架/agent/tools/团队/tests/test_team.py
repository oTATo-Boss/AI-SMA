"""团队工具的隔离测试：在临时目录里复制角色包和脚本，不碰真实项目。"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1]
AGENT = TOOLS.parents[1]


class TeamToolTests(unittest.TestCase):
    def setUp(self):
        parent = Path(os.environ.get("OTATO_TEST_ARTIFACT_DIR", tempfile.gettempdir()))
        parent.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix="team-", dir=parent)
        self.root = Path(self.temporary.name)
        shutil.copytree(AGENT / "团队", self.root / "agent/团队")
        shutil.copytree(TOOLS, self.root / "agent/tools/团队", ignore=shutil.ignore_patterns("tests", "__pycache__"))
        (self.root / "agent/账号数据/爆款库").mkdir(parents=True)

    def tearDown(self):
        self.temporary.cleanup()

    def run_tool(self, name, *args):
        return subprocess.run([sys.executable, str(self.root / "agent/tools/团队" / name), *args],
                              capture_output=True, text=True, cwd=self.root)

    def write(self, relative, data):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return path

    def base(self, kind, **fields):
        return dict({"artifact": kind, "task": "测试任务", "version": 1, "owner": "tester",
                     "created_at": "2026-10-15 10:00", "evidence_refs": []}, **fields)

    def test_generate_and_check_adapters(self):
        result = self.run_tool("生成角色.py")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        claude = sorted((self.root / ".claude/agents").glob("*.md"))
        codex = sorted((self.root / ".codex/agents").glob("*.toml"))
        self.assertEqual(len(claude), 8)
        self.assertEqual(len(codex), 8)
        critic = (self.root / ".claude/agents/creative-critic.md").read_text(encoding="utf-8")
        self.assertTrue(critic.startswith("---\nname: creative-critic\n"))
        self.assertIn("disallowedTools: Agent", critic)
        self.assertIn("tools: Read, Write, Bash", critic)
        self.assertIn("agent/团队/创意评审/经验.md", critic)
        try:
            import tomllib
        except ImportError:
            tomllib = None
        if tomllib:
            data = tomllib.loads((self.root / ".codex/agents/creative-critic.toml").read_text(encoding="utf-8"))
            self.assertEqual(data["name"], "creative-critic")
            self.assertIn("盲评", data["developer_instructions"])
        self.assertEqual(self.run_tool("生成角色.py", "--check").returncode, 0)
        role = self.root / "agent/团队/审片/角色.md"
        role.write_text(role.read_text(encoding="utf-8") + "\n补一句。\n", encoding="utf-8")
        result = self.run_tool("生成角色.py", "--check")
        self.assertEqual(result.returncode, 1)
        self.assertIn("不是最新", result.stdout)

    def test_role_definition_problems_are_reported(self):
        (self.root / "agent/团队/坏角色").mkdir()
        (self.root / "agent/团队/坏角色/角色.md").write_text("---\nname: 坏\n---\n正文\n", encoding="utf-8")
        result = self.run_tool("生成角色.py", "--check")
        self.assertEqual(result.returncode, 1)
        self.assertIn("缺少 id", result.stdout)

    def test_artifact_validation(self):
        self.write("agent/账号数据/爆款库/xhs-20261015-01.json", self.base(
            "viral-reference", id="xhs-20261015-01", platform="小红书", url="https://example.com/1", author="作者",
            published_at="2026-10-10", collected_at="2026-10-15 09:00", metrics={"点赞": 5000}, baseline={"点赞中位数": 800},
            outlier_ratio=6.25, media_reviewed=True, observed=["事实"], inferred=["推测"], transferable=["方法"]))
        good = self.write("agent/工作/测试任务/调研/机会简报.json", self.base(
            "opportunity-brief", evidence_refs=["xhs-20261015-01"], account_baseline="中位 380", gaps=[],
            opportunities=[{"topic": "主题", "why_now": "原因", "evidence_refs": ["xhs-20261015-01"],
                            "audience_signal": "信号", "mechanism_hints": ["机制"]}]))
        self.assertEqual(self.run_tool("校验产物.py", str(good)).returncode, 0)
        bad_ref = self.write("agent/工作/测试任务/调研/机会简报-坏.json", self.base(
            "opportunity-brief", evidence_refs=["xhs-20261015-99"], account_baseline="", gaps=[], opportunities=[]))
        result = self.run_tool("校验产物.py", str(bad_ref))
        self.assertEqual(result.returncode, 1)
        self.assertIn("爆款库没有条目", result.stdout)
        review = self.write("agent/工作/测试任务/创意/创意评审.json", self.base(
            "idea-review", blind=True, pick="C9", explore_pick=None, verdict="pass", required_changes=[], similarity_flags=[],
            scores=[{"candidate": "A1", "total": 28, "dimensions": {}, "risks": []}]))
        self.assertIn("pick 必须是打过分的候选之一", self.run_tool("校验产物.py", str(review)).stdout)
        video = self.root / "agent/工作/测试任务/产物/成片.mp4"
        video.parent.mkdir(parents=True)
        video.write_bytes(b"fixture-video")
        report = self.write("agent/工作/测试任务/检查/审片报告.json", self.base(
            "review-report", method={"frames": "每秒一帧"}, verdict="pass", defects=[], strengths=[], publishable=True,
            media={"path": "agent/工作/测试任务/产物/成片.mp4", "sha256": hashlib.sha256(b"fixture-video").hexdigest()}))
        self.assertEqual(self.run_tool("校验产物.py", str(report)).returncode, 0)
        video.write_bytes(b"changed-video")
        self.assertIn("成片在审片之后被改过", self.run_tool("校验产物.py", str(report)).stdout)
        update = self.write("agent/工作/测试任务/复盘/经验更新-20261020.json", self.base(
            "experience-update", mechanism="预期反转", evidence=[], sample_size=2, window="7 天", confidence="medium",
            status="verified", recommendation="多做"))
        self.assertIn("只能是 hypothesis", self.run_tool("校验产物.py", str(update)).stdout)
        result = self.run_tool("校验产物.py", "agent/工作/测试任务")
        self.assertIn("产物：", result.stdout)


if __name__ == "__main__":
    unittest.main()
