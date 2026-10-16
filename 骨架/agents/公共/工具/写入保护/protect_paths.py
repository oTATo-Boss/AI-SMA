#!/usr/bin/env python3
"""Claude Code 和 Codex 共用的 PreToolUse 写入拦截：发布内容/、固定资产/ 只读；交付/ 只能整份新增，已有交付不改不删。

从标准输入读取钩子 JSON；拦截时输出 permissionDecision=deny，放行时不输出。两个软件的输出格式相同。
Claude 的编辑工具（Write、Edit、MultiEdit、NotebookEdit）按目标路径判断；Codex 的 apply_patch 按补丁里的文件头判断；
两边的 Bash 命令按常见写入命令、重定向和 cd 尽力解析，覆盖不了任意脚本内部的写入。
"""
import json
import ntpath
import os
import re
import shlex
import sys
from pathlib import Path, PureWindowsPath

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
SHELL_TOOLS = {"Bash", "PowerShell", "powershell", "exec_command", "shell_command", "run_shell_command", "shell"}


def windows_path(value):
    return bool(re.match(r"^(?:[a-zA-Z]:|\\\\)", str(value)))


def canonical(path, windows=False, real=True):
    """Windows realpath resolves junctions on Windows; foreign paths use lexical normalization for inspection."""
    value = os.path.realpath(path) if real and (os.name == "nt" or not windows) else str(path)
    if windows:
        if value.startswith("\\\\?\\UNC\\"):
            value = "\\\\" + value[8:]
        elif value.startswith("\\\\?\\"):
            value = value[4:]
        return ntpath.normcase(ntpath.normpath(value))
    return os.path.normpath(value)


def classify(path):
    windows = os.name == "nt" or windows_path(ROOT)
    # Check both the real destination and the protected route used to reach it.
    for real in (True, False):
        try:
            root, target = canonical(ROOT, windows, real), canonical(path, windows, real)
            if windows:
                if ntpath.commonpath([root, target]) != root:
                    continue
                relative = PureWindowsPath(ntpath.relpath(target, root))
            else:
                relative = Path(target).relative_to(root)
        except ValueError:
            continue
        if not relative.parts:
            continue
        if relative.parts[0] in READ_ONLY:
            return "readonly", relative
        if relative.parts[0] == DELIVERY:
            return "delivery", relative
    return None, None


def resolve(token, cwd):
    token = str(token)
    token = re.sub(r"\$\{?PWD\}?|%CD%", lambda _: str(cwd), token, flags=re.I)
    token = re.sub(r"\$\{?(?:env:)?(?:HOME|USERPROFILE)\}?|%(?:HOME|USERPROFILE)%",
                   lambda _: str(Path.home()), token, flags=re.I)
    if "$" in token or "`" in token or re.search(r"%[^%]+%", token):
        return None  # 变量无法静态解析
    if os.name == "nt" or windows_path(cwd) or windows_path(token):
        return PureWindowsPath(ntpath.normpath(ntpath.join(str(cwd), token)))
    # PowerShell accepts backslashes on Unix too; native Bash keeps normal POSIX semantics.
    path = Path(os.path.expanduser(token))
    return path if path.is_absolute() else cwd / path


def new_package(relative):
    """交付/<包>/... 只有在 <包> 目录还不存在、且路径不含通配符时才算新增。"""
    if len(relative.parts) < 2 or GLOB.search(str(relative)):
        return False
    return not (Path(ROOT) / DELIVERY / relative.parts[1]).exists()


