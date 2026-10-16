#!/usr/bin/env python3
"""Portable hook entry point. Locate the project from client context without a shell ancestor loop."""
import argparse
import importlib.util
import json
import os
import sys
from pathlib import Path

SCRIPT = Path("agents") / "公共" / "工具" / "写入保护" / "protect_paths.py"


def locate_project(payload, project=None):
    # An explicitly generated project path prevents a child tool cwd outside the project losing protection.
    candidates = [project, os.environ.get("CLAUDE_PROJECT_DIR"), payload.get("cwd"), os.getcwd()]
    for value in candidates:
        if not value:
            continue
        path = Path(value).resolve()
        for parent in (path, *path.parents):
            if (parent / SCRIPT).is_file():
                return parent
    return None


def main(argv=None):
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", help="Deployment-generated project path; otherwise search client cwd ancestors")
    args = parser.parse_args(argv)
    payload = json.load(sys.stdin)
    root = locate_project(payload, args.project)
    if root is None:
        print("写入保护：未找到项目，未执行路径检查。", file=sys.stderr)
        return 0
    spec = importlib.util.spec_from_file_location("ai_sma_protect_paths", root / SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.ROOT = root
    reason = module.decide(payload)
    if reason:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                          "permissionDecisionReason": "项目写入保护：" + reason + "（规则见 AGENTS.md）"}}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"写入保护入口出错：{type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(1)
