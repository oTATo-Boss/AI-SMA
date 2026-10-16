#!/usr/bin/env python3
"""Local task records. Standard library only; never writes protected directories."""
import argparse
import copy
import hashlib
import importlib.util
import json
import os
import re
import tempfile
import time
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path, PureWindowsPath
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

if os.name == "nt":
    import msvcrt
else:
    import fcntl


class TaskError(ValueError):
    pass


def project_zone(name):
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError as exc:
        raise TaskError(f"缺少时区数据 {name}；使用当前 Python 安装 tzdata 后重试") from exc


ZONE = None  # Workspace 从流程定义设置；不在模块加载时依赖系统时区库。
V2_FIELDS = {"parent_id", "depends_on", "unit", "input_versions", "review_mode"}
JOB_STATES = {"intent", "unknown", "submitted", "running", "succeeded", "failed", "cancelled"}


def portable_name(name):
    return (bool(name) and name not in {".", ".."} and not re.search(r'[<>:"/\\|?*\x00-\x1f]', name)
            and name == name.rstrip(" .")
            and not re.fullmatch(r"(?i)(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?", name))


def acquire_lock(stream):
    if os.name == "nt":
        stream.seek(0)
        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)


def release_lock(stream):
    if os.name == "nt":
        stream.seek(0)
        msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        fcntl.flock(stream, fcntl.LOCK_UN)


def now():
    return datetime.now(ZONE).isoformat(timespec="seconds")


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise TaskError(f"无法读取 JSON：{path.name}（{type(exc).__name__}）") from exc


