# 写入保护（Claude、Codex 钩子）

`发布内容/`、`固定资产/` 只读；`交付/` 只接受全新包，已有包不能修改、删除或追加。两个客户端使用同一个 `protect_paths.py` 判断常见写入，属于辅助检查，**不是文件系统沙盒**。

## 启动与部署接口

- Claude 使用 `.claude/settings.json` 的 PreToolUse 钩子，另保留 `permissions.deny` 的 Edit 规则。
- Codex 使用 `.codex/hooks.json` 的 PreToolUse 钩子。项目配置是否加载、钩子是否获准，以当前客户端的信任和钩子状态为准；写入配置文件不代表已启用。
- `hook_entry.py` 先读客户端输入，再从指定项目、`CLAUDE_PROJECT_DIR`、输入 `cwd` 和进程 `cwd` 向上查找项目。部署配置带项目路径作为回退，工具在项目外启动时仍可检查指向项目内的绝对路径。
- 模板中的 Python 定位命令适用于从项目目录及其子目录启动；部署器必须按实际解释器和 shell 重新生成命令，不依赖 POSIX 的 `while`、`dirname` 或 `$PWD`。

`hook_config.py` 提供纯函数，不执行安装或写文件：

```python
configs = render_hooks(project_root, python_executable=sys.executable,
                       os_name=os.name, shell=None)
codex_config = merge_hooks(existing_codex, configs["codex"])
claude_config = merge_hooks(existing_claude, configs["claude"])
```

`shell` 可选 `posix`、`powershell`、`cmd`；Windows 默认 `cmd`，其他系统默认 `posix`。生成器保留中文、空格和命令元字符路径，并使用实际 Python。`cmd` 会展开成对百分号变量；若项目或解释器路径含这类文字，须选择 PowerShell 启动方式。`merge_hooks` 只替换本项目的旧保护命令，保留用户其他钩子、权限、模型设置。移动项目或更换解释器后重新生成。

## 检查行为

- 编辑工具（Write、Edit、MultiEdit、NotebookEdit、apply_patch）写保护目录一律拒绝。交付包在任务暂存目录做好后，用复制命令整体送入全新目录。
- POSIX 命令识别常见删除、移动、复制、新建、属性修改、`sed -i`、`tee`、`dd`、重定向和 `cd`。
- PowerShell 识别 `Set-Content`、`Add-Content`、`Clear-Content`、`Out-File`、`Export-Csv`、`New-Item`、`Remove-Item`、`Move-Item`、`Copy-Item`、`Rename-Item`、`Set-ItemProperty`、`Set-Acl`、常见别名、参数形式、重定向和 `Set-Location`。包装在 `pwsh -Command` 的命令也检查。
- Windows 路径按 drive/UNC 和大小写归一，处理 `..` 和 extended path 前缀。原生 Windows 使用真实路径解析 directory junction；POSIX 使用真实路径解析软链接。
- `exec_command` 的 `workdir` 优先于客户端全局 `cwd`。无法静态解析的变量不猜测成确定路径。

## 明确限制

任意 Python／Node 脚本内部写入、动态变量、`Invoke-Expression`、编码 PowerShell 命令、复杂 shell 表达式、`xargs`、归档解压及未识别的命令可能绕过这项辅助检查。未知命令放行不等于获准修改受保护内容，仍须遵守项目规则。客户端未加载钩子时没有拦截能力。

找不到项目会在 stderr 说明未执行检查；钩子自身出错会报告错误但不阻断全部工具。没有声称这两种状态受到了完整保护。本人要求修订保护目录时，按明确范围处理授权，不把静态保护当成完整权限系统。

## 验证

```bash
python3 -m unittest discover -s agents/公共/工具/写入保护/tests -v
```

测试在临时夹具中检查决定，不执行待拦截的破坏性命令。包含实际 Python 钩子进程、嵌套工作目录、解释器路径引用、已有用户设置保留，以及 Windows 路径词法测试。Windows CI 使用原生 junction 夹具；非 Windows 上的 drive/UNC 测试仅验证词法规则，不能当作原生 Windows 或客户端钩子激活证据。真实 Codex／Claude 激活仍需单独记录。
