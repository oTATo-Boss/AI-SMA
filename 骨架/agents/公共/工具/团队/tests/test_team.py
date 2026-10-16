"""团队工具的隔离测试：在临时目录里复制智能体包和脚本，不碰真实项目。"""
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
AGENTS = Path(__file__).resolve().parents[4]

try:
    import tomllib
except ImportError:  # Python 3.9、3.10 没有 tomllib，跳过 TOML 解析断言
    tomllib = None


class TeamToolTests(unittest.TestCase):
    def setUp(self):
        parent = Path(os.environ.get("OTATO_TEST_ARTIFACT_DIR", tempfile.gettempdir()))
        parent.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix="team-", dir=parent)
        self.root = Path(self.temporary.name)
        shutil.copytree(AGENTS / "role", self.root / "agents/role", ignore=shutil.ignore_patterns("__pycache__", "tests"))
        shutil.copytree(TOOLS, self.root / "agents/公共/工具/团队", ignore=shutil.ignore_patterns("tests", "__pycache__"))
        (self.root / "agents/账号/爆款库").mkdir(parents=True)
        shutil.copy2(AGENTS / "账号/账号配置.yaml", self.root / "agents/账号/账号配置.yaml")

    def tearDown(self):
        self.temporary.cleanup()

    def run_tool(self, name, *args):
        return subprocess.run([sys.executable, str(self.root / "agents/公共/工具/团队" / name), *args],
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
        self.assertEqual(len(list((self.root / ".claude/agents").glob("*.md"))), 8)
        self.assertEqual(len(list((self.root / ".codex/agents").glob("*.toml"))), 8)
        self.assertFalse((self.root / ".claude/agents/account-lead.md").exists())
        critic = (self.root / ".claude/agents/creative-critic.md").read_text(encoding="utf-8")
        self.assertTrue(critic.startswith("---\nname: creative-critic\n"))
        self.assertIn("disallowedTools: Agent", critic)
        self.assertIn("tools: Read, Write, Bash", critic)
        self.assertIn("agents/role/创意评审/AGENT.md", critic)
        self.assertIn("agents/role/创意评审/记忆/经验.md", critic)
        if tomllib:
            data = tomllib.loads((self.root / ".codex/agents/creative-critic.toml").read_text(encoding="utf-8"))
            self.assertEqual(data["name"], "creative-critic")
            self.assertEqual(data["model_reasoning_effort"], "xhigh")
            self.assertIn("agents/role/创意评审/AGENT.md", data["developer_instructions"])
            config = tomllib.loads((self.root / ".codex/config.toml").read_text(encoding="utf-8"))
            self.assertEqual(config["agents"]["max_concurrent_threads_per_session"], 3)
            self.assertTrue(config["sandbox_workspace_write"]["network_access"])
        self.assertEqual(self.run_tool("生成角色.py", "--check").returncode, 0)
        guide = self.root / "agents/role/审片/AGENT.md"
        guide.write_text(guide.read_text(encoding="utf-8") + "\n补一句。\n", encoding="utf-8")
        self.assertEqual(self.run_tool("生成角色.py", "--check").returncode, 0, "改说明书不需要重新生成")
        card = self.root / "agents/role/审片/agent.yaml"
        card.write_text(card.read_text(encoding="utf-8").replace("effort: xhigh", "effort: high"), encoding="utf-8")
        result = self.run_tool("生成角色.py", "--check")
        self.assertEqual(result.returncode, 1)
        self.assertIn("不是最新", result.stdout)
        config = self.root / "agents/账号/账号配置.yaml"
        config.write_text(config.read_text(encoding="utf-8").replace("max_parallel_agents: 3", "max_parallel_agents: 2"), encoding="utf-8")
        config.write_text(config.read_text(encoding="utf-8").replace("network_commands: true", "network_commands: false"), encoding="utf-8")
        self.run_tool("生成角色.py")
        written = (self.root / ".codex/config.toml").read_text(encoding="utf-8")
        self.assertIn("max_concurrent_threads_per_session = 2", written)
        self.assertNotIn("network_access", written)

    def test_package_problems_are_reported(self):
        bad = self.root / "agents/role/坏角色"
        bad.mkdir()
        (bad / "agent.yaml").write_text("# 注释行可以有\nname: 坏\n这一行不对\n", encoding="utf-8")
        result = self.run_tool("生成角色.py", "--check")
        self.assertEqual(result.returncode, 1)
        for message in ("缺少 id", "缺少 AGENT.md", "缺少 记忆/经验.md", "配置行格式不对"):
            self.assertIn(message, result.stdout)
        shutil.copytree(self.root / "agents/role/导演", self.root / "agents/role/导演副本")
        self.assertIn("编号重复", self.run_tool("生成角色.py", "--check").stdout)

    def test_user_codex_config_is_kept(self):
        (self.root / ".codex").mkdir()
        (self.root / ".codex/config.toml").write_text('model = "自己的设置"\n', encoding="utf-8")
        result = self.run_tool("生成角色.py")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("没有覆盖", result.stdout)
        self.assertEqual((self.root / ".codex/config.toml").read_text(encoding="utf-8"), 'model = "自己的设置"\n')
        self.assertEqual(self.run_tool("生成角色.py", "--check").returncode, 0)

    def test_artifact_validation(self):
        entry = dict(platform="小红书", url="https://example.com/1", author="作者", published_at="2026-10-10",
                     collected_at="2026-10-15 09:00", metrics={"点赞": 5000}, baseline={"点赞中位数": 800}, outlier_ratio=6.25,
                     media_reviewed=True, observed=["事实"], inferred=["推测"], transferable=["方法"])
        self.write("agents/账号/爆款库/xhs-20261015-01.json", self.base("viral-reference", id="xhs-20261015-01", **entry))
        self.write("agents/账号/爆款库/xhs-20261015-a01.json", self.base("viral-reference", id="xhs-20261015-a01", **entry))
        good = self.write("agents/工作/测试任务/调研/机会简报.json", self.base(
            "opportunity-brief", evidence_refs=["xhs-20261015-01", "xhs-20261015-a01"], account_baseline="中位 380", gaps=[],
            opportunities=[{"topic": "主题", "why_now": "原因", "evidence_refs": ["xhs-20261015-01"],
                            "audience_signal": "信号", "mechanism_hints": ["机制"]}]))
        self.assertEqual(self.run_tool("校验产物.py", str(good)).returncode, 0)
        bad_ref = self.write("agents/工作/测试任务/调研/机会简报-坏.json", self.base(
            "opportunity-brief", evidence_refs=["xhs-20261015-99", "xhs-20261015-b07"], account_baseline="", gaps=[], opportunities=[]))
        result = self.run_tool("校验产物.py", str(bad_ref))
        self.assertEqual(result.returncode, 1)
        self.assertIn("爆款库没有条目 xhs-20261015-99", result.stdout)
        self.assertIn("爆款库没有条目 xhs-20261015-b07", result.stdout)
        review = self.write("agents/工作/测试任务/创意/创意评审.json", self.base(
            "idea-review", blind=True, pick="C9", explore_pick=None, verdict="pass", required_changes=[], similarity_flags=[],
            scores=[{"candidate": "A1", "total": 28, "dimensions": {}, "risks": []}]))
        self.assertIn("pick 必须是打过分的候选之一", self.run_tool("校验产物.py", str(review)).stdout)
        video = self.root / "agents/工作/测试任务/产物/成片.mp4"
        video.parent.mkdir(parents=True)
        video.write_bytes(b"fixture-video")
        report = self.write("agents/工作/测试任务/检查/审片报告.json", self.base(
            "review-report", method={"frames": "每秒一帧"}, verdict="pass", defects=[], strengths=[], publishable=True,
            media={"path": "agents/工作/测试任务/产物/成片.mp4", "sha256": hashlib.sha256(b"fixture-video").hexdigest()}))
        self.assertEqual(self.run_tool("校验产物.py", str(report)).returncode, 0)
        video.write_bytes(b"changed-video")
        self.assertIn("成片在审片之后被改过", self.run_tool("校验产物.py", str(report)).stdout)
        update = self.write("agents/工作/测试任务/复盘/经验更新-20261020.json", self.base(
            "experience-update", mechanism="预期反转", evidence=[], sample_size=2, window="7 天", confidence="medium",
            status="verified", recommendation="多做"))
        self.assertIn("只能是 hypothesis", self.run_tool("校验产物.py", str(update)).stdout)
        result = self.run_tool("校验产物.py", "agents/工作/测试任务")
        self.assertIn("产物：", result.stdout)

    def test_blind_candidates_archives_and_null_lists(self):
        candidate = dict(one_liner="一句话", hook="钩子", beats=[], payoff="回报", why="原因", evidence_refs=[],
                         borrowed_mechanism="机制", difference_from_source="差别", feasibility="可行")
        good = self.write("agents/工作/盲评任务/创意/盲评候选.json", self.base(
            "blind-candidates", candidates=[dict(candidate, id="a1"), dict(candidate, id="b1")]))
        self.assertEqual(self.run_tool("校验产物.py", str(good)).returncode, 0)
        bad = self.write("agents/工作/盲评任务/创意/盲评候选-坏.json", self.base(
            "blind-candidates", method="原创发散", candidates=[dict(candidate, id="a1"), dict(candidate, id="a1")]))
        output = self.run_tool("校验产物.py", str(bad)).stdout
        self.assertIn("不能写 method", output)
        self.assertIn("编号有重复", output)
        bad.unlink()
        broken = self.write("agents/工作/盲评任务/创意/创意评审.json", self.base(
            "idea-review", blind=True, pick="a1", explore_pick=None, verdict="pass", required_changes=[], similarity_flags=[], scores=None))
        result = self.run_tool("校验产物.py", str(broken))
        self.assertEqual(result.returncode, 1)
        self.assertNotIn("Traceback", result.stderr)
        self.assertIn("scores 必须是列表", result.stdout)
        broken.unlink()
        video = self.root / "agents/工作/盲评任务/产物/成片.mp4"
        video.parent.mkdir(parents=True)
        video.write_bytes(b"new-cut")
        self.write("agents/工作/盲评任务/检查/审片报告.v1.json", self.base(
            "review-report", method={}, verdict="rework", defects=None, strengths=[], publishable=False,
            media={"path": "agents/工作/盲评任务/产物/成片.mp4", "sha256": hashlib.sha256(b"old-cut").hexdigest()}))
        result = self.run_tool("校验产物.py", "agents/工作/盲评任务")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertNotIn("审片报告.v1.json", result.stdout)


if __name__ == "__main__":
    unittest.main()
