#!/usr/bin/env python3
"""从 agents/role/*/agent.yaml 生成子智能体的登记文件：Claude Code 的 .claude/agents/<编号>.md、Codex 的 .codex/agents/<编号>.toml，
以及 .codex/config.toml（同时干活的子智能体上限）。登记文件只让子智能体先读自己的说明书，说明书改了不用重新生成。
顺带检查每个智能体包是否齐全、配置卡是否合格、用到的技能是否登记在技能目录。--check 只检查是否最新，不写文件。标准库。"""
import argparse
import hashlib
import importlib.util
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
ROLES = ROOT / "agents/role"
ACCOUNT_CONFIG = ROOT / "agents/账号/账号配置.yaml"
PROJECT_CONFIG = ROOT / "agents/项目/项目配置.yaml"
SKILLS_INDEX = ROOT / "agents/SKILLS_INDEX.md"
CLAUDE = ROOT / ".claude/agents"
CODEX = ROOT / ".codex/agents"
CODEX_CONFIG = ROOT / ".codex/config.toml"
MARK = "由 agents/公共/工具/团队/生成角色.py 生成"
REQUIRED = ("AGENT.md", "agent.yaml", "记忆/经验.md")
EFFORTS = {"low", "medium", "high", "xhigh", "max"}
CODEX_EFFORT = {"low": "low", "medium": "medium", "high": "high", "xhigh": "xhigh", "max": "xhigh"}
KEY = re.compile(r"[a-z][a-z0-9_]*")


def rel(path):
    return Path(path).relative_to(ROOT).as_posix()


def parse_value(raw):
    raw = raw.strip()
    if raw.startswith("[") and raw.endswith("]"):
        return [item.strip() for item in raw[1:-1].split(",") if item.strip()]
    if raw in {"true", "false"}:
        return raw == "true"
    return raw


def load_card(path):
    """读配置卡：每行"键: 值"，# 开头的是注释。返回 (配置, 问题列表)。"""
    meta, problems = {}, []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, sep, value = line.partition(":")
        if not sep or not KEY.fullmatch(key):
            problems.append(f"{rel(path)}：配置行格式不对：{line}")
            continue
        meta[key] = parse_value(value)
    for key in ("id", "name", "description"):
        if not meta.get(key):
            problems.append(f"{rel(path)}：缺少 {key}")
    if meta.get("id") and not re.fullmatch(r"[a-z][a-z0-9-]*", str(meta["id"])):
        problems.append(f"{rel(path)}：id 只能用小写字母、数字和连字符")
    if meta.get("effort") and meta["effort"] not in EFFORTS:
        problems.append(f"{rel(path)}：effort 只能是 {sorted(EFFORTS)}")
    tools = meta.get("claude_tools", "inherit")
    if not (tools == "inherit" or isinstance(tools, list)):
        problems.append(f"{rel(path)}：claude_tools 写 inherit 或 [工具, …]")
    if not isinstance(meta.get("skills", []), list):
        problems.append(f"{rel(path)}：skills 写成 [技能, …]")
    for key in ("nesting", "main"):
        if key in meta and not isinstance(meta[key], bool):
            problems.append(f"{rel(path)}：{key} 只能是 true 或 false")
    quoted = [str(meta.get("name", ""))] + [str(s) for s in meta.get("skills", []) if isinstance(meta.get("skills"), list)]
    if any("'''" in item for item in quoted):  # 名字和技能会写进 Codex 的 ''' 字符串
        problems.append(f"{rel(path)}：name 和 skills 不能含三个连续单引号")
    return meta, problems


def roles():
    """返回 (智能体列表, 不属于单个智能体的问题)。"""
    found = []
    folders = sorted(p for p in ROLES.iterdir() if p.is_dir() and not p.name.startswith(".")) if ROLES.exists() else []
    for folder in folders:
        problems = [f"agents/role/{folder.name}：缺少 {name}" for name in REQUIRED if not (folder / name).is_file()]
        if "'''" in folder.name:
            problems.append(f"agents/role/{folder.name}：文件夹名不能含三个连续单引号")
        meta = {}
        if (folder / "agent.yaml").is_file():
            meta, card_problems = load_card(folder / "agent.yaml")
            problems += card_problems
        found.append({"folder": folder.name, "meta": meta, "problems": problems})
    ids = [r["meta"].get("id") for r in found if r["meta"].get("id")]
    for role in found:
        if role["meta"].get("id") and ids.count(role["meta"]["id"]) > 1:
            role["problems"].append(f"agents/role/{role['folder']}/agent.yaml：编号重复")
    general = []
    if found and sum(r["meta"].get("main") is True for r in found) != 1:
        general.append("agents/role/ 里应该有且只有一个 main: true 的智能体（总负责人）")
    return found, general