class Workspace:
    def __init__(self, root):
        global ZONE
        self.root = Path(root).resolve()
        self.agent = self.root / "agents"
        self.runtime = self.agent / "role/总负责人/工具/任务管理"
        self.definition = load_json(self.runtime / "流程定义.json")
        # 类型注册表允许带 id/owner/依赖的阶段；旧记录仍保存可读阶段名。
        for workflow in self.definition["workflows"].values():
            phases = workflow["phases"]
            workflow["phase_definitions"] = [p if isinstance(p, dict) else {"id": p, "name": p} for p in phases]
            workflow["phases"] = [p["name"] for p in workflow["phase_definitions"]]
            aliases = {p["id"]: p["name"] for p in workflow["phase_definitions"]}
            workflow.setdefault("gates", [])
            workflow.setdefault("required_checks", [])
            workflow.setdefault("requires_acceptance", False)
            for rule in workflow["gates"] + workflow["required_checks"]:
                rule["before_phase"] = aliases.get(rule["before_phase"], rule["before_phase"])
        project = self.definition.get("project", {})
        self.work = self.root / project.get("work_dir", "agents/工作")
        self.delivery_root = self.root / project.get("delivery_dir", "交付")
        self.overview_path = self.root / project.get("overview", "agents/工作/任务总览.md")
        self.packages = self.definition.get("packages", {"social-video": ["视频.mp4", "封面.png", "发布文案.txt"]})
        self.read_only = [self.root / d for d in project.get("read_only_dirs", ["发布内容", "固定资产"])]
        ZONE = project_zone(project.get("timezone", "Asia/Shanghai"))
        config = self.agent / "项目/项目配置.yaml"
        self.project_config = load_json(config) if config.exists() else {}
        self.version = 2 if self.project_config.get("schema_version") == 2 or self.definition.get("schema_version") == 2 else 1
        mode = self.project_config.get("team", {}).get("execution_mode", "native")
        self.review_mode = "self" if mode in {"single", "serial", "single-agent", "single_agent"} else "independent"

    def path(self, value, *, write=False, exists=False):
        if not isinstance(value, str) or not value:
            raise TaskError("路径必须为非空的项目相对路径")
        relative = Path(value)
        if relative.is_absolute() or PureWindowsPath(value).is_absolute() or "\\" in value or ".." in relative.parts:
            raise TaskError("路径必须相对项目根目录，不能包含 ..")
        if any(part.startswith(".env") or part in {"credentials", ".git"} for part in relative.parts):
            raise TaskError("任务路径不能引用凭据或 Git 内部文件")
        path = self.root / relative
        cursor = self.root
        for part in relative.parts:
            cursor = cursor / part
            if cursor.is_symlink() or (cursor.exists() and getattr(cursor.lstat(), "st_file_attributes", 0) & 0x400):
                raise TaskError(f"路径不能经过软链接：{value}")
        resolved = path.resolve()
        if not resolved.is_relative_to(self.root):
            raise TaskError("路径离开项目目录")
        if write:
            if not resolved.is_relative_to(self.agent):
                raise TaskError("管理工具只允许写 agents/，不能写受保护目录")
            if path.is_file() and path.stat().st_nlink > 1:
                raise TaskError("不能写入硬链接文件")
        if exists and not path.exists():
            raise TaskError(f"路径不存在：{value}")
        return path

    def relative(self, path):
        return Path(path).relative_to(self.root).as_posix()

    def phase_name(self, workflow, value):
        return next((p["name"] for p in self.definition["workflows"][workflow]["phase_definitions"] if p["id"] == value), value)

    def task_path(self, value):
        path = self.path(value, write=True, exists=True)
        if path.is_dir():
            path = path / "task.json"
        relative = path.relative_to(self.work) if path.is_relative_to(self.work) else Path()
        if len(relative.parts) != 2 or path.name != "task.json":
            raise TaskError(f"任务必须是 {self.relative(self.work)}/<任务>/task.json")
        return self.path(self.relative(path), write=True, exists=True)

    def records(self):
        # Do not recurse through media, engines, dependency trees or history.
        return [self.task_path(self.relative(p)) for p in sorted(self.work.glob("*/task.json"))]

    def atomic(self, path, content):
        path = self.path(self.relative(path), write=True)
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix=".task-write-", dir=path.parent)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def evidence(self, value):
        path = self.path(value, exists=True)
        if not path.is_file():
            raise TaskError("确认和检查证据必须指向具体文件")
        return {"path": value, "sha256": sha256(path)}

    def evidence_error(self, evidence):
        if not isinstance(evidence, dict) or set(evidence) != {"path", "sha256"}:
            return "证据需要 path 和 sha256"
        if not isinstance(evidence["sha256"], str) or not re.fullmatch(r"[a-f0-9]{64}", evidence["sha256"]):
            return "证据哈希格式错误"
        try:
            if self.evidence(evidence["path"]) != evidence:
                return f"证据版本已变化：{evidence['path']}"
        except TaskError as exc:
            return str(exc)
        return None

    def package(self, value, kind, new_name=None):
        if kind not in set(self.packages) | {"prompt", "other"}:
            raise TaskError("未知交付包类型")
        folder = self.path(value, exists=True)
        if not folder.is_dir():
            raise TaskError("交付包必须是目录")
        if not (folder.is_relative_to(self.work) or folder.is_relative_to(self.delivery_root)):
            raise TaskError("交付包只能在工作区或交付目录内")
        entries = sorted(folder.iterdir())
        if not entries:
            raise TaskError("交付包为空")
        package_rule = self.packages.get(kind)
        expected = package_rule if isinstance(package_rule, list) else None
        if expected is not None and {p.name for p in entries} != set(expected):
            raise TaskError(f"{kind} 包应只含：" + "、".join(expected))
        if isinstance(package_rule, dict):
            required = package_rule.get("required", [])
            optional = package_rule.get("optional", [])
            names = {p.name for p in entries}
            if not set(required) <= names:
                raise TaskError("交付包缺少：" + "、".join(sorted(set(required) - names)))
            if not package_rule.get("allow_extra", False) and names - set(required + optional):
                raise TaskError("交付包有未定义的内容：" + "、".join(sorted(names - set(required + optional))))
            expected = [p.name for p in entries if p.is_file()]
            descendants = sorted(folder.rglob("*"))
            for item in descendants:
                self.path(self.relative(item), exists=True)
            entries = [p for p in descendants if p.is_file()]
            if not entries:
                raise TaskError("交付包缺少实际文件")
        files = {}
        for path in entries:
            self.path(self.relative(path), exists=True)
            if not path.is_file() or path.stat().st_nlink > 1 or path.stat().st_size == 0:
                raise TaskError(f"交付文件必须是非空独立文件：{path.name}")
            if kind == "prompt" and path.suffix.lower() not in {".txt", ".png", ".jpg", ".jpeg", ".webp"}:
                raise TaskError("提示词包只能含 txt 与参考图")
            files[path.relative_to(folder).as_posix()] = sha256(path)
        if kind == "prompt" and not any(p.suffix.lower() == ".txt" for p in entries):
            raise TaskError("提示词包缺少 txt")
        for name in expected or []:
            item = folder / name
            if item.suffix.lower() == ".mp4":
                with item.open("rb") as stream:
                    if stream.read(12)[4:8] != b"ftyp":
                        raise TaskError(f"{name} 文件头不是 MP4")
            elif item.suffix.lower() == ".png":
                with item.open("rb") as stream:
                    if stream.read(8) != b"\x89PNG\r\n\x1a\n":
                        raise TaskError(f"{name} 文件头不是 PNG")
            elif item.suffix.lower() == ".txt":
                try:
                    if not item.read_text(encoding="utf-8").strip():
                        raise TaskError(f"{name} 为空")
                except UnicodeError as exc:
                    raise TaskError(f"{name} 应为 UTF-8 文本") from exc
        if new_name:
            if not portable_name(new_name):
                raise TaskError("新交付名称不能包含路径")
            target = self.path(self.relative(self.delivery_root / new_name))
            if target.exists():
                raise TaskError("同名交付已存在，不能合并、追加或覆盖")
        return {"path": value, "kind": kind, "files": files}

    def task_index(self):
        result = {}
        for path in self.records():
            data = load_json(path)
            if not isinstance(data, dict) or not isinstance(data.get("id"), str) or not data["id"]:
                raise TaskError("关联任务缺少有效 ID：" + self.relative(path))
            if data.get("id") in result:
                raise TaskError("重复任务 ID")
            result[data.get("id")] = data
        return result

    def snapshot(self, value, task_id=None):
        record = self.evidence(value)
        if task_id:
            record["task_id"] = task_id
        path = self.path(value, exists=True)
        if path.suffix == ".json":
            try:
                data = load_json(path)
                if isinstance(data, dict) and data.get("artifact") and isinstance(data.get("version"), int):
                    record["artifact_version"] = data["version"]
            except TaskError:
                pass
        return record

    def dependency_snapshots(self, dependencies):
        index, records = self.task_index(), []
        for task_id in dependencies:
            if task_id not in index:
                raise TaskError("前置任务不存在：" + task_id)
            for value in index[task_id].get("outputs", []):
                path = self.path(value, exists=True)
                files = [path] if path.is_file() else sorted(path.rglob("*"))
                for item in files:
                    if item.is_file():
                        records.append(self.snapshot(self.relative(item), task_id))
        return records

    def relation_errors(self, task):
        errors = []
        if task.get("parent_id") is not None and (not isinstance(task["parent_id"], str) or not task["parent_id"]):
            return ["parent_id 必须是任务 ID 或 null"]
        if not isinstance(task.get("depends_on"), list) or any(not isinstance(i, str) or not i for i in task.get("depends_on", [])):
            return errors + ["depends_on 必须是任务 ID 列表"]
        if len(task["depends_on"]) != len(set(task["depends_on"])):
            errors.append("depends_on 不能重复")
        unit = task.get("unit")
        if unit is not None and (not isinstance(unit, dict) or not isinstance(unit.get("type"), str) or not isinstance(unit.get("id"), str) or not unit["id"].strip() or unit["type"] not in {"project", "episode", "chapter", "sequence", "scene", "shot", "work-package"}):
            errors.append("unit 需要有效的 type 和非空 id")
        if task.get("review_mode") not in ("self", "independent"):
            errors.append("review_mode 只能是 self 或 independent")
        if not isinstance(task.get("input_versions"), list):
            return errors + ["input_versions 必须是版本证据列表"]
        try:
            index = self.task_index()
        except TaskError as exc:
            return errors + [str(exc)]
        index[task["id"]] = task
        for relation in [task.get("parent_id"), *task["depends_on"]]:
            if relation and relation not in index:
                errors.append("关联任务不存在：" + relation)
            elif relation == task["id"]:
                errors.append("任务不能依赖或包含自身")
        def cyclic(node, chain, field):
            if node in chain:
                return True
            record = index.get(node, {})
            edges = record.get(field, []) if field == "depends_on" else [record.get(field)]
            if not isinstance(edges, list) or any(child is not None and not isinstance(child, str) for child in edges):
                errors.append("关联任务的 " + field + " 格式错误")
                return False
            return any(cyclic(child, chain | {node}, field) for child in edges if child and child in index)
        for field in ("parent_id", "depends_on"):
            if cyclic(task["id"], set(), field):
                errors.append(field + " 关系形成循环")
        for version in task["input_versions"]:
            if not isinstance(version, dict):
                errors.append("input_versions 每项必须是对象")
                continue
            error = self.evidence_error({k: version.get(k) for k in ("path", "sha256")})
            if error:
                errors.append("上游输入已失效，需要复核：" + error)
            upstream = version.get("task_id")
            if upstream is not None and (not isinstance(upstream, str) or not upstream):
                errors.append("输入版本 task_id 必须是非空任务 ID")
            if upstream and upstream not in task["depends_on"]:
                errors.append("输入版本的 task_id 必须属于 depends_on")
        if errors:
            return errors
        try:
            current = self.dependency_snapshots(task["depends_on"])
            recorded = [v for v in task["input_versions"] if isinstance(v, dict) and v.get("task_id")]
            key = lambda v: (v.get("task_id", ""), v.get("path", ""))
            if sorted(current, key=key) != sorted(recorded, key=key):
                errors.append("前置任务产物版本或清单已变化，需要 refresh-inputs 后重新检查")
        except TaskError as exc:
            errors.append(str(exc))
        if isinstance(task["status"], str) and task["status"] in {"进行中", "结束"}:
            bound = {v.get("task_id") for v in task["input_versions"] if isinstance(v, dict)}
            for dependency in task["depends_on"]:
                if dependency not in bound:
                    errors.append("前置任务尚无绑定产物：" + dependency)
        return errors

    def validate(self, task):
        errors, warnings = [], []
        if not isinstance(task, dict):
            return ["任务必须是对象"], warnings
        template = load_json(self.runtime / "模板/任务.json")
        version = task.get("schema_version")
        required = (set(template) - V2_FIELDS) | (V2_FIELDS if version == 2 else set())
        missing = required - set(task)
        if missing:
            return ["任务缺少字段：" + ", ".join(sorted(missing))], warnings
        if isinstance(version, bool) or version not in (1, 2):
            errors.append("不支持的任务版本")
        for field in ["id", "title", "goal", "owner", "created_at", "updated_at"]:
            if not isinstance(task[field], str) or not task[field].strip():
                errors.append(f"{field} 必须是非空字符串")
        if not isinstance(task["revision"], int) or isinstance(task["revision"], bool) or task["revision"] < 1:
            errors.append("revision 必须是正整数")
        for field in ["created_at", "updated_at"]:
            try:
                stamp = datetime.fromisoformat(task[field])
                if stamp.utcoffset() is None:
                    raise ValueError()
            except (TypeError, ValueError):
                errors.append(f"{field} 必须含时区")
        if not isinstance(task["done_when"], list) or not task["done_when"] or any(not isinstance(s, str) or not s.strip() for s in task["done_when"]):
            errors.append("done_when 需要至少一个完成条件")
        for field in ["inputs", "outputs", "approvals", "gates", "checks", "deliveries", "external_jobs", "issues"]:
            if not isinstance(task[field], list):
                errors.append(f"{field} 必须是数组")
        if errors:
            return errors, warnings
        if version == 2:
            errors += self.relation_errors(task)
        for field in ["workflow", "phase", "status", "next_action"]:
            if not isinstance(task[field], str):
                errors.append(f"{field} 必须是字符串")
        if task["migration"] is not None and (not isinstance(task["migration"], dict) or not task["migration"].get("source")):
            errors.append("旧任务迁移需要明确来源")
        if any(not isinstance(issue, str) for issue in task["issues"]):
            errors.append("issues 必须是文字条目")
        if errors:
            return errors, warnings
        workflow = self.definition["workflows"].get(task["workflow"])
        if not workflow:
            return ["未知流程"], warnings
        if task["phase"] not in workflow["phases"]:
            errors.append("阶段不属于所选流程")
        if task["status"] not in self.definition["statuses"]:
            errors.append("未知执行状态")
        if not isinstance(task["next_action"], str) or (task["status"] not in {"结束", "取消"} and not task["next_action"].strip()):
            errors.append("未结束任务必须写下一步或恢复条件")
        for field in ["inputs", "outputs"]:
            for value in task[field]:
                try:
                    path = self.path(value, exists=True)
                    if field == "outputs" and any(path.is_relative_to(d) for d in self.read_only):
                        errors.append("outputs 不能指向只读目录：" + value)
                except TaskError as exc:
                    errors.append(str(exc))
        gates = {}
        for gate in task["gates"]:
            if not isinstance(gate, dict) or not {"key", "title", "before_phase", "decision", "source", "subject", "at"}.issubset(gate):
                errors.append("确认字段不完整")
                continue
            if not all(isinstance(gate[k], str) for k in ["key", "title", "before_phase", "decision", "source", "at"]):
                errors.append("确认文字字段类型错误")
                continue
            if gate["key"] in gates:
                errors.append("重复确认 key")
            gates[gate["key"]] = gate
            if gate["before_phase"] not in workflow["phases"] or gate["decision"] not in {"pending", "approved", "rejected", "unknown"}:
                errors.append("确认阶段或结果错误")
            if gate["decision"] in {"approved", "rejected"} and not gate["source"].strip():
                errors.append("确认必须有本人原话或可定位的来源")
            if gate["key"] == "positioning" and gate["decision"] == "approved" and gate["subject"] is None:
                errors.append("定位确认必须绑定具体的方案文件版本")
            if gate["subject"] is not None:
                error = self.evidence_error(gate["subject"])
                if error and gate["decision"] == "approved":
                    errors.append(error + "；受影响确认需要重新取得")
                elif error:
                    warnings.append(error)
        for requirement in workflow["gates"]:
            if requirement["key"] not in gates:
                errors.append("缺少流程确认：" + requirement["title"])
            elif gates[requirement["key"]]["before_phase"] != requirement["before_phase"]:
                errors.append("不能改变流程必经确认的阶段")
        if not errors and task["phase"] in workflow["phases"]:
            for gate in gates.values():
                if workflow["phases"].index(task["phase"]) >= workflow["phases"].index(gate["before_phase"]):
                    if gate["decision"] != "approved":
                        message = "当前阶段之前的确认未取得：" + gate["title"]
                        if task["migration"] and task["status"] in {"等待本人", "结束", "取消"}:
                            warnings.append("旧任务历史待核实：" + message)
                        else:
                            errors.append(message)
        if task["phase"] in workflow["phases"]:
            passed = {c.get("name") for c in task["checks"] if isinstance(c, dict) and c.get("result") == "passed" and c.get("evidence")}
            for requirement in workflow.get("required_checks", []):
                if workflow["phases"].index(task["phase"]) >= workflow["phases"].index(requirement["before_phase"]) and requirement["name"] not in passed:
                    errors.append(f"进入「{requirement['before_phase']}」前需要通过检查：{requirement['name']}")
        for approval in task["approvals"]:
            if not isinstance(approval, dict) or not isinstance(approval.get("source"), str) or not approval["source"].strip() or not isinstance(approval.get("scope"), str) or not approval["scope"].strip():
                errors.append("任务授权缺少范围或来源")
        if task["status"] == "进行中" and not task["approvals"]:
            errors.append("执行前需要登记已有任务授权")
        for check in task["checks"]:
            if not isinstance(check, dict) or not {"name", "result", "evidence", "summary"}.issubset(check):
                errors.append("检查字段不完整")
                continue
            if not isinstance(check["result"], str) or check["result"] not in {"passed", "failed", "unverified"}:
                errors.append("未知检查结果")
            if check["evidence"] is not None:
                error = self.evidence_error(check["evidence"])
                if error:
                    errors.append(error)
            elif check["result"] == "passed":
                errors.append("检查通过必须有具体版本证据")
            if version == 2:
                mode = check.get("review_mode", task["review_mode"])
                if mode not in {"self", "independent"}:
                    errors.append("检查 review_mode 必须是 self 或 independent")
                requirement = next((r for r in workflow.get("required_checks", []) if r["name"] == check["name"]), {})
                if check["result"] == "passed" and requirement.get("requires_independent") and mode != "independent":
                    errors.append("此检查需要独立评审：" + check["name"])
                if check["result"] == "passed" and check.get("evidence"):
                    errors += self.review_evidence_errors(check, mode, requirement.get("requires_independent", False))
        for delivery in task["deliveries"]:
            try:
                if not isinstance(delivery, dict) or not {"path", "kind", "files", "source"}.issubset(delivery):
                    raise TaskError("交付记录不完整")
                fresh = self.package(delivery["path"], delivery["kind"])
                if fresh["files"] != delivery["files"]:
                    errors.append("交付文件与登记版本不一致：" + delivery["path"])
                if not delivery["source"]:
                    errors.append("交付记录缺少来源")
            except TaskError as exc:
                errors.append(str(exc))
        acceptance = task["acceptance"]
        if not isinstance(acceptance, dict) or not isinstance(acceptance.get("status"), str) or acceptance.get("status") not in {"不适用", "待验收", "已通过", "需修订"}:
            errors.append("验收状态错误")
        else:
            if workflow["requires_acceptance"] and acceptance["status"] == "不适用":
                errors.append("内容任务必须保留本人验收状态")
            if acceptance["status"] in {"已通过", "需修订"}:
                if not acceptance.get("source") or not task["deliveries"]:
                    errors.append("本人验收需要来源和交付版本")
                elif not isinstance(task["deliveries"][-1], dict) or acceptance.get("subject") != {"path": task["deliveries"][-1].get("path"), "files": task["deliveries"][-1].get("files")}:
                    errors.append("本人验收必须对应当前交付版本")
        submission_keys = set()
        for job in task["external_jobs"]:
            if not isinstance(job, dict) or not {"tool", "task_id", "status", "record"}.issubset(job):
                errors.append("外部任务缺少工具、ID、状态或回包位置")
            elif job["record"]:
                try:
                    self.path(job["record"], exists=True)
                except TaskError as exc:
                    errors.append(str(exc))
            if isinstance(job, dict) and job.get("submission_key"):
                key = job["submission_key"]
                if not isinstance(key, str):
                    errors.append("submission_key 必须是文字")
                    continue
                if key in submission_keys:
                    errors.append("submission_key 重复")
                submission_keys.add(key)
                if job.get("status") not in JOB_STATES:
                    errors.append("提交意图的状态无效")
                if job.get("status") in {"submitted", "running", "succeeded"} and not job.get("task_id"):
                    errors.append("已提交的外部任务需要真实 task_id")
                error = self.evidence_error(job.get("request"))
                if error:
                    errors.append("提交请求证据失效：" + error)
        if task["status"] == "结束":
            if task["phase"] != workflow["phases"][-1]:
                errors.append("结束任务必须处于流程末阶段")
            if not task["outputs"]:
                errors.append("结束任务必须关联成果")
            if not task["checks"] or any(c.get("result") == "failed" for c in task["checks"]):
                errors.append("结束前需要检查记录并解决失败项")
            if not any(c.get("result") == "passed" for c in task["checks"]):
                errors.append("结束前需要至少一项有证据的检查通过")
            if workflow["requires_acceptance"] and (not task["deliveries"] or acceptance.get("status") != "已通过"):
                errors.append("内容结束需要当前交付及本人验收通过")
        if task["issues"]:
            warnings.append("任务有未解决项或限制，请读取 issues")
        return errors, warnings

    def review_evidence_errors(self, check, mode, require_independent=False):
        """v2 评审绑定产物本身，不只检查报告 JSON 未改动。"""
        try:
            path = self.path(check["evidence"]["path"], exists=True)
            if path.suffix != ".json":
                return ["独立评审必须提供 v2 结构化评审报告"] if require_independent else []
            data = load_json(path)
            contract_errors = []
            validator = self.agent / "公共/工具/团队/校验产物.py"
            if isinstance(data, dict) and data.get("artifact") and validator.is_file():
                spec = importlib.util.spec_from_file_location("task_artifact_contract", validator)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                contract_errors = module.validate_file(path)
            if not isinstance(data, dict) or data.get("artifact") not in {"review-report", "idea-review"}:
                return contract_errors + (["独立评审必须提供 v2 结构化评审报告"] if require_independent else [])
            errors = contract_errors
            if data.get("schema_version") != 2 or data.get("review_mode") != mode:
                errors.append("v2 评审报告需要 schema_version=2 且 review_mode 与登记一致")
            if data.get("verdict") != "pass":
                errors.append("检查通过需要 verdict=pass 的评审报告")
            if mode == "independent" and (not data.get("producer_run") or not data.get("reviewer_run") or data["producer_run"] == data["reviewer_run"]):
                errors.append("独立评审需要不同的 producer_run 和 reviewer_run")
            if mode == "independent" and (not data.get("producer") or not data.get("owner") or data["producer"] == data["owner"]):
                errors.append("独立评审需要不同的 producer 和 owner")
            if not isinstance(data.get("inputs"), list) or not data["inputs"]:
                errors.append("评审需要绑定被评产物的 inputs 哈希")
            if data["artifact"] == "review-report" and not isinstance(data.get("media"), dict):
                errors.append("审片报告必须绑定 media 文件与哈希")
            for evidence in [data.get("media"), *data.get("inputs", [])]:
                if evidence is not None:
                    problem = self.evidence_error(evidence)
                    if problem:
                        errors.append(problem)
            return errors
        except (TaskError, TypeError) as exc:
            return ["评审证据无法验证：" + str(exc)]

    @contextmanager
    def locked(self, task_path, wait=0):
        """单任务编辑锁；wait 秒内拿不到就报错（0 表示不等）。"""
        lock = self.path(self.relative(task_path.parent / ".task.lock"), write=True)
        with lock.open("a+b") as stream:
            if lock.stat().st_size == 0:
                stream.write(b"\0")
                stream.flush()
            deadline = time.monotonic() + wait
            while True:
                try:
                    acquire_lock(stream)
                    break
                except OSError as exc:
                    if time.monotonic() >= deadline:
                        raise TaskError("任务正在被另一进程编辑，重新读取后再试") from exc
                    time.sleep(0.1)
            try:
                yield
            finally:
                release_lock(stream)

    def mutate(self, value, revision, action, change, wait=0, tolerate_existing=False):
        """revision 为 None 时不核对版本；tolerate_existing 时任务原有的问题不挡住这次写入（只用于 job 这种只追加的登记）。"""
        path = self.task_path(value)
        with self.locked(path, wait):
            original = load_json(path)
            if revision is not None and original.get("revision") != revision:
                raise TaskError("任务版本冲突，重新读取当前 revision 后再写")
            task = copy.deepcopy(original)
            change(task)
            task["revision"] += 1
            task["updated_at"] = now()
            errors, warnings = self.validate(task)
            if errors and tolerate_existing:
                existing = set(self.validate(original)[0])
                added = [e for e in errors if e not in existing]
                if not added:
                    warnings = warnings + ["任务原有问题，这次登记没有新增：" + "；".join(errors)]
                errors = added
            if errors:
                raise TaskError("；".join(errors))
            self.atomic(path, json.dumps(task, ensure_ascii=False, indent=2) + "\n")
            journal = self.path(self.relative(path.parent / "运行记录.jsonl"), write=True)
            entry = {"at": task["updated_at"], "action": action, "revision": task["revision"], "owner": task["owner"], "phase": task["phase"], "status": task["status"]}
            # Retain changed values as history, not another current-state source.
            entry["changes"] = {k: {"before": original.get(k), "after": task[k]} for k in task if original.get(k) != task[k]}
            with journal.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(entry, ensure_ascii=False) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            self.overview()
            return task, warnings

    def new(self, title, workflow, goal, done_when, owner, parent_id=None, depends_on=None, unit=None, review_mode=None):
        if not portable_name(title):
            raise TaskError("任务名称不能为空或包含路径")
        definition = self.definition["workflows"][workflow]
        task = load_json(self.runtime / "模板/任务.json")
        version = 2 if self.version == 2 or parent_id or depends_on or unit or review_mode else 1
        task["schema_version"] = version
        if version == 2:
            task.update(parent_id=parent_id, depends_on=depends_on or [], unit=unit, review_mode=review_mode or self.review_mode,
                        input_versions=self.dependency_snapshots(depends_on or []))
        else:
            for key in V2_FIELDS:
                task.pop(key, None)
        stamp = datetime.now(ZONE).strftime("%Y%m%d_%H%M%S")
        directory = self.path(self.relative(self.work / (stamp + "_" + title)), write=True)
        task.update(id=stamp + "-" + uuid.uuid4().hex[:8], title=title, workflow=workflow, goal=goal, done_when=done_when, phase=definition["phases"][0], next_action="读取对应流程，检查已有授权与输入，明确下一步。", owner=owner, created_at=now(), updated_at=now())
        task["acceptance"]["status"] = "待验收" if definition["requires_acceptance"] else "不适用"
        task["gates"] = [dict(gate, decision="pending", source="", subject=None, at="") for gate in definition["gates"]]
        errors, _ = self.validate(task)
        if errors:
            raise TaskError("；".join(errors))
        if directory.exists():
            raise TaskError("任务目录已存在，先检查是否同题，不合并或覆盖")
        existing_ids = {load_json(p).get("id") for p in self.records()}
        if task["id"] in existing_ids:
            raise TaskError("任务 ID 冲突，稍后创建")
        directory.mkdir()
        self.atomic(directory / "task.json", json.dumps(task, ensure_ascii=False, indent=2) + "\n")
        self.overview()
        return task, self.relative(directory / "task.json")

    def overview(self):
        rows, ids = [], set()
        for path in self.records():
            task = load_json(path)
            errors, warnings = self.validate(task)
            if task.get("id") in ids:
                errors.append("重复任务 ID")
            ids.add(task.get("id"))
            rows.append((path, task, errors, warnings))
        order = {"进行中": 0, "待开始": 1, "等待本人": 2, "等待外部": 3, "受阻": 4, "结束": 5, "取消": 6}
        rows.sort(key=lambda row: (order.get(row[1].get("status"), 9), row[1].get("updated_at", ""), str(row[0])))
        base = self.overview_path.parent
        script = os.path.relpath(self.runtime / "任务管理.py", base)
        lines = ["# 任务总览", "", f"由 `{script} sync` 生成，不手动维护。当前状态以各任务 `task.json` 为准。", "", "生成时间：" + now()]
        def cell(value):
            return str(value).replace("|", "／").replace("\n", " ").replace("[", "（").replace("]", "）")
        current_group = None
        for path, task, errors, warnings in rows:
            status = task.get("status")
            group = "进行中" if status in {"进行中", "待开始"} else "结束" if status == "结束" else "取消" if status == "取消" else "等待"
            if group != current_group:
                lines.extend(["", "## " + group, "", "| 任务 | 类型／阶段 | 执行状态 | 当前交付／验收 | 下一步 | 记录检查 |", "|---|---|---|---|---|---|"])
                current_group = group
            label = self.definition["workflows"].get(task.get("workflow"), {}).get("label", "未知")
            link = os.path.relpath(path, base)  # 相对链接：项目整体移动或复制后仍有效
            delivery = task.get("deliveries", [])
            summary = (Path(delivery[-1]["path"]).name if delivery else "无登记交付") + "／" + task.get("acceptance", {}).get("status", "未知")
            health = "错误：" + "；".join(errors) if errors else "记录通过"
            if not errors and any("历史待核实" in item for item in warnings):
                health += "；历史确认未核实"
            if not errors and task.get("issues"):
                health += "；限制见任务"
            lines.append(f"| [{cell(task.get('title', path.parent.name))}](<{link}>) | {cell(label + '／' + task.get('phase', ''))} | {cell(task.get('status', ''))} | {cell(summary)} | {cell(task.get('next_action', ''))} | {cell(health)} |")
        if not rows:
            lines.extend(["", "| 任务 | 类型／阶段 | 执行状态 | 当前交付／验收 | 下一步 | 记录检查 |", "|---|---|---|---|---|---|"])
            lines.append("| 暂无登记任务 | — | — | — | — | — |")
        self.atomic(self.overview_path, "\n".join(lines) + "\n")
        return rows