def check_target(token, cwd, mode, sources=()):
    path = resolve(token, cwd)
    if path is None:
        return None
    if mode == "destructive":
        windows = os.name == "nt" or windows_path(ROOT)
        root, target = canonical(ROOT, windows), canonical(path, windows)
        try:
            common = ntpath.commonpath([root, target]) if windows else os.path.commonpath([root, target])
            if common == target:
                return f"不能删改包含受保护目录的项目或祖先目录：{token}"
        except ValueError:
            pass
    kind, relative = classify(path)
    if kind == "readonly":
        return f"{relative.parts[0]}/ 只读，不能改动：{token}"
    if kind == "delivery":
        if mode == "destructive":
            return f"交付/ 已有内容不能删改：{token}"
        if len(relative.parts) == 1:  # 复制到 交付/ 根目录：包名取源目录名
            for source in sources:
                name = PureWindowsPath(source.rstrip("/\\")).name if "\\" in source else Path(source.rstrip("/")).name
                if not name or (Path(ROOT) / DELIVERY / name).exists() or GLOB.search(name):
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
    if name.lower() in {"pwsh", "powershell", "pwsh.exe", "powershell.exe"}:
        for index, arg in enumerate(args):
            if arg.lower() in {"-command", "-c"} and index + 1 < len(args):
                return check_powershell(" ".join(args[index + 1:]), cwd), cwd
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


def powershell_tokens(command):
    """A deliberately limited shell lexer: preserve Windows backslashes and quoted spaces."""
    tokens, word, quote, position = [], [], None, 0
    while position < len(command):
        character = command[position]
        if quote:
            if character == quote:
                if position + 1 < len(command) and command[position + 1] == quote:
                    word.append(quote)
                    position += 1
                else:
                    quote = None
            elif character == "`" and quote == '"' and position + 1 < len(command):
                position += 1
                word.append(command[position])
            else:
                word.append(character)
        elif character in "\"'":
            quote = character
        elif character == "`" and position + 1 < len(command):
            position += 1
            word.append(command[position])
        elif character in " \t\r;|&<>\n":
            if word:
                tokens.append("".join(word))
                word = []
            if character not in " \t\r":
                if character in ">|&" and tokens and tokens[-1] == character:
                    tokens[-1] += character
                else:
                    tokens.append(character)
        else:
            word.append(character)
        position += 1
    if quote:
        return []  # An incomplete command cannot execute as written.
    if word:
        tokens.append("".join(word))
    return tokens


PS_ALIASES = {
    "sc": "set-content", "ac": "add-content", "clc": "clear-content", "ni": "new-item",
    "ri": "remove-item", "rm": "remove-item", "del": "remove-item", "erase": "remove-item",
    "rd": "remove-item", "rmdir": "remove-item", "mi": "move-item", "mv": "move-item",
    "move": "move-item", "cpi": "copy-item", "cp": "copy-item", "copy": "copy-item",
    "rni": "rename-item", "ren": "rename-item", "rename": "rename-item",
    "sl": "set-location", "cd": "set-location", "chdir": "set-location",
    "pushd": "set-location", "tee": "tee-object", "md": "new-item", "mkdir": "new-item",
}
PS_VALUE_OPTIONS = {"path", "literalpath", "filepath", "destination", "newname", "value", "name",
                    "itemtype", "encoding", "filter", "include", "exclude", "erroraction",
                    "warningaction", "informationaction", "inputobject", "stream", "delimiter"}
PS_PATH_OPTIONS = ("literalpath", "path", "filepath")


def ps_arguments(args):
    named, positional, index = {}, [], 0
    while index < len(args):
        token = args[index]
        if token.startswith("-"):
            key, separator, value = token.lstrip("-").partition(":")
            key = key.lower()
            if not separator and key in PS_VALUE_OPTIONS and index + 1 < len(args):
                index += 1
                value = args[index]
            if value:
                named.setdefault(key, []).extend(value.split(","))
        elif not re.fullmatch(r"/[a-zA-Z]+", token):  # cmd-compatible switches: /S /Q /Y
            positional.extend(token.split(","))
        index += 1
    return named, positional


def ps_path(token):
    # FileSystem:: is a PowerShell provider prefix; other providers are outside this filesystem hook.
    token = re.sub(r"^(?:Microsoft\.PowerShell\.Core\\)?FileSystem::", "", token, flags=re.I)
    return token.replace("\\", "/") if os.name != "nt" and not windows_path(ROOT) else token


