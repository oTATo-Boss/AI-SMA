#!/usr/bin/env python3
"""Local task records. Standard library only; never writes protected directories."""
import argparse
import copy
import fcntl
import hashlib
import json
import os
import re
import tempfile
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


class TaskError(ValueError):
    pass


ZONE = ZoneInfo("Asia/Shanghai")  # 由流程定义 project.timezone 覆盖


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
        self.agent = self.root / "agent"
        self.runtime = self.agent / "tools/任务管理"
        self.definition = load_json(self.runtime / "流程定义.json")
        project = self.definition.get("project", {})
        self.work = self.root / project.get("work_dir", "agent/工作")
        self.delivery_root = self.root / project.get("delivery_dir", "交付")
        self.overview_path = self.root / project.get("overview", "agent/log/任务总览.md")
        self.packages = self.definition.get("packages", {"social-video": ["视频.mp4", "封面.png", "发布文案.txt"]})
        self.read_only = [self.root / d for d in project.get("read_only_dirs", ["发布内容", "固定资产"])]
        ZONE = ZoneInfo(project.get("timezone", "Asia/Shanghai"))

    def path(self, value, *, write=False, exists=False):
        if not isinstance(value, str) or not value:
            raise TaskError("路径必须为非空的项目相对路径")
        relative = Path(value)
        if relative.is_absolute() or ".." in relative.parts:
            raise TaskError("路径必须相对项目根目录，不能包含 ..")
        if any(part.startswith(".env") or part in {"credentials", ".git"} for part in relative.parts):
            raise TaskError("任务路径不能引用凭据或 Git 内部文件")
        path = self.root / relative
        cursor = self.root
        for part in relative.parts:
            cursor = cursor / part
            if cursor.is_symlink():
                raise TaskError(f"路径不能经过软链接：{value}")
        resolved = path.resolve()
        if not resolved.is_relative_to(self.root):
            raise TaskError("路径离开项目目录")
        if write:
            if not resolved.is_relative_to(self.agent):
                raise TaskError("管理工具只允许写 agent/，不能写受保护目录")
            if path.is_file() and path.stat().st_nlink > 1:
                raise TaskError("不能写入硬链接文件")
        if exists and not path.exists():
            raise TaskError(f"路径不存在：{value}")
        return path

    def relative(self, path):
        return str(Path(path).relative_to(self.root))

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
        expected = self.packages.get(kind)
        if expected is not None and {p.name for p in entries} != set(expected):
            raise TaskError(f"{kind} 包应只含：" + "、".join(expected))
        files = {}
        for path in entries:
            self.path(self.relative(path), exists=True)
            if not path.is_file() or path.stat().st_nlink > 1 or path.stat().st_size == 0:
                raise TaskError(f"交付文件必须是非空独立文件：{path.name}")
            if kind == "prompt" and path.suffix.lower() not in {".txt", ".png", ".jpg", ".jpeg", ".webp"}:
                raise TaskError("提示词包只能含 txt 与参考图")
            files[path.name] = sha256(path)
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
            if Path(new_name).name != new_name or new_name in {".", ".."}:
                raise TaskError("新交付名称不能包含路径")
            target = self.path(self.relative(self.delivery_root / new_name))
            if target.exists():
                raise TaskError("同名交付已存在，不能合并、追加或覆盖")
        return {"path": value, "kind": kind, "files": files}

    def validate(self, task):
        errors, warnings = [], []
        if not isinstance(task, dict):
            return ["任务必须是对象"], warnings
        template = load_json(self.runtime / "模板/任务.json")
        missing = set(template) - set(task)
        if missing:
            return ["任务缺少字段：" + ", ".join(sorted(missing))], warnings
        if task["schema_version"] != 1:
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
            if gate["key"] == "plan" and gate["decision"] == "approved" and gate["subject"] is None:
                errors.append("方案确认必须绑定具体文件版本")
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
        for job in task["external_jobs"]:
            if not isinstance(job, dict) or not {"tool", "task_id", "status", "record"}.issubset(job):
                errors.append("外部任务缺少工具、ID、状态或回包位置")
            elif job["record"]:
                try:
                    self.path(job["record"], exists=True)
                except TaskError as exc:
                    errors.append(str(exc))
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

    @contextmanager
    def locked(self, task_path):
        lock = self.path(self.relative(task_path.parent / ".task.lock"), write=True)
        with lock.open("a") as stream:
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise TaskError("任务正在被另一进程编辑，重新读取后再试") from exc
            try:
                yield
            finally:
                fcntl.flock(stream, fcntl.LOCK_UN)

    def mutate(self, value, revision, action, change):
        path = self.task_path(value)
        with self.locked(path):
            original = load_json(path)
            if original.get("revision") != revision:
                raise TaskError("任务版本冲突，重新读取当前 revision 后再写")
            task = copy.deepcopy(original)
            change(task)
            task["revision"] += 1
            task["updated_at"] = now()
            errors, warnings = self.validate(task)
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

    def new(self, title, workflow, goal, done_when, owner):
        if not title.strip() or Path(title).name != title or title in {".", ".."}:
            raise TaskError("任务名称不能为空或包含路径")
        definition = self.definition["workflows"][workflow]
        task = load_json(self.runtime / "模板/任务.json")
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
    create.add_argument("--owner", default="agent（当前对话）")
    for name in ["show", "validate", "update", "authorize", "gate", "check", "delivery", "accept"]:
        cmd = sub.add_parser(name)
        cmd.add_argument("task", help="相对项目根目录的任务目录或 task.json")
        if name in {"update", "authorize", "gate", "check", "delivery", "accept"}:
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
            cmd.add_argument("--subject", help="本人确认的具体文件；脚本／方案确认须填写")
        elif name == "check":
            cmd.add_argument("--name", required=True)
            cmd.add_argument("--result", choices=["passed", "failed", "unverified"], required=True)
            cmd.add_argument("--evidence")
            cmd.add_argument("--summary", required=True)
        elif name == "delivery":
            cmd.add_argument("--path", required=True)
            cmd.add_argument("--kind", choices=kinds, required=True)
            cmd.add_argument("--source", required=True)
        elif name == "accept":
            cmd.add_argument("--decision", choices=["approved", "rejected"], required=True)
            cmd.add_argument("--source", required=True)
    sub.add_parser("sync", help="生成任务总览")
    sub.add_parser("validate-all", help="检查所有当前任务")
    package = sub.add_parser("check-package", help="只读检查完整包及新名称冲突；不复制交付")
    package.add_argument("path")
    package.add_argument("--kind", choices=kinds, required=True)
    package.add_argument("--new-name")
    return p


