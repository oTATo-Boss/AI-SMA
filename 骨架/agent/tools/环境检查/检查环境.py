#!/usr/bin/env python3
"""本机环境检查：必要工具、应用、Python 包、登录状态和项目技能是否齐全，缺了给出补法。
只读：不安装、不登录、不读取或输出密钥。退出码 1 表示缺少必需项。
技能清单读 agent/SKILLS_INDEX.md：有"入口"链接的按路径查，否则按名字在常见技能目录里找；补法取"来源"列。"""
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DEPENDENCIES = Path(__file__).resolve().parent / "依赖.json"
SKILLS_INDEX = ROOT / "agent/SKILLS_INDEX.md"
MARK = {"ok": "✓", "missing": "✗", "warn": "!"}
SKIP_DIRS = {"node_modules", ".git", "__pycache__", "references", "scripts", "assets", "templates", "examples"}


def expand(value):
    if value.startswith("~"):
        return Path(value).expanduser()
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def locate(tool):
    found = shutil.which(tool["name"])
    if found:
        return found, False
    for candidate in tool.get("paths", []):
        if expand(candidate).exists():
            return str(expand(candidate)), True
    return None, False


def run(command, timeout=20):
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
        return result.returncode, (result.stdout or "") + (result.stderr or "")
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, type(exc).__name__


def version_tuple(text):
    match = re.search(r"(\d+(?:\.\d+)*)", text)
    return tuple(int(x) for x in match.group(1).split(".")) if match else None


def frontmatter_name(skill_md):
    try:
        with skill_md.open(encoding="utf-8") as stream:
            head = stream.read(2000)
    except (OSError, UnicodeError):
        return None
    match = re.search(r"^name:\s*['\"]?([^'\"\n]+)", head, re.M)
    return match.group(1).strip() if match else None


def skill_index(roots, depth=4):
    """在技能目录里按目录名和 frontmatter name 建索引（小写）。"""
    index, seen = {}, set()
    for root in roots:
        base = expand(root)
        if not base.exists():
            continue
        for current, dirs, files in os.walk(base, followlinks=True):
            real = os.path.realpath(current)
            level = len(Path(current).relative_to(base).parts)
            if real in seen or level > depth:
                dirs[:] = []
                continue
            seen.add(real)
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            if "SKILL.md" in files:
                skill_md = Path(current) / "SKILL.md"
                for name in {skill_md.parent.name, frontmatter_name(skill_md) or ""} - {""}:
                    index.setdefault(name.lower(), []).append(skill_md)
    return index


def index_rows(text):
    """读技能索引里带"名称"列、且有"入口"或"来源"列的表格行。"""
    rows, header = [], None
    for line in text.splitlines():
        if not line.startswith("|"):
            header = None
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if set(line.replace("|", "").strip()) <= set("-: "):
            continue
        if header is None:
            header = cells
            continue
        row = dict(zip(header, cells))
        if "名称" in row and ("入口" in row or "来源" in row):
            rows.append(row)
    return rows


def plain(text):
    return re.sub(r"\[([^\]]*)\]\(([^)]*)\)", r"\1 \2", text).replace("`", "").strip()


def check_tools(deps, report):
    located = {}
    for tool in deps["tools"]:
        path, fallback = locate(tool)
        if not path:
            report.append((tool["need"], "missing", f"{tool['name']}：没找到（{tool['for']}）", tool["install"]))
            continue
        located[tool["name"]] = path
        _, output = run([path, *tool["version"]])
        first = next((line for line in output.splitlines() if line.strip()), "").strip()[:60]
        found, minimum = version_tuple(first), tool.get("min")
        if minimum and (not found or found < version_tuple(minimum)):
            report.append((tool["need"], "missing", f"{tool['name']} 版本 {first} 低于 {minimum}", tool["install"]))
            continue
        note = f"（不在 PATH，使用 {path}）" if fallback else ""
        report.append((tool["need"], "ok", f"{tool['name']}：{first}{note}", None))
    for app in deps.get("apps", []):
        status = "ok" if Path(app["path"]).exists() else "missing"
        report.append((app["need"], status, f"{app['name']}：{'已安装' if status == 'ok' else '没找到'}（{app['for']}）",
                       None if status == "ok" else app["install"]))
    for package in deps.get("python_packages", []):
        code, _ = run([sys.executable, "-c", f"import {package['name']}"])
        status = "ok" if code == 0 else "missing"
        report.append((package["need"], status, f"Python 包 {package['name']}：{'可用' if code == 0 else '没装'}（{package['for']}）",
                       None if code == 0 else package["install"]))
    return located


def summarize_heygen(output):
    data = json.loads(output)
    credential, account = data.get("credential", {}), data.get("data", {})
    plan = account.get("subscription", {}).get("plan", "未知")
    expires = (credential.get("expires_at") or "")[:10]
    refresh = "，可续期" if credential.get("refreshable") else ""
    return f"已登录（{plan}，{expires} 到期{refresh}）"


