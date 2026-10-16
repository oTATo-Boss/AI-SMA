#!/usr/bin/env python3
"""Claude Code 和 Codex 共用的 PreToolUse 写入拦截：发布内容/、固定资产/ 只读；交付/ 只能整份新增，已有交付不改不删。

从标准输入读取钩子 JSON；拦截时输出 permissionDecision=deny，放行时不输出。两个软件的输出格式相同。
Claude 的编辑工具（Write、Edit、MultiEdit、NotebookEdit）按目标路径判断；Codex 的 apply_patch 按补丁里的文件头判断；
两边的 Bash 命令按常见写入命令、重定向和 cd 尽力解析，覆盖不了任意脚本内部的写入。
"""
import json
import os
import re
import shlex
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
READ_ONLY = ("发布内容", "固定资产")
DELIVERY = "交付"
EDIT_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}
# 删除或改动已有内容：命中任何受保护路径都拦截。
DESTRUCTIVE = {"rm", "rmdir", "unlink", "trash", "shred", "truncate", "chmod", "chflags", "chown", "chgrp", "xattr", "setfile"}
# 新建内容：只读目录拦截；交付/ 只允许写进还不存在的新包目录。
CREATING = {"touch", "mkdir", "tee"}
COPYING = {"cp", "rsync", "ditto", "install", "ln"}
PREFIXES = {"sudo", "command", "builtin", "nohup", "time", "nice", "env", "exec"}
SEPARATORS = {";", "&&", "||", "|", "&", "(", ")", "|&", ";;", "\n"}
GLOB = re.compile(r"[*?\[\]{}]")
# Codex apply_patch 补丁里的文件头：新增、修改、删除、改名后的目标。
PATCH_TARGET = re.compile(r"^\*\*\* (Add File|Update File|Delete File|Move to): (.+?)\s*$", re.M)


def classify(path):
    try:
        relative = Path(os.path.realpath(path)).relative_to(os.path.realpath(ROOT))
    except ValueError:
        return None, None
    if not relative.parts:
        return None, None
    if relative.parts[0] in READ_ONLY:
        return "readonly", relative
    if relative.parts[0] == DELIVERY:
        return "delivery", relative
    return None, None


def resolve(token, cwd):
    token = re.sub(r"\$\{?PWD\}?", str(cwd), token)
    token = re.sub(r"\$\{?HOME\}?", str(Path.home()), token)
    if "$" in token or "`" in token:
        return None  # 变量无法静态解析
    path = Path(os.path.expanduser(token))
    return path if path.is_absolute() else cwd / path


def new_package(relative):
    """交付/<包>/... 只有在 <包> 目录还不存在、且路径不含通配符时才算新增。"""
    if len(relative.parts) < 2 or GLOB.search(str(relative)):
        return False
    return not (ROOT / DELIVERY / relative.parts[1]).exists()


def check_target(token, cwd, mode, sources=()):
    path = resolve(token, cwd)
    if path is None:
        return None
    kind, relative = classify(path)
    if kind == "readonly":
        return f"{relative.parts[0]}/ 只读，不能改动：{token}"
    if kind == "delivery":
        if mode == "destructive":
            return f"交付/ 已有内容不能删改：{token}"
        if len(relative.parts) == 1:  # 复制到 交付/ 根目录：包名取源目录名
            for source in sources:
                name = Path(source.rstrip("/")).name
                if not name or (ROOT / DELIVERY / name).exists() or GLOB.search(name):
                    return f"交付/{name} 已存在或无法确认，不能合并、覆盖或追加"
            return None if sources else f"不能直接改动 交付/ 目录本身：{token}"
        if not new_package(relative):
            return f"交付/{relative.parts[1]} 已存在，修订要新建交付目录：{token}"
    return None


def operands(args):
    """去掉选项，保留路径参数；遇到 -- 之后都算路径。"""
    result, literal = [], False
    for arg in args:
        if literal or not arg.startswith("-") or arg == "-":
            result.append(arg)
        elif arg == "--":
            literal = True
    return result


