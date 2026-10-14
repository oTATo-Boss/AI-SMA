#!/usr/bin/env python3
"""从账号模板新建账号项目：复制骨架、填入账号名、写第一条日志、生成任务总览、运行项目检查，并列出还要手填的地方。"""
import argparse
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

VERSION = "v0"
TEMPLATE = Path(__file__).resolve().parent
SKELETON = TEMPLATE / "骨架"
TEXT_SUFFIXES = {".md", ".yaml", ".yml", ".json", ".py", ".txt"}


def fail(message):
    print("停止：" + message)
    return 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", required=True, help="账号名，会写进入口和账号配置")
    parser.add_argument("--dest", help="新项目目录，默认当前目录下的 @<账号名>")
    parser.add_argument("--browser-profile", help="Chrome 里给这个账号用的个人资料名；不填就留待填写")
    args = parser.parse_args()

    name = args.name.strip()
    if not name or re.search(r'[/\\:*?"<>|]', name):
        return fail("账号名不能为空，也不能含路径或文件系统不允许的字符")
    dest = Path(args.dest).expanduser() if args.dest else Path.cwd() / f"@{name}"
    dest = dest.resolve()
    if dest.exists():
        return fail(f"{dest} 已存在，不合并、不覆盖；换一个目录")
    if TEMPLATE in dest.parents or dest == TEMPLATE:
        return fail("新项目不能建在模板目录里面")

    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    values = {"{{账号名}}": name, "{{浏览器资料}}": args.browser_profile or "待填写：Chrome 个人资料名"}
    shutil.copytree(SKELETON, dest, symlinks=False, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store"))
    for folder in ("交付", "发布内容", "固定资产"):  # 空目录不进仓库，新建时补上
        (dest / folder).mkdir(exist_ok=True)
    for path in dest.rglob("*"):
        if path.is_file() and path.suffix in TEXT_SUFFIXES:
            text = path.read_text(encoding="utf-8")
            filled = text
            for key, value in values.items():
                filled = filled.replace(key, value)
            if filled != text:
                path.write_text(filled, encoding="utf-8")

    log = dest / "agent/log" / now.strftime("%Y-%m") / (now.strftime("%Y-%m-%d") + ".md")
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(f"# {now:%Y-%m-%d}\n\n- {now:%H:%M} · agent · 从账号模板 {VERSION} 新建项目 · "
                   f"下一步按模板说明的顺序填写账号配置、账号信息和定位 · `AGENTS.md`\n", encoding="utf-8")

    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    subprocess.run([sys.executable, str(dest / "agent/tools/任务管理/任务管理.py"), "sync"], check=True, env=env, stdout=subprocess.DEVNULL)
    print(f"已新建：{dest}\n", flush=True)
    check = subprocess.run([sys.executable, str(dest / "agent/tools/项目检查/检查.py")], env=env)
    print("\n本机环境：", flush=True)
    environment = subprocess.run([sys.executable, str(dest / "agent/tools/环境检查/检查环境.py")], env=env)

    pending = []
    for path in sorted(dest.rglob("*")):
        if path.is_file() and path.suffix in {".md", ".yaml", ".yml"}:
            count = path.read_text(encoding="utf-8").count("待填写")
            if count:
                pending.append(f"  {path.relative_to(dest)}：{count} 处")
    print("\n还要手填的地方（搜索“待填写”）：")
    print("\n".join(pending) if pending else "  无")
    print("\n建议顺序：账号配置.yaml → 账号信息.md → 定位与策略.md（先跑一轮定位与对标）→ 内容与交付.md 第 1–3 节"
          " → 附录 → SKILLS_INDEX.md → RunningHub 授权（要用时）。品牌资产放进 固定资产/。")
    print("另外：给这个账号建一个 Chrome 个人资料并登录它的平台后台；资料名没传的话写进根目录 AGENTS.md 和项目规则第 4 节。")
    return check.returncode or environment.returncode


if __name__ == "__main__":
    sys.exit(main())