def parser():
    definition = load_json(Path(__file__).resolve().parent / "流程定义.json")
    kinds = sorted(set(definition.get("packages", {"social-video": []})) | {"prompt", "other"})
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)
    create = sub.add_parser("new", help="新建任务")
    create.add_argument("--title", required=True)
    create.add_argument("--workflow", choices=list(definition["workflows"]), required=True)
    create.add_argument("--goal", required=True)
    create.add_argument("--done-when", action="append", required=True)
    create.add_argument("--owner", default="总负责人（当前对话）")
    create.add_argument("--parent-id")
    create.add_argument("--depends-on", action="append", default=[])
    create.add_argument("--unit-type", choices=["project", "episode", "chapter", "sequence", "scene", "shot", "work-package"])
    create.add_argument("--unit-id")
    create.add_argument("--review-mode", choices=["self", "independent"])
    for name in ["show", "validate", "update", "authorize", "gate", "check", "delivery", "accept", "refresh-inputs"]:
        cmd = sub.add_parser(name)
        cmd.add_argument("task", help="相对项目根目录的任务目录或 task.json")
        if name in {"update", "authorize", "gate", "check", "delivery", "accept", "refresh-inputs"}:
            cmd.add_argument("--revision", type=int, required=True)
        if name == "update":
            for field in ["phase", "status", "next", "owner"]:
                cmd.add_argument("--" + field)
            for field in ["input", "output", "issue"]:
                cmd.add_argument("--" + field, action="append", default=[])
        elif name == "authorize":
            cmd.add_argument("--scope", required=True)
            cmd.add_argument("--source", required=True)
        elif name == "gate":
            cmd.add_argument("--key", required=True)
            cmd.add_argument("--title")
            cmd.add_argument("--before-phase")
            cmd.add_argument("--decision", choices=["pending", "approved", "rejected", "unknown"], required=True)
            cmd.add_argument("--source", required=True)
            cmd.add_argument("--subject", help="本人确认的具体文件；定位方案确认（positioning）必须填写")
        elif name == "check":
            cmd.add_argument("--name", required=True)
            cmd.add_argument("--result", choices=["passed", "failed", "unverified"], required=True)
            cmd.add_argument("--evidence")
            cmd.add_argument("--summary", required=True)
            cmd.add_argument("--review-mode", choices=["self", "independent"])
        elif name == "delivery":
            cmd.add_argument("--path", required=True)
            cmd.add_argument("--kind", choices=kinds, required=True)
            cmd.add_argument("--source", required=True)
        elif name == "accept":
            cmd.add_argument("--decision", choices=["approved", "rejected"], required=True)
            cmd.add_argument("--source", required=True)
        elif name == "refresh-inputs":
            cmd.add_argument("--source", required=True, help="复核上游变更的记录或说明；重绑版本会清除旧检查并退回首阶段")
    job = sub.add_parser("job", help="登记或更新外部付费任务；不用 --revision，带锁，几个智能体同时登记也安全")
    job.add_argument("task", help="相对项目根目录的任务目录或 task.json")
    job.add_argument("--tool", required=True)
    job.add_argument("--task-id")
    job.add_argument("--submission-key", help="对应提交前已登记的意图；未知结果时用它恢复")
    job.add_argument("--status", required=True)
    job.add_argument("--record", required=True, help="回包或回执位置，相对项目根目录")
    job.add_argument("--cost", help="已知消耗；不知道就不写")
    intent = sub.add_parser("job-intent", help="调用外部服务前登记唯一提交意图，不调用服务")
    intent.add_argument("task")
    intent.add_argument("--tool", required=True)
    intent.add_argument("--submission-key", required=True)
    intent.add_argument("--request", required=True, help="已去除凭据的请求文件")
    recover = sub.add_parser("job-recover", help="只读列出外部提交状态；未知结果必须查服务，不能重提交")
    recover.add_argument("task")
    recover.add_argument("--submission-key")
    sub.add_parser("sync", help="生成任务总览")
    sub.add_parser("validate-all", help="检查所有当前任务")
    package = sub.add_parser("check-package", help="只读检查完整包及新名称冲突；不复制交付")
    package.add_argument("path")
    package.add_argument("--kind", choices=kinds, required=True)
    package.add_argument("--new-name")
    return p


