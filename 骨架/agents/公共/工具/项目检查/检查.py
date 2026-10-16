#!/usr/bin/env python3
"""项目一键检查：规则文档链接、任务记录、定位确认、账号隔离、智能体包与登记文件、交接产物、受保护目录、密钥、配置一致性；
另外提示每个智能体动手前的阅读量、该提炼的记忆和重复出现的规则。只读，标准库。"""
import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
AGENTS = ROOT / "agents"
SKILLS = Path.home() / ".agents/skills"
PROTECTED = ["交付", "发布内容", "固定资产"]
RULE_GLOBS = ["AGENTS.md", "CLAUDE.md", "agents/*.md", "agents/role/*/AGENT.md", "agents/role/*/知识/**/*.md",
              "agents/role/*/工具/**/*.md", "agents/role/*/记忆/经验.md", "agents/账号/*.md", "agents/账号/附录/**/*.md",
              "agents/账号/数据/README.md", "agents/账号/爆款库/README.md", "agents/账号/历史资料/README.md",
              "agents/项目/*.md", "agents/公共/**/*.md", "agents/工作/README.md", "agents/工作/日志/README.md"]
SKIP_PARTS = {"node_modules", "__pycache__"}
PATH_PREFIXES = ("agents/", "../", "./", "交付/", "发布内容/", "固定资产/", "~/", "/Users/", ".claude/", ".codex/")
PATH_SUFFIXES = (".md", ".json", ".jsonl", ".py", ".yaml", ".yml", ".txt", ".png", ".jpg", ".mp4", ".glb")
SKILL_INTERNAL = ("references/", "scripts/", "templates/", "assets/")  # 技能包内相对路径，随技能入口解析
OPTIONAL = (".claude/skills", ".agents/skills", "~/.claude/skills", "~/.codex/skills", "~/.agents/skills")  # 可能还没建的技能目录
TASK_RELATIVE = ("调研/", "创意/", "方案/", "工程/", "产物/", "检查/", "复盘/", "交付暂存/", "输入/", "过程/",
                 "记忆/")  # 任务目录、智能体包里的相对路径
# 示例或占位路径不做存在性检查。
PLACEHOLDERS = ("<", ">", "*", "YYYY", "…", "任务目录", "绝对路径", "/path/", "实际", "选题名", "原任务",
                "内容名称", "完整包", "SKILL_DIR", "$")
TEXT_SUFFIXES = {".md", ".json", ".jsonl", ".txt", ".py", ".yaml", ".yml", ".js", ".ts", ".tsx", ".html", ".sh", ".csv", ".log"}
# 关键规则：定义处之外只应以引用出现，出现文件过多说明又在多处重写。
# 按账号补充：把本账号最重要、最容易在多处重写的规则短语加进来。
WATCH = {"发布由本人": r"本人在 ?App|发布由本人|由本人(手动)?发布", "交付三文件": r"三文件",
         "付费持续授权": r"持续授权", "taskId 不重提": r"盲目重提|不重复提交|不再盲目"}
WATCH_LIMIT = 3
EXPERIENCE_LIMIT = 3000  # 经验.md 的字数上限
RECORD_LIMIT = 10  # 上次提炼后攒够这么多条记录就该提炼


def rule_docs():
    seen = []
    for pattern in RULE_GLOBS:
        for path in sorted(ROOT.glob(pattern)):
            if path.is_file() and not SKIP_PARTS & set(path.parts) and path not in seen:
                seen.append(path)
    return seen


def rel(path):
    try:
        return str(Path(path).relative_to(ROOT))
    except ValueError:
        return str(path)


def resolve(target, base):
    target = target.split("#")[0].strip()
    if target.startswith("~/"):
        return [Path.home() / target[2:]]
    if target.startswith("/"):
        return [Path(target)]
    return [base / target, AGENTS / target, ROOT / target, SKILLS / target]


