"""Generate client hook commands using the deployment interpreter and actual host shell.

No file writes, package installation or client activation occur in these functions.
"""
import copy
import os
import re
import shlex
import sys
from pathlib import Path, PureWindowsPath

HOOK_ID = "ai-sma-path-protection"
HOOK_RELATIVE = "agents/公共/工具/写入保护/hook_entry.py"
MATCHERS = {
    "codex": "Bash|PowerShell|exec_command|shell_command|run_shell_command|shell|apply_patch",
    "claude": "Write|Edit|MultiEdit|NotebookEdit|Bash|PowerShell",
}


def quote_command(arguments, shell):
    if shell == "posix":
        return " ".join(shlex.quote(str(argument)) for argument in arguments)
    if shell == "powershell":
        return "& " + " ".join("'" + str(argument).replace("'", "''") + "'" for argument in arguments)
    if shell == "cmd":
        # Quote every argument, including paths containing & without spaces. Preserve Windows argv escaping.
        quoted = []
        for argument in arguments:
            text = str(argument)
            if re.search(r"%[^%]+%", text):
                raise ValueError("cmd expands percent variables in paths; generate the hook with shell='powershell'")
            text = re.sub(r'(\\*)"', lambda match: "\\" * (len(match[1]) * 2 + 1) + '"', text)
            trailing = len(text) - len(text.rstrip("\\"))
            quoted.append('"' + text + "\\" * trailing + '"')
        return " ".join(quoted)
    raise ValueError(f"unsupported hook shell: {shell}")


def render_hooks(root=None, python_executable=None, os_name=None, shell=None):
    """Return {'codex': config_fragment, 'claude': config_fragment} without changing files.

    root=None creates portable repository examples; deployments must supply the actual absolute root.
    os_name accepts os.name or platform.system(): nt/Windows, posix/Darwin/Linux.
    shell is posix, powershell, or cmd; defaults to cmd on Windows and posix elsewhere.
    """
    windows = (os_name or os.name).lower() in {"nt", "windows"}
    shell = shell or ("cmd" if windows else "posix")
    executable = python_executable or ("python" if windows else (sys.executable if root else "python3"))
    if root:
        project = PureWindowsPath(root) if windows else Path(root).resolve()
        arguments = [executable, str(project / HOOK_RELATIVE), "--project", str(project)]
    else:
        # Syntax works in POSIX shells and cmd. No $PWD, dirname, while loop, or platform-specific path is embedded.
        locator = (
            "import pathlib,runpy; "
            "p=pathlib.Path.cwd().resolve(); "
            "s=next((d/'agents/公共/工具/写入保护/hook_entry.py' for d in (p,*p.parents) "
            "if (d/'agents/公共/工具/写入保护/hook_entry.py').is_file()),None); "
            "runpy.run_path(str(s),run_name='__main__') if s else None"
        )
        arguments = [executable, "-c", locator]
    command = quote_command(arguments, shell)
    result = {}
    for client, matcher in MATCHERS.items():
        hook = {"type": "command", "command": command, "timeout": 10}
        if client == "codex":
            hook["statusMessage"] = "检查项目写入保护"
        result[client] = {"hooks": {"PreToolUse": [{"matcher": matcher, "hooks": [hook]}]}}
    return result


def merge_hooks(existing, rendered):
    """Keep unrelated client settings and hook groups; replace this project's previous hook only."""
    result = copy.deepcopy(existing or {})
    groups = result.setdefault("hooks", {}).get("PreToolUse", [])
    retained = []
    for group in groups:
        group = copy.deepcopy(group)
        group["hooks"] = [hook for hook in group.get("hooks", [])
                          if not any(marker in str(hook.get("command", ""))
                                     for marker in ("写入保护/", "写入保护\\", "protect_paths.py", "hook_entry.py"))]
        if group["hooks"]:
            retained.append(group)
    result["hooks"]["PreToolUse"] = retained + copy.deepcopy(rendered["hooks"]["PreToolUse"])
    return result