def check_powershell_segment(words, cwd):
    if not words:
        return None, cwd
    name = ntpath.basename(words[0]).lower()
    if name in {"powershell", "powershell.exe", "pwsh", "pwsh.exe"}:
        for index, arg in enumerate(words[1:], 1):
            if arg.lower() in {"-command", "-c"} and index + 1 < len(words):
                return check_powershell(" ".join(words[index + 1:]), cwd), cwd
    name = PS_ALIASES.get(name, name)
    named, positional = ps_arguments(words[1:])
    paths = next((named[key] for key in PS_PATH_OPTIONS if key in named), [])
    if name == "set-location":
        target = paths[0] if paths else (positional[0] if positional else str(Path.home()))
        return None, resolve(ps_path(target), cwd) or cwd
    if name in {"copy-item", "move-item"}:
        sources = paths or (positional[:-1] if "destination" not in named else positional)
        destinations = named.get("destination", positional[-1:] if not paths else positional[:1])
        if name == "move-item":
            for source in sources:
                reason = check_target(ps_path(source), cwd, "destructive")
                if reason:
                    return reason, cwd
        for destination in destinations:
            reason = check_target(ps_path(destination), cwd, "create", [ps_path(s) for s in sources])
            if reason:
                return reason, cwd
    writes = {"set-content", "add-content", "clear-content", "out-file", "export-csv", "export-clixml",
              "new-item", "set-item", "remove-item", "rename-item", "set-itemproperty", "remove-itemproperty",
              "set-acl", "tee-object", "attrib"}
    if name in writes:
        targets = paths or (positional[:1] if name not in {"remove-item", "attrib"} else positional)
        mode = "destructive" if name in {"remove-item", "rename-item", "clear-content", "set-acl", "attrib"} else "create"
        for target in targets:
            reason = check_target(ps_path(target), cwd, mode)
            if reason:
                return reason, cwd
        if name == "rename-item":
            # Rename-Item -NewName normally accepts a basename; checking full paths closes obvious misuse too.
            for target in named.get("newname", positional[1:2]):
                reason = check_target(ps_path(target), cwd, "create")
                if reason:
                    return reason, cwd
    return None, cwd


def check_powershell(command, cwd):
    segment, redirect = [], False
    for token in powershell_tokens(command) + [";"]:
        if redirect:
            reason = check_target(ps_path(token), cwd, "create")
            if reason:
                return reason
            redirect = False
            continue
        if token in {">", ">>"}:
            redirect = True
        elif token in {";", "\n", "|", "||", "&&", "&"}:
            reason, cwd = check_powershell_segment(segment, cwd)
            if reason:
                return reason
            segment = []
        else:
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
        return parts[-1] if len(parts) >= 3 and parts[1].lower() in {"-c", "-lc", "-command"} else " ".join(parts)
    return command or ""


def decide(payload):
    tool = (payload.get("tool_name") or "").rsplit(".", 1)[-1]
    data = payload.get("tool_input") or {}
    cwd_text = (data.get("workdir") if isinstance(data, dict) else None) or payload.get("cwd") or os.getcwd()
    cwd = PureWindowsPath(cwd_text) if windows_path(cwd_text) else Path(cwd_text)
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
    if tool in SHELL_TOOLS:
        raw_command = data.get("command") or data.get("cmd") or ""
        command = command_text(raw_command)
        reason = check_patch(command, cwd) if "*** Begin Patch" in command else None
        shell = str(data.get("shell") or "").lower()
        if isinstance(raw_command, list) and raw_command:
            shell = str(raw_command[0]).lower()
        powershell = (tool.lower() == "powershell" or "powershell" in shell or "pwsh" in shell
                      or (windows_path(cwd) and not any(name in shell for name in ("bash", "zsh", "sh.exe"))))
        return reason or (check_powershell(command, cwd) if powershell else check_bash(command, cwd))
    return None


def main():
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
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