def check_links(docs):
    broken = []
    link = re.compile(r"\]\(<?([^)>]+?)>?\)")
    tick = re.compile(r"`([^`\s]+)`")
    for doc in docs:
        text = doc.read_text(encoding="utf-8")
        for number, line in enumerate(text.splitlines(), 1):
            if any(word in line for word in ("不存在", "已不在", "本机已无")):
                continue  # 有意记录已消失路径的说明行
            targets = [m.group(1) for m in link.finditer(line) if not m.group(1).startswith(("http://", "https://", "mailto:", "#"))]
            for token in tick.findall(line):
                if (token.startswith(PATH_PREFIXES) or ("/" in token and token.endswith(PATH_SUFFIXES))) and not token.startswith(("http", "-")):
                    targets.append(token)
            for target in targets:
                if any(p in target for p in PLACEHOLDERS) or target.startswith(SKILL_INTERNAL + OPTIONAL + TASK_RELATIVE) or target.endswith(".env"):
                    continue  # 示例路径、技能包内路径、可选的私有配置不查存在性
                if not any(c.exists() for c in resolve(target, doc.parent)):
                    broken.append(f"{rel(doc)}:{number} → {target}")
    return broken


def task_workspace():
    spec = importlib.util.spec_from_file_location("task_management", AGENTS / "role/总负责人/工具/任务管理/任务管理.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, module.Workspace(ROOT)


def check_tasks(module, workspace):
    errors, warnings = [], 0
    for path in workspace.records():
        task_errors, task_warnings = workspace.validate(module.load_json(path))
        errors += [f"{rel(path)}：{e}" for e in task_errors]
        warnings += len(task_warnings)
    return errors, warnings, len(workspace.records())


def load_tool(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def check_team():
    """智能体包和登记文件是否齐全、最新；爆款库和任务目录里的交接产物是否符合合同。"""
    if not (AGENTS / "公共/工具/团队/生成角色.py").exists():
        return [], 0, 0
    problems, count = load_tool("team_generate", "agents/公共/工具/团队/生成角色.py").check()
    validator = load_tool("team_validate", "agents/公共/工具/团队/校验产物.py")
    files = validator.artifact_files([str(AGENTS / "账号/爆款库"), str(AGENTS / "工作")])
    for path in files:
        try:
            problems += [f"{rel(path)}：{item}" for item in validator.validate_file(path)]
        except Exception as exc:  # 单个产物写坏了不能让整个检查崩掉
            problems.append(f"{rel(path)}：校验时出错 {type(exc).__name__}: {exc}")
    return problems, count, len(files)


def check_positioning(module, workspace):
    """定位状态写"已确认"时，所写任务目录里必须有本人通过的 positioning 确认，且确认绑定的方案文件没改过。"""
    path = AGENTS / "账号/定位与策略.md"
    config = AGENTS / "项目/项目配置.yaml"
    if config.exists() and json.loads(config.read_text(encoding="utf-8"))["project"]["profile"] != "social-account":
        return "非账号项目：按项目开工要求确认", []
    if not path.exists():
        return "没有定位文件", []
    match = re.search(r"^\*\*定位状态：(待确认|已确认)\*\*(.*)$", path.read_text(encoding="utf-8"), re.M)
    if not match:
        return "没写定位状态", []
    if match.group(1) == "待确认":
        return "待确认", []
    found = re.search(r"`(agents/工作/[^`]+?)/?`", match.group(2))
    if not found:
        return "已确认", ["定位状态写了已确认，但没写确认记录所在的任务目录"]
    record = ROOT / found.group(1) / "task.json"
    if not record.is_file():
        return "已确认", [f"定位确认记录不存在：{found.group(1)}"]
    gate = next((g for g in module.load_json(record).get("gates", []) if g.get("key") == "positioning"), None)
    if not gate or gate.get("decision") != "approved" or not str(gate.get("source", "")).strip():
        return "已确认", [f"{found.group(1)} 里没有本人通过的 positioning 确认"]
    if not gate.get("subject"):
        return "已确认", [f"{found.group(1)} 的 positioning 确认没有绑定定位方案文件"]
    error = workspace.evidence_error(gate["subject"])
    if error:
        return "已确认", [f"{found.group(1)} 的定位确认已失效：{error}"]
    return "已确认，确认记录有效", []


def config_list(key):
    path = AGENTS / "项目/项目配置.yaml"
    if path.exists():
        config = json.loads(path.read_text(encoding="utf-8"))
        return config.get("isolation", {}).get(key, [])
    config = AGENTS / "账号/账号配置.yaml"
    text = config.read_text(encoding="utf-8") if config.exists() else ""
    match = re.search(rf"^\s*{key}:\s*\[(.*?)\]", text, re.M)
    return [v.strip().strip("'\"") for v in match.group(1).split(",") if v.strip()] if match else []


def sibling_accounts():
    """同级目录里的其他账号项目：只看文件夹名和有没有入口、账号配置，不读里面的内容。"""
    terms = []
    for folder in sorted(ROOT.parent.iterdir()):
        if folder == ROOT or folder.name.startswith(".") or not folder.is_dir():
            continue
        configs = (folder / "agents/项目/项目配置.yaml", folder / "agents/账号/账号配置.yaml", folder / "agent/规范/账号配置.yaml")
        if (folder / "AGENTS.md").is_file() and any(c.is_file() for c in configs):
            name = folder.name.strip().lstrip("@").strip()
            terms.append(name if len(name) >= 4 else folder.name.strip())  # 名字太短时带上 @，减少误报
    return terms


def check_isolation():
    own = ROOT.name.strip().lstrip("@").strip()
    allowed = set(config_list("allowed_terms"))
    siblings = sibling_accounts()
    terms = [t for t in siblings if t and t not in allowed and t not in own]
    hits = []
    for path in sorted(ROOT.rglob("*")) if terms else []:
        if (path.suffix.lower() not in TEXT_SUFFIXES or SKIP_PARTS & set(path.parts) or path.name.startswith(".env")
                or not path.is_file() or path.stat().st_size > 5_000_000):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeError, OSError):
            continue
        for term in terms:
            if term in text:
                lines = [str(n) for n, line in enumerate(text.splitlines(), 1) if term in line]
                hits.append(f"{rel(path)}:{','.join(lines[:5])} → {term}")
    return hits, len(siblings)


def snapshot():
    state = {}
    for name in PROTECTED:
        for path in sorted((ROOT / name).rglob("*")):
            if path.is_file() and path.name != ".DS_Store":
                stat = path.stat()
                state[rel(path)] = [stat.st_size, stat.st_mtime_ns]
    return state


def compare(before, after):
    return {"新增": sorted(set(after) - set(before)), "删除": sorted(set(before) - set(after)),
            "改动": sorted(k for k in set(before) & set(after) if before[k] != after[k])}


def secret_values():
    values = []
    env = AGENTS / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            key, _, value = line.removeprefix("export ").partition("=")
            value = value.strip().strip("'\"")
            if re.search(r"KEY|TOKEN|SECRET", key.upper()) and len(value) >= 8:
                values.append(value)
    return values


def check_secrets():
    values = secret_values()
    bearer = re.compile(r"Bearer\s+[A-Za-z0-9._\-]{24,}")
    hits = []
    for path in ROOT.rglob("*"):
        if (path.suffix.lower() not in TEXT_SUFFIXES or SKIP_PARTS & set(path.parts) or path.name.startswith(".env")
                or not path.is_file() or path.stat().st_size > 5_000_000):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeError, OSError):
            continue
        if any(v in text for v in values) or bearer.search(text):
            hits.append(rel(path))  # 只报告位置，不输出内容
    return hits, len(values)


