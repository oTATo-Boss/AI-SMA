#!/usr/bin/env python3
"""从 agent/团队/*/角色.md 生成 Claude Code（.claude/agents/）和 Codex（.codex/agents/）的角色配置。--check 只检查是否最新，不写文件。标准库。"""
import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TEAM = ROOT / "agent/团队"
CLAUDE = ROOT / ".claude/agents"
CODEX = ROOT / ".codex/agents"
MARK = "由 agent/tools/团队/生成角色.py 生成"
EFFORTS = {"low", "medium", "high", "xhigh", "max"}
CODEX_EFFORT = {"low": "low", "medium": "medium", "high": "high", "xhigh": "xhigh", "max": "xhigh"}


def rel(path):
    return str(Path(path).relative_to(ROOT))


def parse_value(raw):
    raw = raw.strip()
    if raw.startswith("[") and raw.endswith("]"):
        return [item.strip() for item in raw[1:-1].split(",") if item.strip()]
    if raw in {"true", "false"}:
        return raw == "true"
    return raw


def load_role(path):
    """返回 (配置, 正文, 问题列表)。"""
    match = re.match(r"---\n(.*?)\n---\n(.*)", path.read_text(encoding="utf-8"), re.S)
    if not match:
        return {}, "", [f"{rel(path)}：开头缺少 --- 配置块"]
    meta, problems = {}, []
    for line in match.group(1).splitlines():
        if line.strip():
            key, sep, value = line.partition(":")
            if not sep:
                problems.append(f"{rel(path)}：配置行格式不对：{line}")
                continue
            meta[key.strip()] = parse_value(value)
    for key in ("id", "name", "description"):
        if not meta.get(key):
            problems.append(f"{rel(path)}：缺少 {key}")
    if meta.get("id") and not re.fullmatch(r"[a-z][a-z0-9-]*", str(meta["id"])):
        problems.append(f"{rel(path)}：id 只能用小写字母、数字和连字符")
    if meta.get("effort") and meta["effort"] not in EFFORTS:
        problems.append(f"{rel(path)}：effort 只能是 {sorted(EFFORTS)}")
    tools = meta.get("tools", "inherit")
    if not (tools == "inherit" or isinstance(tools, list)):
        problems.append(f"{rel(path)}：tools 写 inherit 或 [工具, …]")
    if not isinstance(meta.get("skills", []), list):
        problems.append(f"{rel(path)}：skills 写成 [技能, …]")
    body = match.group(2).strip()
    if "'''" in body:
        problems.append(f"{rel(path)}：正文不能含三个连续单引号")
    return meta, body, problems


def roles():
    found = []
    for path in sorted(TEAM.glob("*/角色.md")):
        meta, body, problems = load_role(path)
        found.append({"folder": path.parent.name, "meta": meta, "body": body, "problems": problems})
    ids = [r["meta"].get("id") for r in found]
    for role in found:
        if ids.count(role["meta"].get("id")) > 1:
            role["problems"].append(f"agent/团队/{role['folder']}/角色.md：id 重复")
    return found


def available_skills():
    """Claude Code 能发现的技能名（小写）；找不到环境检查工具时返回 None，表示不过滤。"""
    checker = ROOT / "agent/tools/环境检查/检查环境.py"
    deps = ROOT / "agent/tools/环境检查/依赖.json"
    if not checker.exists() or not deps.exists():
        return None
    spec = importlib.util.spec_from_file_location("environment_check", checker)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return set(module.skill_index(json.loads(deps.read_text(encoding="utf-8")).get("claude_roots", [])))


def footer(role, missing=(), list_skills=False):
    lines = ["", "---", f"开工前读 `agent/团队/{role['folder']}/经验.md`；交接格式见 `agent/团队/合同.md`；项目规则以根目录 `AGENTS.md` 为准。"]
    skills = role["meta"].get("skills", [])
    if list_skills and skills:
        lines.append("本角色用到的技能：" + "、".join(skills) + "。用之前完整读它们的 SKILL.md。")
    if missing:
        lines.append("本机没找到这些技能：" + "、".join(missing) + "。按 `agent/SKILLS_INDEX.md` 的来源安装，或回报总控。")
    return "\n".join(lines)


