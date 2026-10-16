# 写入保护（Claude、Codex 钩子）

把入口红线 2、3 变成硬拦截：`发布内容/`、`固定资产/` 只读；`交付/` 只能整份新增全新目录，已有交付不改、不删、不追加。两个软件调用同一个 `protect_paths.py`：

- Claude：项目根目录 `.claude/settings.json` 的 PreToolUse 钩子，另有 `permissions.deny` 的 Edit 规则作第二层。
- Codex：项目根目录 `.codex/hooks.json` 的 PreToolUse 钩子。Codex 只在本人信任这个文件夹后才加载项目里的钩子，第一次还要本人在 Codex 里用 `/hooks` 看过并批准；钩子内容改了要重新批准。钩子命令会从当前目录往上找项目根目录，找不到就放行。

拦截范围：

- 编辑工具（Claude 的 Write、Edit、MultiEdit、NotebookEdit，Codex 的 apply_patch）写这三个目录一律拦截；交付包用命令整份复制（见 `agents/role/后期/工具/发布包/README.md`）。
- 命令（两个软件都叫 Bash）按常见写入命令（rm、mv、cp、rsync、mkdir、touch、chmod、sed -i、tee、dd 等）、重定向和 cd 解析目标路径，经软链接的路径也会还原到真实位置；命令里带补丁内容的也按补丁检查。复制到 `交付/` 时，只有目标包目录还不存在才放行。
- 限制：Python 等脚本内部的写入、xargs 传入的路径、tar／unzip 解压目标无法静态判断，仍要遵守规则。钩子是兜底，不是完整的权限边界。
- 钩子自身出错时报告错误但不阻断（避免卡住所有工具）；改动后运行测试：

```bash
OTATO_TEST_ARTIFACT_DIR=<隔离目录> python3 -m unittest agents/公共/工具/写入保护/tests/test_protect_paths.py
```

本人确实要改这些目录时自己在 Finder 里操作，或明确同意后临时调整 `.claude/settings.json`、`.codex/hooks.json`。