def project_config():
    return json.loads(PROJECT_CONFIG.read_text(encoding="utf-8")) if PROJECT_CONFIG.exists() else None


def ownership_path():
    return ROOT / ("agents/项目/团队生成记录.json" if PROJECT_CONFIG.exists() else "agents/公共/工具/团队/生成记录.json")


def safe_output(path):
    path = Path(path)
    path.relative_to(ROOT)
    for candidate in (path, *path.parents):
        if candidate == ROOT:
            break
        if candidate.is_symlink() or (candidate.exists() and candidate.resolve() != candidate.absolute()):
            raise ValueError("客户端输出经过链接，保留原内容：" + rel(path))
    return path


def content_digest(content):
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def ownership():
    path = safe_output(ownership_path())
    if not path.exists():
        return {"schema_version": 1, "files": {}}
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("schema_version") != 1 or not isinstance(value.get("files"), dict):
        raise ValueError("团队生成记录格式无效，保留原文件")
    value['files'] = {key.replace('\\', '/'): digest for key, digest in value['files'].items()}
    return value


def atomic_write(path, content):
    path = safe_output(path)
    temporary = safe_output(path.with_name(path.name + ".tmp"))
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary.write_text(content, encoding="utf-8")
    os.replace(temporary, path)


def load_tool(name, relative):
    path = ROOT / relative
    if not path.exists():
        return None
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def available_skills():
    """Claude Code 能发现的技能名（小写）；找不到环境检查工具时返回 None，表示不过滤。"""
    if PROJECT_CONFIG.exists():
        # Availability is verified separately. Generation must never silently remove assigned skills.
        return None
    module = load_tool("environment_check", "agents/公共/工具/环境检查/检查环境.py")
    deps = ROOT / "agents/公共/工具/环境检查/依赖.json"
    if module is None or not deps.exists():
        return None
    return set(module.skill_index(json.loads(deps.read_text(encoding="utf-8")).get("claude_roots", [])))


def indexed_skills():
    """技能目录里登记的技能名（小写）；没有技能目录时返回 None，表示不核对。"""
    catalog = ROOT / "agents/公共/技能来源.json"
    if catalog.exists():
        return {s.lower() for s in json.loads(catalog.read_text(encoding="utf-8"))["skills"]}
    module = load_tool("environment_check", "agents/公共/工具/环境检查/检查环境.py")
    if module is None or not SKILLS_INDEX.exists():
        return None
    return {re.sub(r"（.*?）|\(.*?\)", "", row["名称"]).strip().lower() for row in module.index_rows(SKILLS_INDEX.read_text(encoding="utf-8"))}


def pointer(role):
    meta, base = role["meta"], f"agents/role/{role['folder']}"
    return (f"你是{meta['name']}（{meta['id']}）。第一步：完整读 `{base}/AGENT.md` 和 `{base}/记忆/经验.md`，按说明书工作。"
            f"随后读取存在的 `agents/项目/定制/项目规则.md` 与 `agents/项目/定制/角色/{meta['id']}.md`；本人要求优先。"
            "项目红线以根目录 AGENTS.md 为准；结果交回总负责人，不直接找本人。")


def render_claude(role, available):
    meta = role["meta"]
    skills = meta.get("preload_skills", meta.get("skills", []))
    preload = [s for s in skills if available is None or s.lower() in available]
    missing = [s for s in skills if s not in preload]
    lines = ["---", f"name: {meta['id']}", "description: " + json.dumps(f"{meta['name']}：{meta['description']}", ensure_ascii=False)]
    if isinstance(meta.get("claude_tools"), list):
        lines.append("tools: " + ", ".join(meta["claude_tools"]))
    if meta.get("nesting") is False:
        lines.append("disallowedTools: Agent")
    if meta.get("claude_model"):
        lines.append(f"model: {meta['claude_model']}")
    if meta.get("effort"):
        lines.append(f"effort: {meta['effort']}")
    if preload:
        lines += ["skills:"] + [f"  - {s}" for s in preload]
    lines.append("---")
    body = pointer(role)
    if PROJECT_CONFIG.exists():
        body += "\n本角色全部已分配技能与实际入口见 agents/项目/安装回执.json；未验证时先回报缺口。按任务读取所需技能，不将全部技能预加载。"
    if missing:
        body += "\n\n本机没找到这些技能：" + "、".join(missing) + "。按 `agents/SKILLS_INDEX.md` 的来源安装，或回报总负责人。"
    head = "\n".join(lines) + f"\n<!-- {MARK}，源文件 agents/role/{role['folder']}/agent.yaml；要改请改源文件后重新运行 -->\n\n"
    return head + body + "\n"