def render_claude(role, available):
    meta = role["meta"]
    skills = meta.get("skills", [])
    preload = [s for s in skills if available is None or s.lower() in available]
    missing = [s for s in skills if s not in preload]
    lines = ["---", f"name: {meta['id']}", "description: " + json.dumps(f"{meta['name']}：{meta['description']}", ensure_ascii=False)]
    if isinstance(meta.get("tools"), list):
        lines.append("tools: " + ", ".join(meta["tools"]))
    if meta.get("nesting") is False:
        lines.append("disallowedTools: Agent")
    for key in ("model", "effort"):
        if meta.get(key):
            lines.append(f"{key}: {meta[key]}")
    if preload:
        lines += ["skills:"] + [f"  - {s}" for s in preload]
    lines.append("---")
    head = "\n".join(lines) + f"\n<!-- {MARK}，源文件 agent/团队/{role['folder']}/角色.md；要改请改源文件后重新运行 -->\n\n"
    return head + role["body"] + footer(role, missing) + "\n"


def render_codex(role):
    meta = role["meta"]
    lines = [f"# {MARK}，源文件 agent/团队/{role['folder']}/角色.md；要改请改源文件后重新运行",
             "name = " + json.dumps(meta["id"]),
             "description = " + json.dumps(f"{meta['name']}：{meta['description']}", ensure_ascii=False)]
    if meta.get("effort"):
        lines.append("model_reasoning_effort = " + json.dumps(CODEX_EFFORT[meta["effort"]]))
    lines.append("developer_instructions = '''")
    return "\n".join(lines) + "\n" + role["body"] + footer(role, list_skills=True) + "\n'''\n"


def plan():
    """返回 (要写的文件 {路径: 内容}, 问题列表, 角色数)。"""
    found = roles()
    problems = [p for role in found for p in role["problems"]]
    available = available_skills()
    files = {}
    for role in found:
        if role["problems"]:
            continue
        files[CLAUDE / f"{role['meta']['id']}.md"] = render_claude(role, available)
        files[CODEX / f"{role['meta']['id']}.toml"] = render_codex(role)
    return files, problems, len(found)


def stale(files):
    """生成目录里由本脚本生成、但已没有对应角色的文件。"""
    extra = []
    for folder in (CLAUDE, CODEX):
        for path in sorted(folder.glob("*")) if folder.exists() else []:
            if path not in files and path.is_file() and MARK in path.read_text(encoding="utf-8", errors="ignore"):
                extra.append(path)
    return extra


def check():
    """给项目检查用：返回 (问题列表, 角色数)。"""
    files, problems, count = plan()
    for path, content in files.items():
        if not path.exists():
            problems.append(f"缺少 {rel(path)}，运行 python3 agent/tools/团队/生成角色.py")
        elif path.read_text(encoding="utf-8") != content:
            problems.append(f"{rel(path)} 不是最新，运行 python3 agent/tools/团队/生成角色.py")
    problems += [f"{rel(p)} 已没有对应角色，可以删除" for p in stale(files)]
    return problems, count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="只检查是否最新，不写文件")
    args = parser.parse_args()
    if args.check:
        problems, count = check()
        print(f"角色：{count} 个，问题 {len(problems)} 处")
        for item in problems:
            print("  ✗ " + item)
        return 1 if problems else 0
    files, problems, count = plan()
    for path, content in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists() or path.read_text(encoding="utf-8") != content:
            path.write_text(content, encoding="utf-8")
    extra = stale(files)
    print(f"角色：{count} 个，已生成 Claude Code 配置 {sum(p.parent == CLAUDE for p in files)} 个、Codex 配置 {sum(p.parent == CODEX for p in files)} 个")
    for item in problems + [f"{rel(p)} 已没有对应角色，可以删除" for p in extra]:
        print("  ✗ " + item)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
