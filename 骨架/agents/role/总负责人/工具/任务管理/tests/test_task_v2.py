"""v2 依赖、恢复和跨平台公共接口的隔离行为测试。"""
import copy
import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

import test_task_management as legacy

MOD = legacy.MOD


class TaskV2Tests(unittest.TestCase):
    tearDown = legacy.TaskManagementTests.tearDown
    cli = legacy.TaskManagementTests.cli
    create = legacy.TaskManagementTests.create
    read = legacy.TaskManagementTests.read
    operation = legacy.TaskManagementTests.operation
    evidence = legacy.TaskManagementTests.evidence

    def setUp(self):
        legacy.TaskManagementTests.setUp(self)
        config = self.root / "agents/项目/项目配置.yaml"
        config.parent.mkdir()
        config.write_text(json.dumps({"schema_version": 2, "team": {"execution_mode": "single"}}))
        validator = self.root / "agents/公共/工具/团队/校验产物.py"
        validator.parent.mkdir(parents=True)
        shutil.copy2(legacy.RUNTIME.parents[3] / "公共/工具/团队/校验产物.py", validator)
        self.workspace = MOD.Workspace(self.root)

    def review(self, subject, mode="self"):
        evidence = self.workspace.evidence(subject)
        return {"schema_version": 2, "artifact": "review-report", "task": "fixture", "version": 1, "owner": "reviewer",
                "created_at": "2026-10-16 12:00", "evidence_refs": [], "files": [], "inputs": [evidence], "media": evidence,
                "producer": "writer", "producer_run": "run-1", "reviewer_run": "run-2" if mode == "independent" else "run-1",
                "review_mode": mode, "method": {}, "verdict": "pass", "defects": [], "strengths": [], "publishable": True}

    def test_v2_default_and_v1_read_compatibility(self):
        task = self.create()
        data = self.read(task)
        self.assertEqual((data["schema_version"], data["review_mode"]), (2, "self"))
        old = copy.deepcopy(data)
        old["schema_version"] = 1
        for field in MOD.V2_FIELDS:
            old.pop(field)
        (self.root / task).write_text(json.dumps(old))
        self.cli("validate", task)
        self.operation(task, "update", "--next", "旧任务继续工作")
        self.assertEqual(self.read(task)["schema_version"], 1)

    def test_dependency_change_invalidates_and_refresh_clears_checks(self):
        upstream = self.create("剧本")
        script = self.evidence(upstream, "剧本.md", "第一版")
        self.operation(upstream, "update", "--output", script)
        child = self.cli("new", "--title", "分镜", "--workflow", "maintenance", "--goal", "分镜", "--done-when", "可拍",
                         "--parent-id", self.read(upstream)["id"], "--depends-on", self.read(upstream)["id"],
                         "--unit-type", "scene", "--unit-id", "S01").strip()
        report = self.evidence(child, "检查.txt", "通过")
        self.operation(child, "check", "--name", "结构", "--result", "passed", "--evidence", report, "--summary", "已检查")
        (self.root / script).write_text("第二版")
        self.assertIn("上游输入已失效", self.cli("validate", child, ok=False))
        self.operation(child, "update", "--phase", "沉淀", ok=False)
        self.operation(child, "refresh-inputs", "--source", "剧本第二版改变结尾，需要重新制作分镜")
        data = self.read(child)
        self.assertEqual(data["checks"], [])
        self.assertEqual((data["phase"], data["status"]), ("查现状", "待开始"))
        self.cli("validate", child)

    def test_output_manifest_changes_and_dependency_cycles(self):
        first = self.create("上游")
        output = self.evidence(first, "A.txt", "A")
        self.operation(first, "update", "--output", output)
        child = self.cli("new", "--title", "下游", "--workflow", "maintenance", "--goal", "g", "--done-when", "d",
                         "--depends-on", self.read(first)["id"]).strip()
        extra = self.evidence(first, "B.txt", "B")
        self.operation(first, "update", "--output", extra)
        self.assertIn("清单已变化", self.cli("validate", child, ok=False))
        data = self.read(first)
        data["depends_on"] = [self.read(child)["id"]]
        (self.root / first).write_text(json.dumps(data))
        self.assertIn("形成循环", self.cli("validate", first, ok=False))

    def test_intent_unknown_and_resume_never_create_second_job(self):
        task = self.create()
        request = self.evidence(task, "请求.json", '{"prompt":"test"}')
        self.cli("job-intent", task, "--tool", "test-service", "--submission-key", "S01-v1", "--request", request)
        self.cli("job-intent", task, "--tool", "test-service", "--submission-key", "S01-v1", "--request", request, ok=False)
        self.cli("job", task, "--tool", "test-service", "--submission-key", "S01-v1", "--status", "unknown", "--record", request)
        recovery = json.loads(self.cli("job-recover", task, "--submission-key", "S01-v1"))
        self.assertEqual((len(recovery), recovery[0]["status"], recovery[0]["task_id"]), (1, "unknown", None))
        self.cli("job", task, "--tool", "test-service", "--submission-key", "S01-v1", "--task-id", "remote-1", "--status", "submitted", "--record", request)
        self.cli("job", task, "--tool", "test-service", "--submission-key", "S01-v1", "--task-id", "remote-2", "--status", "submitted", "--record", request, ok=False)
        self.assertEqual(len(self.read(task)["external_jobs"]), 1)

    def test_phase_objects_and_independent_review_requirement(self):
        path = self.runtime / "流程定义.json"
        data = json.loads(path.read_text())
        data["workflows"]["review"] = {"phases": [{"id": "draft", "name": "制作", "owners": ["writer"], "requires": []},
                                                          {"id": "deliver", "name": "交付", "owners": ["reviewer"], "requires": ["draft"]}],
                                                  "required_checks": [{"name": "终审", "before_phase": "deliver", "requires_independent": True}]}
        path.write_text(json.dumps(data))
        task = self.create("独立终审", "review")
        subject = self.evidence(task, "作品.txt", "subject")
        report = self.evidence(task, "检查.json", json.dumps(self.review(subject, "independent")))
        self.operation(task, "check", "--name", "终审", "--result", "passed", "--evidence", report,
                       "--summary", "自检", "--review-mode", "self", ok=False)
        self.operation(task, "check", "--name", "终审", "--result", "passed", "--evidence", report,
                       "--summary", "独立", "--review-mode", "independent")
        self.operation(task, "update", "--phase", "deliver")
        self.assertEqual(self.read(task)["phase"], "交付")

    def test_media_mutation_invalidates_unchanged_review_report(self):
        task = self.create()
        video = self.evidence(task, "片段.mp4", "fixture")
        report_data = self.review(video)
        report = self.evidence(task, "审片.json", json.dumps(report_data))
        self.operation(task, "check", "--name", "审片", "--result", "passed", "--evidence", report, "--summary", "自检")
        (self.root / video).write_text("different")
        self.assertIn("证据版本已变化", self.cli("validate", task, ok=False))

    def test_lock_contention_and_release(self):
        task = self.create()
        code = ("import importlib.util,pathlib; "
                "s=importlib.util.spec_from_file_location('m'," + repr(str(self.runtime / "任务管理.py")) + "); "
                "m=importlib.util.module_from_spec(s); s.loader.exec_module(m); "
                "w=m.Workspace(" + repr(str(self.root)) + "); "
                "lock=w.locked(w.task_path(" + repr(task) + ")); lock.__enter__(); lock.__exit__(None,None,None)")
        with self.workspace.locked(self.workspace.task_path(task)):
            result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("正在被另一进程编辑", result.stderr)
        self.assertEqual(subprocess.run([sys.executable, "-c", code], capture_output=True).returncode, 0)

    def test_windows_names_paths_and_directory_delivery(self):
        for name in ("CON", "COM1.txt", "trailing.", "bad\\name"):
            self.cli("new", "--title", name, "--workflow", "maintenance", "--goal", "g", "--done-when", "d", ok=False)
        for value in ("C:/Windows/file", "..\\outside", "\\\\server\\share"):
            with self.assertRaises(MOD.TaskError):
                self.workspace.path(value)
        self.workspace.packages["film"] = {"required": ["母版.mp4", "源码"], "optional": ["字幕.srt"], "allow_extra": False}
        folder = self.root / "交付/测试"
        (folder / "源码").mkdir(parents=True)
        (folder / "母版.mp4").write_bytes(b"\0\0\0\x18ftypisom" + b"fixture")
        (folder / "源码/a.py").write_text("print('source')")
        package = self.workspace.package("交付/测试", "film")
        self.assertEqual(set(package["files"]), {"母版.mp4", "源码/a.py"})


if __name__ == "__main__":
    unittest.main()