def render_codex(role):
    meta = role["meta"]
    lines = [f"# {MARK}，源文件 agents/role/{role['folder']}/agent.yaml；要改请改源文件后重新运行",
             "name = " + json.dumps(meta["id"]),
             "description = " + json.dumps(f"{meta['name']}：{meta['description']}", ensure_ascii=False)]
    if meta.get("codex_model"):
        lines.append("model = " + json.dumps(meta["codex_model"]))
    if meta.get("effort"):
        lines.append("model_reasoning_effort = " + json.dumps(CODEX_EFFORT[meta["effort"]]))
    body = pointer(role)
    if meta.get("skills"):
        body += "\n本角色用到的技能：" + "、".join(meta["skills"]) + "。用之前完整读它们的 SKILL.md。"
    if PROJECT_CONFIG.exists():
        body += "\n精确技能来源、版本、入口与验证状态见 agents/项目/安装回执.json；不按同名技能猜测来源。"
    lines.append("developer_instructions = '''")
    return "\n".join(lines) + "\n" + body + "\n'''\n"


def parallel_limit():
    if PROJECT_CONFIG.exists():
        return int(project_config().get("autonomy", {}).get("max_parallel_agents", 3))
    text = ACCOUNT_CONFIG.read_text(encoding="utf-8") if ACCOUNT_CONFIG.exists() else ""
    match = re.search(r"^\s*max_parallel_agents:\s*(\d+)", text, re.M)
    return int(match.group(1)) if match else 3


def network_commands():
    """账号配置 autonomy.network_commands：没写时按 true，做内容时命令可以联网。"""
    if PROJECT_CONFIG.exists():
        return project_config().get("autonomy", {}).get("network_commands", True)
    text = ACCOUNT_CONFIG.read_text(encoding="utf-8") if ACCOUNT_CONFIG.exists() else ""
    match = re.search(r"^\s*network_commands:\s*(true|false)\b", text, re.M)
    return match is None or match.group(1) == "true"


def render_codex_config():
    source = "agents/项目/项目配置.yaml" if PROJECT_CONFIG.exists() else "agents/账号/账号配置.yaml"
    text = (f"# {MARK}，取自 {source} 的 autonomy（max_parallel_agents、network_commands）；要改请改源文件后重新运行\n"
            f"[agents]\nmax_concurrent_threads_per_session = {parallel_limit()}\n")
    if network_commands():
        text += "\n[sandbox_workspace_write]\nnetwork_access = true\n"
    if CODEX_CONFIG.exists() and MARK in CODEX_CONFIG.read_text(encoding='utf-8'):
        # Retain unrelated user settings and comments; only two declared fields are managed.
        existing = CODEX_CONFIG.read_text(encoding='utf-8')
        import tomllib
        tomllib.loads(existing)
        for section, key, value in [('agents', 'max_concurrent_threads_per_session', str(parallel_limit())),
                                    ('sandbox_workspace_write', 'network_access', 'true' if network_commands() else None)]:
            pattern = re.compile(r'(?ms)^\[' + re.escape(section) + r'\][^\n]*\n(.*?)(?=^\[|\Z)')
            match = pattern.search(existing)
            if match:
                body = match.group(1)
                field = re.compile(r'(?m)^' + re.escape(key) + r'\s*=.*$')
                if value is None:
                    body = field.sub('', body)
                else:
                    body = field.sub(key + ' = ' + value, body) if field.search(body) else body + key + ' = ' + value + '\n'
                existing = existing[:match.start(1)] + body + existing[match.end(1):]
            elif value is not None:
                existing += f'\n[{section}]\n{key} = {value}\n'
        text = existing
    return text


