# 写入保护（Claude Code 钩子）

把红线 2、3 变成硬拦截：`发布内容/`、`固定资产/` 只读；`交付/` 只能整份新增全新目录，已有交付不改、不删、不追加。配置在项目根目录 `.claude/settings.json`：PreToolUse 钩子调用 `protect_paths.py`，另有 `permissions.deny` 的 Edit 规则作第二层。

- 编辑工具（Write、Edit、MultiEdit、NotebookEdit）写这三个目录一律拦截，交付包用 Bash 整份复制（见 `../发布包/AGENTS.md`）。
- Bash 按常见写入命令（rm、mv、cp、rsync、mkdir、touch、chmod、sed -i、tee、dd 等）、重定向和 cd 解析目标路径，经软链接的路径也会还原到真实位置；复制到 `交付/` 时，只有目标包目录还不存在才放行。
- 限制：Python 等脚本内部的写入、xargs 传入的路径、tar／unzip 解压目标无法静态判断，仍要遵守规则。只对 Claude Code 生效，Codex 等其他客户端按 `AGENTS.md` 红线自觉执行。
- 钩子自身出错时报告错误但不阻断（避免卡住所有工具）；改动后运行测试：

```bash
OTATO_TEST_ARTIFACT_DIR=<隔离目录> python3 -m unittest agent/tools/写入保护/tests/test_protect_paths.py
```

本人确实要改这些目录时自己在 Finder 里操作，或明确同意后临时调整 `.claude/settings.json`。