def chars(paths):
    return sum(len(p.read_text(encoding="utf-8")) for p in paths if p.is_file())


def role_dirs():
    base = AGENTS / "role"
    return sorted(p for p in base.iterdir() if p.is_dir() and not p.name.startswith(".")) if base.exists() else []


def is_main(role_dir):
    card = role_dir / "agent.yaml"
    return card.is_file() and re.search(r"^main:\s*true\s*$", card.read_text(encoding="utf-8"), re.M) is not None


def startup_files(role_dir):
    """动手前要读的文件：入口、说明书、经验，加上说明书里"开工先读"（总负责人是"每次对话开始"）列出的项目文件。"""
    guide = role_dir / "AGENT.md"
    files = [ROOT / "AGENTS.md", guide, role_dir / "记忆/经验.md"]
    section = "每次对话开始" if is_main(role_dir) else "开工先读"
    text = guide.read_text(encoding="utf-8") if guide.is_file() else ""
    match = re.search(rf"^## {section}\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    for token in re.findall(r"`([^`\s]+)`", match.group(1) if match else ""):
        path = ROOT / token
        if path.is_file() and path not in files:
            files.append(path)
    return files


def reading_load():
    rows = [{"智能体": d.name, "主对话": is_main(d), "文件": [rel(f) for f in startup_files(d)], "字符": chars(startup_files(d))}
            for d in role_dirs()]
    return sorted(rows, key=lambda row: not row["主对话"])


def check_memory():
    """提示：经验超过字数上限，或者上次提炼以后的记录攒够了条数。"""
    notes = []
    for role_dir in role_dirs():
        experience = role_dir / "记忆/经验.md"
        if not experience.is_file():
            continue
        text = experience.read_text(encoding="utf-8")
        if len(text) > EXPERIENCE_LIMIT:
            notes.append(f"{role_dir.name}：经验 {len(text)} 字，超过 {EXPERIENCE_LIMIT}，该提炼了")
        match = re.search(r"最后提炼：\s*(\d{4}-\d{2}-\d{2})", text)
        since, count = (match.group(1) if match else ""), 0
        records = role_dir / "记忆/记录"
        for record in sorted(records.glob("*.md")) if records.is_dir() else []:
            for line in record.read_text(encoding="utf-8").splitlines():
                found = re.match(r"- (\d{4}-\d{2}-\d{2})", line)
                count += bool(found and found.group(1) > since)
        if count >= RECORD_LIMIT:
            notes.append(f"{role_dir.name}：上次提炼后记录 {count} 条，该提炼了")
    return notes


def check_duplicates(docs):
    report = {}
    for label, pattern in WATCH.items():
        found = [rel(d) for d in docs if re.search(pattern, d.read_text(encoding="utf-8"))]
        if len(found) > WATCH_LIMIT:
            report[label] = found
    return report


def check_config():
    problems = []
    common = AGENTS / "项目/项目配置.yaml"
    if common.exists():
        config = json.loads(common.read_text(encoding="utf-8"))
        definition = json.loads((AGENTS / "role/总负责人/工具/任务管理/流程定义.json").read_text(encoding="utf-8"))
        if config.get("schema_version") != 2:
            problems.append("项目配置 schema_version 必须为 2")
        if config.get("project", {}).get("stage") not in {"开工中", "已开工"}:
            problems.append("项目开工状态无效")
        if config["project"].get("timezone") != definition["project"].get("timezone"):
            problems.append("项目时区和任务时区不一致")
        if config.get("team", {}).get("execution_mode") not in {"auto", "multi", "single"}:
            problems.append("team.execution_mode 无效")
        team = load_tool("team_config_check", "agents/公共/工具/团队/生成角色.py")
        found, general = team.roles()
        problems.extend(general)
        actual = {r["meta"].get("id") for r in found}
        selected = set(config.get("team", {}).get("roles", []))
        if actual != selected:
            problems.append("启用角色与实际角色目录不一致")
        required = set(config.get("skills", {}).get("required", []))
        assigned = {s for r in found for s in r["meta"].get("skills", [])}
        if assigned - required:
            problems.append("角色所分配技能未纳入安装需求：" + "、".join(sorted(assigned - required)))
        catalog = json.loads((AGENTS / "公共/技能来源.json").read_text(encoding="utf-8"))
        for name in sorted(required):
            item = catalog["skills"].get(name)
            if item is None or item.get("status", "ready") != "ready":
                problems.append("所需技能不可部署：" + name)
            elif set(item.get("requires", [])) - required:
                problems.append("技能依赖未闭合：" + name)
        return problems
    config = AGENTS / "账号/账号配置.yaml"
    definition = json.loads((AGENTS / "role/总负责人/工具/任务管理/流程定义.json").read_text(encoding="utf-8"))
    if not config.exists():
        return ["缺少 agents/账号/账号配置.yaml"]
    text = config.read_text(encoding="utf-8")
    def value(key):
        match = re.search(rf"^\s*{key}:\s*(\S.*?)\s*(#.*)?$", text, re.M)
        return match.group(1).strip("'\"") if match else None
    package = definition.get("packages", {}).get("social-video", [])
    for key in ["video_filename", "cover_filename", "copy_filename"]:
        if value(key) not in package:
            problems.append(f"账号配置 {key}={value(key)} 不在流程定义 packages.social-video {package}")
    zone = definition.get("project", {}).get("timezone")
    if value("timezone") != zone:
        problems.append(f"账号配置 timezone={value('timezone')} 与流程定义 {zone} 不一致")
    if value("stage") not in {"开工中", "已开工"}:
        problems.append(f"账号配置 stage={value('stage')} 只能是 开工中 或 已开工")
    return problems


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write-baseline", help="保存受保护目录快照（文件、大小、修改时间）")
    parser.add_argument("--baseline", help="与之前保存的快照比较")
    parser.add_argument("--json", help="完整报告另存为 JSON")
    args = parser.parse_args()
    docs = rule_docs()
    report, failed = {}, False

    broken = check_links(docs)
    report["失效链接"] = broken
    print(f"链接：检查 {len(docs)} 份规则文档，失效 {len(broken)} 处")
    for item in broken:
        print("  ✗ " + item)

    module, workspace = task_workspace()
    task_errors, task_warnings, total = check_tasks(module, workspace)
    report["任务记录错误"] = task_errors
    print(f"任务：{total} 个记录，错误 {len(task_errors)}，提示 {task_warnings}")
    for item in task_errors:
        print("  ✗ " + item)

    status, positioning = check_positioning(module, workspace)
    report["定位确认"] = {"状态": status, "问题": positioning}
    print(f"定位：{status}")
    for item in positioning:
        print("  ✗ " + item)

    team, roles, artifacts = check_team()
    report["团队"] = team
    print(f"团队：智能体 {roles} 个，产物 {artifacts} 个，问题 {len(team)} 处")
    for item in team:
        print("  ✗ " + item)

    leaks, siblings = check_isolation()
    report["串号位置"] = leaks
    print(f"隔离：同级账号项目 {siblings} 个，本项目文件里出现它们的名称 {len(leaks)} 处")
    for item in leaks:
        print("  ✗ " + item)

    state = snapshot()
    if args.write_baseline:
        Path(args.write_baseline).write_text(json.dumps(state, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"受保护目录：已保存快照，{len(state)} 个文件")
    if args.baseline:
        diff = compare(json.loads(Path(args.baseline).read_text(encoding="utf-8")), state)
        report["受保护目录变化"] = diff
        changed = sum(len(v) for v in diff.values())
        print(f"受保护目录：与快照比较，变化 {changed} 项")
        for kind, items in diff.items():
            for item in items:
                print(f"  ✗ {kind}：{item}")
        failed |= bool(changed)

    hits, count = check_secrets()
    report["疑似密钥位置"] = hits
    print(f"密钥：比对 {count} 个 .env 密钥及 Bearer 令牌格式，命中 {len(hits)} 个文件")
    for item in hits:
        print("  ✗ " + item)

    rows = reading_load()
    report["阅读量"] = rows
    print("阅读量：动手前要读的字符数（入口、说明书、经验和开工先读）")
    for row in rows:
        print(f"  {row['智能体']}{'（主对话）' if row['主对话'] else ''}：{row['字符']} 字符")

    notes = check_memory()
    report["记忆提示"] = notes
    print(f"记忆：该提炼的 {len(notes)} 处（提示，不判失败）")
    for item in notes:
        print("  ! " + item)

    duplicates = check_duplicates(docs)
    report["规则重复提示"] = duplicates
    print(f"规则重复：超过 {WATCH_LIMIT} 个文件出现的关键规则 {len(duplicates)} 条（提示，不判失败）")
    for label, files in duplicates.items():
        print(f"  ! {label}：{len(files)} 个文件")

    problems = check_config()
    report["配置一致性"] = problems
    print(f"配置：不一致 {len(problems)} 处")
    for item in problems:
        print("  ✗ " + item)

    failed |= bool(broken or task_errors or positioning or team or leaks or hits or problems)
    if args.json:
        Path(args.json).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("结果：" + ("有失败项" if failed else "通过"))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