def check_segment(words, cwd):
    while words and (re.fullmatch(r"\w+=.*", words[0]) or words[0] in PREFIXES):
        words = words[1:]
    if not words:
        return None, cwd
    name, args = os.path.basename(words[0]), words[1:]
    paths = operands(args)
    if name in {"cd", "pushd"}:
        target = resolve(paths[0], cwd) if paths else Path.home()
        return None, target if target is not None else cwd
    if name in DESTRUCTIVE:
        for token in paths:
            reason = check_target(token, cwd, "destructive")
            if reason:
                return reason, cwd
    if name in CREATING:
        for token in paths:
            reason = check_target(token, cwd, "create")
            if reason:
                return reason, cwd
    if name in COPYING or name == "mv":
        if len(paths) >= 2:
            sources, destination = paths[:-1], paths[-1]
            if name == "mv":
                for token in sources:
                    reason = check_target(token, cwd, "destructive")
                    if reason:
                        return reason, cwd
            return check_target(destination, cwd, "create", sources), cwd
    if name in {"sed", "perl"} and any(a.startswith("-i") or a.startswith("-pi") for a in args):
        for token in paths:
            reason = check_target(token, cwd, "destructive")
            if reason:
                return reason, cwd
    if name == "find" and {"-delete", "-exec", "-execdir", "-ok"} & set(args):
        for token in args:
            reason = check_target(token, cwd, "destructive") if not token.startswith("-") else None
            if reason:
                return "find 带删除或执行动作：" + reason, cwd
    if name == "dd":
        for arg in args:
            if arg.startswith("of="):
                reason = check_target(arg[3:], cwd, "create")
                if reason:
                    return reason, cwd
    return None, cwd


def check_bash(command, cwd):
    try:
        # 换行和 ; && | 一样分隔命令，避免多行命令里的第二条被并进第一条
        lexer = shlex.shlex(command, posix=True, punctuation_chars="();<>|&\n")
        lexer.whitespace = " \t\r"
        lexer.whitespace_split = True
        tokens = list(lexer)
    except ValueError:
        return None  # 引号不完整的命令本身无法执行
    segment, expect_redirect = [], False
    for token in tokens + [";"]:
        if expect_redirect:
            reason = check_target(token, cwd, "create")
            if reason:
                return reason
            expect_redirect = False
            continue
        if token.endswith(">") and set(token) <= set("&|>"):
            expect_redirect = True
            continue
        if token in SEPARATORS or (token and set(token) <= set(";&|()\n")):  # 空字符串参数（如 sed -i ''）不是分隔符
            reason, cwd = check_segment(segment, cwd)
            if reason:
                return reason
            segment = []
            continue
        segment.append(token)
    return None


def check_patch(text, cwd):
    """Codex 的补丁：只要碰到只读目录或交付目录就拦截（交付包要整份复制，不能用补丁写）。"""
    for _, target in PATCH_TARGET.findall(text):
        path = resolve(target.strip(), cwd)
        kind, relative = classify(path) if path is not None else (None, None)
        if kind == "readonly":
            return f"{relative.parts[0]}/ 只读，不能用补丁修改：{target}"
        if kind == "delivery":
            return f"交付/ 不能用补丁直接写；在任务的交付暂存目录做好后整份复制到全新目录：{target}"
    return None


def command_text(command):
    """Bash 的命令通常是字符串；有的客户端给数组（例如 ["bash", "-lc", "命令"]）。"""
    if isinstance(command, list):
        parts = [str(part) for part in command]
        return parts[-1] if len(parts) >= 3 and parts[1] in {"-c", "-lc"} else " ".join(parts)
    return command or ""


def decide(payload):
    tool = payload.get("tool_name")
    data = payload.get("tool_input") or {}
    cwd = Path(payload.get("cwd") or os.getcwd())
    if tool == "apply_patch":
        text = data if isinstance(data, str) else (data.get("command") or data.get("patch") or data.get("input") or "")
        return check_patch(command_text(text), cwd)
    if tool in EDIT_TOOLS:
        target = data.get("file_path") or data.get("notebook_path")
        if not target:
            return None
        path = resolve(target, cwd)
        kind, relative = classify(path) if path is not None else (None, None)
        if kind == "readonly":
            return f"{relative.parts[0]}/ 只读，不能用编辑工具修改：{target}"
        if kind == "delivery":
            return f"交付/ 不能用编辑工具直接写；在任务的交付暂存目录做好后整份复制到全新目录：{target}"
        return None
    if tool == "Bash":
        command = command_text(data.get("command"))
        reason = check_patch(command, cwd) if "*** Begin Patch" in command else None
        return reason or check_bash(command, cwd)
    return None


def main():
    reason = decide(json.load(sys.stdin))
    if reason:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                                 "permissionDecisionReason": "项目写入保护：" + reason + "（规则见 AGENTS.md 红线 2、3）"}},
                         ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # 钩子自身出错时报告但不阻断（退出码 1 不是拦截信号；2 才是）
        print(f"写入保护钩子出错：{type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(1)