def main():
    args = parser().parse_args()
    workspace = Workspace(Path(__file__).resolve().parents[3])
    try:
        if args.command == "new":
            _, path = workspace.new(args.title, args.workflow, args.goal, args.done_when, args.owner)
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
                        task[key] = getattr(args, arg)
                for arg, key in [("input", "inputs"), ("output", "outputs"), ("issue", "issues")]:
                    for item in getattr(args, arg):
                        if item not in task[key]:
                            task[key].append(item)
                # Legacy history is not a license for new execution.
                if task["phase"] != old_phase and args.status not in {"取消"}:
                    definition = workspace.definition["workflows"][task["workflow"]]
                    if task["phase"] in definition["phases"]:
                        for gate in task["gates"]:
                            if definition["phases"].index(task["phase"]) >= definition["phases"].index(gate["before_phase"]) and gate["decision"] != "approved":
                                raise TaskError("新阶段必须取得确认：" + gate["title"])
            elif args.command == "authorize":
                if not args.scope.strip() or not args.source.strip():
                    raise TaskError("授权需要范围和本人来源")
                task["approvals"].append({"scope": args.scope, "source": args.source, "decision": "approved", "at": now()})
            elif args.command == "gate":
                gate = next((g for g in task["gates"] if g["key"] == args.key), None)
                if gate is None:
                    if not args.title or not args.before_phase:
                        raise TaskError("新增确认需要 title 与 before-phase")
                    gate = {"key": args.key, "title": args.title, "before_phase": args.before_phase}
                    task["gates"].append(gate)
                if args.decision == "approved" and not args.source.strip():
                    raise TaskError("确认缺少本人来源")
                if args.key == "plan" and args.decision == "approved" and not args.subject:
                    raise TaskError("方案确认必须绑定具体文件版本")
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

        task, warnings = workspace.mutate(args.task, args.revision, args.command, change)
        print(json.dumps({"id": task["id"], "revision": task["revision"], "warnings": warnings}, ensure_ascii=False))
        return 0
    except (TaskError, OSError) as exc:
        print("拒绝操作：" + str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
