"""Isolated behavior fixtures; no network or production media writes."""
import copy
import os
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

RUNTIME = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("task_management", RUNTIME / "任务管理.py")
MOD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MOD)


class TaskManagementTests(unittest.TestCase):
    def setUp(self):
        parent = Path(os.environ.get("OTATO_TEST_ARTIFACT_DIR", str(RUNTIME / "tests/.fixtures")))
        parent.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix="fixture-", dir=parent)
        self.root = Path(self.temporary.name)
        self.runtime = self.root / "agents/role/总负责人/工具/任务管理"
        for folder in ["模板"]:
            (self.runtime / folder).mkdir(parents=True)
        (self.root / "agents/工作").mkdir(parents=True)
        for folder in ["交付", "发布内容", "固定资产"]:
            (self.root / folder).mkdir()
        for name in ["任务管理.py", "流程定义.json", "模板/任务.json"]:
            shutil.copy2(RUNTIME / name, self.runtime / name)
        self.workspace = MOD.Workspace(self.root)

    def tearDown(self):
        self.temporary.cleanup()

    def cli(self, *args, ok=True):
        result = subprocess.run([sys.executable, str(self.runtime / "任务管理.py"), *args], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0 if ok else 1, result.stdout + result.stderr)
        return result.stdout

    def create(self, name="任务", workflow="maintenance"):
        output = self.cli("new", "--title", name, "--workflow", workflow, "--goal", "测试目标", "--done-when", "测试完成条件")
        return output.strip()

    def read(self, task):
        return json.loads((self.root / task).read_text())

    def operation(self, task, command, *args, ok=True):
        return self.cli(command, task, "--revision", str(self.read(task)["revision"]), *args, ok=ok)

    def evidence(self, task, name, text):
        path = Path(task).parent / name
        (self.root / path).parent.mkdir(parents=True, exist_ok=True)
        (self.root / path).write_text(text)
        return str(path)

    def pass_team_checks(self, task):
        self.operation(task, "authorize", "--scope", "测试内容", "--source", "测试本人来源")
        review = self.evidence(task, "创意/创意评审.json", '{"verdict": "pass"}')
        self.operation(task, "check", "--name", "创意评审", "--result", "passed", "--evidence", review, "--summary", "过线")
        film = self.evidence(task, "检查/审片报告.json", '{"verdict": "pass"}')
        self.operation(task, "check", "--name", "成片审查", "--result", "passed", "--evidence", film, "--summary", "通过")

    def package(self, name):
        folder = self.root / "交付" / name
        folder.mkdir()
        (folder / "视频.mp4").write_bytes(b"\x00\x00\x00\x18ftypisom" + b"fixture")
        (folder / "封面.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"fixture")
        (folder / "发布文案.txt").write_text("测试文案")
        return "交付/" + name

    def test_create_authorize_and_resume(self):
        task = self.create(workflow="research")
        self.operation(task, "update", "--status", "进行中", ok=False)
        self.operation(task, "authorize", "--scope", "已授权研究", "--source", "测试本人任务要求")
        self.operation(task, "update", "--phase", "取证", "--status", "进行中", "--next", "等待证据")
        restarted = MOD.Workspace(self.root)
        self.assertEqual(restarted.validate(self.read(task))[0], [])
        self.assertEqual(self.read(task)["next_action"], "等待证据")
        self.assertTrue((self.root / Path(task).parent / "运行记录.jsonl").is_file())
        self.assertIn("进行中", (self.root / "agents/工作/任务总览.md").read_text())

    def test_stale_write_does_not_overwrite(self):
        task = self.create()
        old_revision = self.read(task)["revision"]
        self.operation(task, "update", "--next", "最新下一步")
        before = (self.root / task).read_bytes()
        self.cli("update", task, "--revision", str(old_revision), "--next", "旧版本覆盖", ok=False)
        self.assertEqual((self.root / task).read_bytes(), before)

    def test_confirmation_required_and_invalidated(self):
        task = self.create(workflow="research")
        self.operation(task, "authorize", "--scope", "定位研究", "--source", "测试本人来源")
        self.operation(task, "gate", "--key", "positioning", "--title", "定位方案确认", "--before-phase", "沉淀",
                       "--decision", "pending", "--source", "等本人确认定位")
        self.operation(task, "update", "--phase", "分析", "--status", "进行中")
        self.operation(task, "update", "--phase", "沉淀", ok=False)
        plan = self.evidence(task, "定位与对标方案.md", "测试方案 v1")
        self.operation(task, "gate", "--key", "positioning", "--decision", "approved", "--source", "测试本人确认", "--subject", plan)
        self.operation(task, "update", "--phase", "沉淀")
        (self.root / plan).write_text("测试方案 v2")
        self.cli("validate", task, ok=False)
        self.operation(task, "gate", "--key", "positioning", "--decision", "pending", "--source", "核心方案变更，需要新确认")
        self.assertEqual(self.read(task)["phase"], "分析")
        self.assertEqual(self.read(task)["status"], "等待本人")
        self.operation(task, "gate", "--key", "positioning", "--decision", "approved", "--source", "测试 v2 本人确认", "--subject", plan)
        self.operation(task, "update", "--phase", "沉淀", "--status", "进行中")

    def test_delivery_acceptance_is_bound_to_version(self):
        task = self.create(workflow="content")
        self.pass_team_checks(task)
        self.operation(task, "update", "--phase", "交付")
        first = self.package("版本一")
        self.operation(task, "delivery", "--path", first, "--kind", "social-video", "--source", "测试实际交付")
        self.operation(task, "update", "--status", "结束", ok=False)
        report = Path(task).parent / "检查.json"
        (self.root / report).write_text('{"fixture_check": "passed"}')
        self.operation(task, "check", "--name", "测试文件", "--result", "passed", "--evidence", str(report), "--summary", "测试检查")
        self.operation(task, "accept", "--decision", "approved", "--source", "测试本人对版本一的验收")
        self.operation(task, "update", "--status", "结束", "--next", "")
        second = self.package("版本二")
        self.operation(task, "delivery", "--path", second, "--kind", "social-video", "--source", "测试修订交付")
        self.assertEqual(self.read(task)["acceptance"]["status"], "待验收")
        self.assertEqual(len(self.read(task)["deliveries"]), 2)
        (self.root / second / "发布文案.txt").write_text("非法修改旧交付")
        self.cli("validate", task, ok=False)

    def test_path_and_package_protection(self):
        target = self.root / "固定资产/原件.txt"
        target.write_text("原件")
        for value in ["固定资产/原件.txt", "发布内容/新文件", "交付/新文件", "../越界", "agents/.env"]:
            with self.assertRaises(MOD.TaskError):
                self.workspace.path(value, write=True)
        link = self.root / "agents/链接"
        link.symlink_to(self.root / "固定资产", target_is_directory=True)
        with self.assertRaises(MOD.TaskError):
            self.workspace.path("agents/链接/原件.txt", write=True)
        hard = self.root / "agents/硬链接.txt"
        os.link(target, hard)  # Path.hardlink_to 要 Python 3.10，模板支持 3.9
        with self.assertRaises(MOD.TaskError):
            self.workspace.path("agents/硬链接.txt", write=True)
        package = self.package("已存在")
        self.cli("check-package", package, "--kind", "social-video", "--new-name", "已存在", ok=False)
        (self.root / package / "检查.json").write_text("{}")
        self.cli("check-package", package, "--kind", "social-video", ok=False)
        self.assertEqual(target.read_text(), "原件")

    def test_migration_is_not_new_execution_permission(self):
        task = self.create(workflow="research")
        self.operation(task, "gate", "--key", "positioning", "--title", "定位方案确认", "--before-phase", "沉淀",
                       "--decision", "pending", "--source", "等本人确认定位")
        data = self.read(task)
        data.update(phase="沉淀", status="等待本人", migration={"source": "旧记录", "historical_confirmations": "unknown"})
        for gate in data["gates"]:
            gate["decision"] = "unknown"
        (self.root / task).write_text(json.dumps(data, ensure_ascii=False))
        errors, warnings = self.workspace.validate(data)
        self.assertEqual(errors, [])
        self.assertTrue(warnings)
        data.update(phase="分析")
        (self.root / task).write_text(json.dumps(data, ensure_ascii=False))
        self.operation(task, "update", "--phase", "沉淀", "--status", "进行中", ok=False)

    def test_invalid_record_and_missing_evidence_rejected(self):
        task = self.create()
        data = self.read(task)
        bad = copy.deepcopy(data)
        bad["workflow"] = []
        self.assertTrue(self.workspace.validate(bad)[0])
        bad = copy.deepcopy(data)
        bad["acceptance"]["status"] = []
        self.assertTrue(self.workspace.validate(bad)[0])
        self.operation(task, "check", "--name", "无证据", "--result", "passed", "--summary", "测试", ok=False)
        self.operation(task, "update", "--phase", "沉淀", "--status", "结束", ok=False)

    def test_two_task_ids_are_distinct(self):
        first = self.create("任务一")
        second = self.create("任务二")
        self.assertNotEqual(self.read(first)["id"], self.read(second)["id"])
        self.cli("validate-all")

    def test_sync_uses_only_canonical_overview_and_group_tables(self):
        active = self.create("当前任务")
        waiting = self.create("等待任务")
        self.operation(waiting, "update", "--status", "等待本人")
        cancelled = self.create("取消任务")
        self.operation(cancelled, "update", "--status", "取消")
        self.cli("sync")
        text = (self.root / "agents/工作/任务总览.md").read_text()
        for group in ("进行中", "等待", "取消"):
            self.assertIn("## " + group + "\n\n| 任务 |", text)
        self.assertFalse((self.root / "agents/任务总览.md").exists())
        self.assertFalse((self.root / "agents/运行").exists())
        self.assertFalse((self.root / "agents/发布记录.md").exists())

    def test_empty_overview_has_a_valid_table(self):
        self.cli("sync")
        text = (self.root / "agents/工作/任务总览.md").read_text()
        self.assertIn("|---|---|---|---|---|---|", text)
        self.assertIn("暂无登记任务", text)

    def test_independent_delivery_requires_no_new_video_script(self):
        task = self.create("独立包装", workflow="delivery")
        self.assertEqual(self.read(task)["gates"], [])
        self.operation(task, "authorize", "--scope", "已有作品补发布材料", "--source", "测试本人明确要求")
        self.operation(task, "update", "--phase", "制作材料", "--status", "进行中")
        package = self.package("独立包装交付")
        self.operation(task, "update", "--phase", "交付")
        self.operation(task, "delivery", "--path", package, "--kind", "social-video", "--source", "测试实际交付")
        self.operation(task, "update", "--status", "结束", ok=False)
        report = Path(task).parent / "包装检查.json"
        (self.root / report).write_text('{"fixture_packaging": "passed"}')
        self.operation(task, "check", "--name", "包装检查", "--result", "passed", "--evidence", str(report), "--summary", "测试检查")
        self.operation(task, "accept", "--decision", "approved", "--source", "测试本人验收")
        self.operation(task, "update", "--status", "结束", "--next", "")
        self.assertEqual(self.read(task)["status"], "结束")

    def test_outputs_may_include_root_entry_but_not_read_only(self):
        task = self.create("根目录入口")
        (self.root / "AGENTS.md").write_text("入口")
        self.operation(task, "update", "--output", "AGENTS.md")
        (self.root / "固定资产/原件.txt").write_text("原件")
        self.operation(task, "update", "--output", "固定资产/原件.txt", ok=False)

    def test_overview_links_are_relative(self):
        task = self.create("相对链接")
        text = (self.root / "agents/工作/任务总览.md").read_text()
        self.assertIn("](<" + Path(task).parent.name + "/task.json>)", text)
        self.assertNotIn(str(self.root), text)

    def test_job_registers_without_revision(self):
        task = self.create(workflow="content")
        receipt = self.evidence(task, "工程/回执.json", '{"taskId": "rh-1"}')
        result = subprocess.run([sys.executable, str(self.runtime / "任务管理.py"), "job", task, "--tool", "RunningHub",
                                 "--task-id", "rh-1", "--status", "submitted", "--record", receipt], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.cli("job", task, "--tool", "RunningHub", "--task-id", "rh-1", "--status", "succeeded", "--record", receipt, "--cost", "12 RH币")
        jobs = self.read(task)["external_jobs"]
        self.assertEqual(len(jobs), 1)
        self.assertEqual((jobs[0]["status"], jobs[0]["cost"]), ("succeeded", "12 RH币"))
        self.cli("job", task, "--tool", "RunningHub", "--task-id", "rh-2", "--status", "submitted", "--record", receipt)
        self.assertEqual(len(self.read(task)["external_jobs"]), 2)
        self.cli("job", task, "--tool", "RunningHub", "--task-id", "rh-3", "--status", "submitted", "--record", "agents/没有.json", ok=False)
        self.cli("validate", task)
        review = self.evidence(task, "创意/创意评审.json", '{"verdict": "pass"}')
        self.operation(task, "authorize", "--scope", "测试", "--source", "测试本人来源")
        self.operation(task, "check", "--name", "创意评审", "--result", "passed", "--evidence", review, "--summary", "过线")
        (self.root / review).write_text('{"verdict": "pass", "改过": true}')
        self.cli("validate", task, ok=False)
        output = self.cli("job", task, "--tool", "RunningHub", "--task-id", "rh-4", "--status", "submitted", "--record", receipt)
        self.assertIn("原有问题", output)
        self.assertEqual(len(self.read(task)["external_jobs"]), 3)

    def test_gate_with_unknown_phase_is_rejected_cleanly(self):
        task = self.create(workflow="research")
        output = self.cli("gate", task, "--revision", str(self.read(task)["revision"]), "--key", "positioning", "--title", "定位方案确认",
                          "--before-phase", "不存在的阶段", "--decision", "pending", "--source", "测试", ok=False)
        self.assertIn("确认的阶段不属于这个任务的流程", output)

    def test_content_required_checks_block_phases(self):
        task = self.create(workflow="content")
        self.assertEqual(self.read(task)["gates"], [])
        self.operation(task, "authorize", "--scope", "一句话做视频", "--source", "测试本人来源")
        self.operation(task, "update", "--phase", "创意", "--status", "进行中", "--next", "出创意")
        self.operation(task, "update", "--phase", "方案", "--next", "写方案", ok=False)
        review = Path(task).parent / "创意评审.json"
        (self.root / review).write_text('{"verdict": "pass"}')
        self.operation(task, "check", "--name", "创意评审", "--result", "failed", "--evidence", str(review), "--summary", "未过线")
        self.operation(task, "update", "--phase", "方案", "--next", "写方案", ok=False)
        self.operation(task, "check", "--name", "创意评审", "--result", "passed", "--evidence", str(review), "--summary", "过线")
        self.operation(task, "update", "--phase", "方案", "--next", "写方案")
        self.operation(task, "update", "--phase", "交付", "--next", "打包", ok=False)
        (self.root / review).write_text('{"verdict": "pass", "改过": true}')
        errors, _ = self.workspace.validate(self.read(task))
        self.assertTrue(any("证据版本已变化" in e for e in errors), errors)

    def test_definition_drives_timezone_choices_and_packages(self):
        definition_path = self.runtime / "流程定义.json"
        definition = json.loads(definition_path.read_text())
        definition["project"]["timezone"] = "UTC"
        definition["packages"]["social-video"] = ["成片.mp4", "封面.png", "文案.txt"]
        definition_path.write_text(json.dumps(definition, ensure_ascii=False))
        task = self.create("配置驱动")
        self.assertTrue(self.read(task)["created_at"].endswith("+00:00"))
        rejected = subprocess.run([sys.executable, str(self.runtime / "任务管理.py"), "new", "--title", "x", "--workflow", "未定义",
                                   "--goal", "g", "--done-when", "d"], capture_output=True, text=True)
        self.assertNotEqual(rejected.returncode, 0)
        folder = self.root / "交付/自定义包"
        folder.mkdir()
        (folder / "成片.mp4").write_bytes(b"\x00\x00\x00\x18ftypisom" + b"fixture")
        (folder / "封面.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"fixture")
        (folder / "文案.txt").write_text("测试文案")
        self.cli("check-package", "交付/自定义包", "--kind", "social-video")
        (folder / "多余.txt").write_text("不该出现")
        self.cli("check-package", "交付/自定义包", "--kind", "social-video", ok=False)


if __name__ == "__main__":
    unittest.main(verbosity=2)