def main():
    args = parser().parse_args()
    try:
        workspace = Workspace(Path(__file__).resolve().parents[5])
        if args.command == "new":
            if bool(args.unit_type) != bool(args.unit_id):
                raise TaskError("unit-type 与 unit-id 要一起填写")
            unit = {"type": args.unit_type, "id": args.unit_id} if args.unit_type else None
            _, path = workspace.new(args.title, args.workflow, args.goal, args.done_when, args.owner,
                                    args.parent_id, args.depends_on, unit, args.review_mode)
            print(path)
            return 0
        if args.command == "check-package":
            print(json.dumps(workspace.package(args.path, args.kind, args.new_name), ensure_ascii=False, indent=2))
            print("仅文件结构、文件头与哈希检查；媒体规格、内容和审美需另行检查。")
            return 0
        if args.command in {"sync", "validate-all"}:
            rows = workspace.overview() if args.command == "sync" else [(p, load_json(p), *workspace.validate(load_json(p))) for p in workspace.records()]
            ids, failed = set(), False
            for path, task, errors, warnings in rows:
                if task.get("id") in ids:
                    errors.append("重复任务 ID")
                ids.add(task.get("id"))
                failed |= bool(errors)
                print(json.dumps({"task": workspace.relative(path), "errors": errors, "warnings": warnings}, ensure_ascii=False))
            return 1 if failed else 0
        path = workspace.task_path(args.task)
        if args.command == "job-recover":
            jobs = load_json(path)["external_jobs"]
            print(json.dumps([j for j in jobs if not args.submission_key or j.get("submission_key") == args.submission_key], ensure_ascii=False, indent=2))
            return 0
        if args.command == "show":
            print(json.dumps(load_json(path), ensure_ascii=False, indent=2))
            return 0
        if args.command == "validate":
            errors, warnings = workspace.validate(load_json(path))
            print(json.dumps({"errors": errors, "warnings": warnings}, ensure_ascii=False, indent=2))
            return 1 if errors else 0

        def change(task):
            if args.command == "update":
                old_phase = task["phase"]
                for arg, key in [("phase", "phase"), ("status", "status"), ("next", "next_action"), ("owner", "owner")]:
                    if getattr(args, arg) is not None:
                        task[key] = workspace.phase_name(task["workflow"], args.phase) if arg == "phase" else getattr(args, arg)
                for arg, key in [("input", "inputs"), ("output", "outputs"), ("issue", "issues")]:
                    for item in getattr(args, arg):
                        if item not in task[key]:
                            task[key].append(item)
                        if arg == "input" and task["schema_version"] == 2:
                            if not any(v["path"] == item for v in task["input_versions"]):
                                task["input_versions"].append(workspace.snapshot(item))
                # Legacy history is not a license for new execution.
                if task["phase"] != old_phase and args.status not in {"取消"}:
                    definition = workspace.definition["workflows"][task["workflow"]]
                    if task["phase"] in definition["phases"]:
                        for gate in task["gates"]:
                            if definition["phases"].index(task["phase"]) >= definition["phases"].index(gate["before_phase"]) and gate["decision"] != "approved":
                                raise TaskError("新阶段必须取得确认：" + gate["title"])
                        passed = {c.get("name") for c in task["checks"] if c.get("result") == "passed" and c.get("evidence")}
                        for requirement in definition.get("required_checks", []):
                            if definition["phases"].index(task["phase"]) >= definition["phases"].index(requirement["before_phase"]) and requirement["name"] not in passed:
                                raise TaskError("进入新阶段前需要通过检查：" + requirement["name"])
            elif args.command == "authorize":
                if not args.scope.strip() or not args.source.strip():
                    raise TaskError("授权需要范围和本人来源")
                task["approvals"].append({"scope": args.scope, "source": args.source, "decision": "approved", "at": now()})
            elif args.command == "gate":
                if args.before_phase:
                    args.before_phase = workspace.phase_name(task["workflow"], args.before_phase)
                gate = next((g for g in task["gates"] if g["key"] == args.key), None)
                if gate is None:
                    if not args.title or not args.before_phase:
                        raise TaskError("新增确认需要 title 与 before-phase")
                    if args.before_phase not in workspace.definition["workflows"][task["workflow"]]["phases"]:
                        raise TaskError("确认的阶段不属于这个任务的流程：" + args.before_phase)
                    gate = {"key": args.key, "title": args.title, "before_phase": args.before_phase}
                    task["gates"].append(gate)
                if args.decision == "approved" and not args.source.strip():
                    raise TaskError("确认缺少本人来源")
                if args.key == "positioning" and args.decision == "approved" and not args.subject:
                    raise TaskError("定位确认必须绑定具体的方案文件版本")
                gate.update(decision=args.decision, source=args.source, subject=workspace.evidence(args.subject) if args.subject else None, at=now())
                if args.decision in {"pending", "rejected"}:
                    phases = workspace.definition["workflows"][task["workflow"]]["phases"]
                    before = phases.index(gate["before_phase"])
                    if phases.index(task["phase"]) >= before:
                        task["phase"] = phases[max(0, before - 1)]
                        task["status"] = "等待本人"
                        task["next_action"] = "修改受影响方案并取得确认：" + gate["title"]
            elif args.command == "check":
                record = {"name": args.name, "result": args.result, "evidence": workspace.evidence(args.evidence) if args.evidence else None, "summary": args.summary}
                if task["schema_version"] == 2:
                    record["review_mode"] = args.review_mode or task["review_mode"]
                task["checks"] = [c for c in task["checks"] if c["name"] != args.name] + [record]
            elif args.command == "delivery":
                record = dict(workspace.package(args.path, args.kind), source=args.source, at=now())
                if not workspace.path(args.path).is_relative_to(workspace.delivery_root):
                    raise TaskError("登记交付必须引用已新增到交付目录的完整包")
                if not args.source.strip():
                    raise TaskError("交付来源不能为空")
                if any(d["path"] == record["path"] for d in task["deliveries"]):
                    raise TaskError("同一交付已登记，不能重复登记或重写旧版本")
                task["deliveries"].append(record)
                if record["path"] not in task["outputs"]:
                    task["outputs"].append(record["path"])
                task["acceptance"] = {"status": "待验收", "source": "新交付版本等待本人验收", "subject": None}
                task["status"] = "等待本人"
                task["next_action"] = "本人验收当前交付后记录反馈或确认。"
            elif args.command == "accept":
                if not task["deliveries"] or not args.source.strip():
                    raise TaskError("本人验收需要当前交付和本人原话或出处")
                delivery = task["deliveries"][-1]
                task["acceptance"] = {"status": "已通过" if args.decision == "approved" else "需修订", "source": args.source, "subject": {"path": delivery["path"], "files": delivery["files"]}, "at": now()}
                task["next_action"] = "按本人反馈修订并检查受影响内容。" if args.decision == "rejected" else "核对完成条件与记录后结束制作任务；发布由本人决定，不作为任务结束条件。"
            elif args.command == "refresh-inputs":
                if task["schema_version"] != 2 or not args.source.strip():
                    raise TaskError("仅 v2 任务支持重绑输入，必须记录复核来源")
                manual = [v for v in task["input_versions"] if not v.get("task_id")]
                task["input_versions"] = [workspace.snapshot(v["path"]) for v in manual] + workspace.dependency_snapshots(task["depends_on"])
                task["checks"] = []
                for gate in task["gates"]:
                    gate.update(decision="pending", subject=None, source="输入更新，需重新确认", at=now())
                workflow = workspace.definition["workflows"][task["workflow"]]
                task["phase"], task["status"] = workflow["phases"][0], "待开始"
                task["next_action"] = "重新检查受上游变化影响的产物；不自动重做外部任务。"
                task["acceptance"] = {"status": "待验收" if workflow["requires_acceptance"] else "不适用", "source": args.source, "subject": None}
                task["issues"].append("上游版本复核：" + args.source)
            elif args.command == "job-intent":
                if not args.tool.strip() or not args.submission_key.strip():
                    raise TaskError("提交意图需要工具和唯一 submission-key")
                if any(j.get("submission_key") == args.submission_key for j in task["external_jobs"]):
                    raise TaskError("提交意图已登记；先用 job-recover 查询并恢复，不重复提交")
                request = workspace.evidence(args.request)
                task["external_jobs"].append({"tool": args.tool, "submission_key": args.submission_key, "request": request,
                                              "task_id": None, "status": "intent", "record": args.request, "at": now()})
            elif args.command == "job":
                if not args.tool.strip() or not args.status.strip() or (not args.task_id and not args.submission_key):
                    raise TaskError("外部任务需要工具、任务 ID 和状态")
                workspace.path(args.record, exists=True)
                record = {"tool": args.tool, "task_id": args.task_id, "status": args.status, "record": args.record, "at": now()}
                if args.cost:
                    record["cost"] = args.cost
                existing = next((j for j in task["external_jobs"] if isinstance(j, dict) and j.get("tool") == args.tool and
                                 ((args.submission_key and j.get("submission_key") == args.submission_key) or
                                  (not args.submission_key and args.task_id and j.get("task_id") == args.task_id))), None)
                if args.submission_key and existing is None:
                    raise TaskError("提交意图不存在，先登记 job-intent")
                if existing is not None:
                    if existing.get("task_id") and args.task_id and existing["task_id"] != args.task_id:
                        raise TaskError("同一提交意图不能改绑另一个外部任务 ID")
                    if existing.get("submission_key") and existing.get("status") in {"succeeded", "failed", "cancelled"} and args.status != existing["status"]:
                        raise TaskError("已终止的提交不能恢复成新请求；如确需新制作，登记新的提交键")
                    record["task_id"] = args.task_id or existing.get("task_id")
                    existing.update(record)
                else:
                    task["external_jobs"].append(record)

        if args.command in {"job", "job-intent"}:
            task, warnings = workspace.mutate(args.task, None, args.command, change, wait=10, tolerate_existing=True)
        else:
            task, warnings = workspace.mutate(args.task, args.revision, args.command, change)
        print(json.dumps({"id": task["id"], "revision": task["revision"], "warnings": warnings}, ensure_ascii=False))
        return 0
    except (TaskError, OSError) as exc:
        print("拒绝操作：" + str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