def plan():
    """返回 (要写的文件 {路径: 内容}, 问题列表, 智能体数, 提示列表)。"""
    found, problems = roles()
    problems += [p for role in found for p in role["problems"]]
    available, indexed = available_skills(), indexed_skills()
    config = project_config()
    client = config.get("project", {}).get("client", "both") if config else "both"
    selected = set(config.get("team", {}).get("roles", [])) if config else None
    files, notes = {}, []
    for role in found:
        if selected is not None and role["meta"].get("id") not in selected:
            continue
        preloads = role["meta"].get("preload_skills", [])
        if not isinstance(preloads, list) or set(preloads) - set(role["meta"].get("skills", [])):
            problems.append(f"agents/role/{role['folder']}/agent.yaml：preload_skills 必须是 skills 的子集")
        if indexed is not None:
            problems += [f"agents/role/{role['folder']}/agent.yaml：技能 {s} 没登记在 agents/SKILLS_INDEX.md"
                         for s in role["meta"].get("skills", []) if s.lower() not in indexed]
        if role["problems"] or role["meta"].get("main") is True:
            continue
        if client in {"claude", "both"}:
            files[CLAUDE / f"{role['meta']['id']}.md"] = render_claude(role, available)
        if client in {"codex", "both"}:
            files[CODEX / f"{role['meta']['id']}.toml"] = render_codex(role)
    if client in {"codex", "both"}:
        safe_output(CODEX_CONFIG)
        if CODEX_CONFIG.exists() and MARK not in CODEX_CONFIG.read_text(encoding="utf-8", errors="ignore"):
            notes.append(f".codex/config.toml 是本人自己的设置，没有覆盖；需要时手动加 [agents] max_concurrent_threads_per_session = {parallel_limit()}")
        else:
            files[CODEX_CONFIG] = render_codex_config()
    for path in files:
        safe_output(path)
    return files, problems, len(found), notes


def stale(files):
    """生成目录里由本脚本生成、但已没有对应智能体的文件。"""
    extra = []
    config = project_config()
    client = config.get("project", {}).get("client", "both") if config else "both"
    folders = [folder for name, folder in (("claude", CLAUDE), ("codex", CODEX)) if client in {name, "both"}]
    for folder in folders:
        safe_output(folder)
        for path in sorted(folder.glob("*")) if folder.exists() else []:
            safe_output(path)
            if path not in files and path.is_file() and MARK in path.read_text(encoding="utf-8", errors="ignore"):
                extra.append(path)
    return extra


def check():
    """给项目检查用：返回 (问题列表, 智能体数)。"""
    files, problems, count, _ = plan()
    for path, content in files.items():
        if not path.exists():
            problems.append(f"缺少 {rel(path)}，运行 python3 agents/公共/工具/团队/生成角色.py")
        elif path.read_text(encoding="utf-8") != content:
            problems.append(f"{rel(path)} 不是最新，运行 python3 agents/公共/工具/团队/生成角色.py")
    problems += [f"{rel(p)} 已没有对应的智能体，可以删除" for p in stale(files)]
    return problems, count


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="只检查是否最新，不写文件")
    args = parser.parse_args()
    if args.check:
        problems, count = check()
        print(f"智能体：{count} 个，问题 {len(problems)} 处")
        for item in problems:
            print("  ✗ " + item)
        return 1 if problems else 0
    files, problems, count, notes = plan()
    owned = ownership()
    for path, content in files.items():
        safe_output(path)
        safe_output(path.with_name(path.name + ".tmp"))
        if path.exists():
            current = path.read_text(encoding="utf-8")
            if current != content and content_digest(current) != owned["files"].get(rel(path)):
                problems.append(f"{rel(path)} 已有用户修改或来源未登记，保留原文件；请在配置卡中合并修改后处理此冲突")
    if problems:
        for item in problems:
            print("  ✗ " + item)
        return 1
    for path, content in files.items():
        if not path.exists() or path.read_text(encoding="utf-8") != content:
            atomic_write(path, content)
        owned["files"][rel(path)] = content_digest(content)
        atomic_write(ownership_path(), json.dumps(owned, ensure_ascii=False, indent=2) + "\n")
    extra = stale(files)
    claude = sum(p.parent == CLAUDE for p in files)
    codex = sum(p.parent == CODEX for p in files)
    print(f"智能体：{count} 个，已生成 Claude Code 登记 {claude} 个、Codex 登记 {codex} 个")
    for item in problems + [f"{rel(p)} 已没有对应的智能体，可以删除" for p in extra]:
        print("  ✗ " + item)
    for item in notes:
        print("  ! " + item)
    return 1 if problems else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, OSError, KeyError) as exc:
        print(f"停止：{exc}", file=sys.stderr)
        sys.exit(1)