def check_logins(deps, located, skills, report):
    for login in deps.get("logins", []):
        if "skill" in login:
            found = skills.get(login["skill"].lower())
            if not found:
                report.append((login["need"], "missing", f"{login['name']}：技能 {login['skill']} 没装，无法检查", login["fix"]))
                continue
            command = [sys.executable, str(found[0].parent / login["script"]), *login.get("args", [])]
        else:
            command = [str(expand(part)) if part.startswith("~") else part for part in login["command"]]
            if command[0] in located:
                command[0] = located[command[0]]
            elif not shutil.which(command[0]):
                report.append((login["need"], "missing", f"{login['name']}：对应工具没装，无法检查", login["fix"]))
                continue
        code, output = run(command)
        try:
            if login.get("parse") == "heygen":
                ok, summary = code == 0, summarize_heygen(output)
            else:
                ok = code == 0 and login["ok"] in output
                summary = next((line for line in output.splitlines() if line.strip()), "").strip()[:80]
        except (ValueError, KeyError, AttributeError):
            ok, summary = False, "状态无法解析"
        # 只输出状态摘要；状态命令本身不回显密钥
        report.append((login["need"], "ok" if ok else "missing", f"{login['name']}：{summary if ok else '未就绪'}", None if ok else login["fix"]))


def check_skills(deps, skills, report):
    claude_roots = [expand(r) for r in deps.get("claude_roots", ["~/.claude/skills", ".claude/skills"])]
    rows = index_rows(SKILLS_INDEX.read_text(encoding="utf-8"))
    total = present = claude_ok = 0
    for row in rows:
        name = re.sub(r"（.*?）|\(.*?\)", "", row["名称"]).strip()
        link = re.search(r"\]\(<?(/[^)>]+SKILL\.md)>?\)", row.get("入口", ""))
        codex_only = bool(link and "/.codex/" in link.group(1))
        need = row.get("需要") or ("可选" if codex_only else "必需")
        source = plain(row.get("来源", "")) or "从原来源重新安装；来源没记录的问本人"
        total += 1
        path = Path(link.group(1)) if link and Path(link.group(1)).exists() else None
        if path is None:
            matches = skills.get(name.lower(), [])
            path = matches[0] if matches else None
        if path is None:
            report.append((need, "missing", f"技能 {name}：没找到", source))
            continue
        present += 1
        if codex_only:
            continue
        in_claude = any(path.is_relative_to(r) for r in claude_roots) or any((r / path.parent.name).exists() for r in claude_roots)
        if in_claude:
            claude_ok += 1
        else:
            report.append(("可选", "warn", f"技能 {name}：在 {path.parent}，Claude 找不到（Codex 不受影响）",
                           f"Claude 用户：把它链接或复制到 ~/.claude/skills/{path.parent.name}"))
    # 汇总行只显示数量，缺失项已在上面逐条列出，不重复计数
    report.append(("汇总", "ok" if present == total else "warn", f"技能 {present}/{total} 已装，其中 Claude 能直接调用 {claude_ok} 个", None))
    repo = deps.get("dev_repo")
    if repo:
        exists = expand(repo["path"]).exists()
        report.append(("可选", "ok" if exists else "warn", f"技能开发库：{'在本机' if exists else '本机没有'}（重装自研技能用）",
                       None if exists else f"git clone {repo['remote']} 到 {repo['path']}"))


def main():
    deps = json.loads(DEPENDENCIES.read_text(encoding="utf-8"))
    skills = skill_index(deps.get("skill_roots", ["~/.claude/skills", "~/.codex/skills", "~/.agents/skills", ".claude/skills"]))
    sections = []
    tools_report = []
    located = check_tools(deps, tools_report)
    sections.append(("工具与应用", tools_report))
    login_report = []
    check_logins(deps, located, skills, login_report)
    sections.append(("登录与凭据（只看状态，不读密钥）", login_report))
    skill_report = []
    check_skills(deps, skills, skill_report)
    sections.append(("技能（来自 agent/SKILLS_INDEX.md）", skill_report))

    missing_required, fixes = 0, []
    for title, items in sections:
        print(title)
        for need, status, text, fix in items:
            mark = MARK["ok"] if status == "ok" else (MARK["missing"] if need == "必需" else MARK["warn"])
            print(f"  {mark} {text}" + ("" if status == "ok" or need == "汇总" else f"〔{need}〕"))
            if status != "ok":
                missing_required += need == "必需"
                if fix:
                    fixes.append(f"  - {text.split('：')[0]}：{fix}")
    if fixes:
        print("\n怎么补（安装和登录先经本人同意，或由本人操作）：")
        print("\n".join(dict.fromkeys(fixes)))
    print("\n结果：" + ("通过" if not missing_required else f"缺 {missing_required} 项必需"))
    return 1 if missing_required else 0


if __name__ == "__main__":
    sys.exit(main())
