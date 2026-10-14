#!/usr/bin/env python3
"""把 AI-SMA 模板部署到账号项目文件夹（默认当前文件夹）：复制骨架、填入账号名、写第一条日志、生成任务总览、运行项目检查和环境检查，并列出还要手填的地方。"""
import argparse
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

VERSION = "v0.8"
TEMPLATE = Path(__file__).resolve().parent
SKELETON = TEMPLATE / "骨架"
TEXT_SUFFIXES = {".md", ".yaml", ".yml", ".json", ".py", ".txt"}
IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store")


def fail(message):
    print("停止：" + message)
    return 1


def skeleton_entries():
    """骨架里会被复制的目录和文件，相对骨架的路径。"""
    for root, dirs, files in os.walk(SKELETON):
        skipped = IGNORE(root, dirs + files)
        dirs[:] = sorted(d for d in dirs if d not in skipped)
        for name in dirs:
            yield Path(root, name).relative_to(SKELETON), True
        for name in sorted(files):
            if name not in skipped:
                yield Path(root, name).relative_to(SKELETON), False


def check_existing(dest):
    """目标文件夹已存在时：只允许有隐藏文件，且和骨架不冲突。返回停止原因，没问题返回 None。"""
    if not dest.is_dir():
        return f"{dest} 不是文件夹"
    visible = sorted(p.name for p in dest.iterdir() if not p.name.startswith("."))
    if dest in TEMPLATE.parents and visible == [TEMPLATE.relative_to(dest).parts[0]]:
        inner = dest / visible[0]
        return f'模板仓库克隆在目标文件夹里（{inner}）。先把它移到临时目录再运行，例如：mv "{inner}" "$(mktemp -d)"/'
    if visible:
        listed = "、".join(visible[:5]) + (" 等" if len(visible) > 5 else "")
        return (f"{dest} 里已有文件：{listed}。先确认没开错文件夹；确实要用这个文件夹，"
                "先把这些文件移走，部署后再放回（品牌素材放进 固定资产/）")
    conflicts = []
    for rel, is_dir in skeleton_entries():
        target = dest / rel
        if target.is_symlink() or (target.exists() and (not is_dir or not target.is_dir())):
            conflicts.append(str(rel))
    if conflicts:
        return "已有同名文件或链接，不覆盖：" + "、".join(conflicts)
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dest", help="账号项目文件夹，默认当前文件夹；可以已经建好，但里面只能有隐藏文件")
    parser.add_argument("--name", help="账号名，默认取文件夹名（去掉开头的 @）")
    parser.add_argument("--browser-profile", help="Chrome 里给这个账号用的个人资料名；不填就留待填写")
    args = parser.parse_args()

    dest = (Path(args.dest).expanduser() if args.dest else Path.cwd()).resolve()
    name = (args.name if args.name is not None else dest.name.lstrip("@")).strip()
    if not name or re.search(r'[/\\:*?"<>|]', name):
        return fail("看不出账号名：用 --name 指定，不能含路径或文件系统不允许的字符")
    if dest == TEMPLATE or TEMPLATE in dest.parents:
        return fail("账号项目不能建在模板仓库里面")
    if dest.exists():
        problem = check_existing(dest)
        if problem:
            return fail(problem)

    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    values = {"{{账号名}}": name, "{{浏览器资料}}": args.browser_profile or "待填写：Chrome 个人资料名"}
    shutil.copytree(SKELETON, dest, symlinks=False, ignore=IGNORE, dirs_exist_ok=True)
    for folder in ("交付", "发布内容", "固定资产"):  # 空目录不进仓库，部署时补上
        (dest / folder).mkdir(exist_ok=True)
    copied = [rel for rel, is_dir in skeleton_entries() if not is_dir]
    for rel in copied:
        path = dest / rel
        if path.suffix in TEXT_SUFFIXES:
            text = path.read_text(encoding="utf-8")
            filled = text
            for key, value in values.items():
                filled = filled.replace(key, value)
            if filled != text:
                path.write_text(filled, encoding="utf-8")

    log = dest / "agent/log" / now.strftime("%Y-%m") / (now.strftime("%Y-%m-%d") + ".md")
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(f"# {now:%Y-%m-%d}\n\n- {now:%H:%M} · agent · 从 AI-SMA {VERSION} 部署项目 · "
                   f"下一步按 `sop/新账号开工.md` 带本人开工 · `AGENTS.md`\n", encoding="utf-8")

    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    subprocess.run([sys.executable, str(dest / "agent/tools/任务管理/任务管理.py"), "sync"], check=True, env=env, stdout=subprocess.DEVNULL)
    print(f"已部署：{dest}（账号名：{name}）\n", flush=True)
    check = subprocess.run([sys.executable, str(dest / "agent/tools/项目检查/检查.py")], env=env)
    print("\n本机环境：", flush=True)
    environment = subprocess.run([sys.executable, str(dest / "agent/tools/环境检查/检查环境.py")], env=env)

    pending = []
    for rel in copied:
        if rel.suffix in {".md", ".yaml", ".yml"} and rel.parts[:2] != ("agent", "sop"):
            count = (dest / rel).read_text(encoding="utf-8").count("待填写")
            if count:
                pending.append(f"  {rel}：{count} 处")
    print("\n还要手填的地方（搜索“待填写”）：")
    print("\n".join(pending) if pending else "  无")
    print("\n下一步：agent 按 agent/sop/新账号开工.md 马上回复本人：怎么用、要准备的、要回答的问题。")
    print("自己在终端部署的：在这个文件夹打开 Claude Code 或 Codex，随便说一句，agent 会接着带你开工。")
    return check.returncode or environment.returncode


if __name__ == "__main__":
    sys.exit(main())
