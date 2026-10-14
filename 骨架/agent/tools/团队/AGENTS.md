# 团队工具

多角色协作用的两个脚本，在项目根目录运行，Python 3.9+ 标准库。协议见 `agent/团队/README.md`，产物格式见 `agent/团队/合同.md`。

## 生成角色配置

```bash
python3 agent/tools/团队/生成角色.py
python3 agent/tools/团队/生成角色.py --check
```

- 从 `agent/团队/*/角色.md` 生成 Claude Code 的 `.claude/agents/<id>.md` 和 Codex 的 `.codex/agents/<id>.toml`。改角色只改 `角色.md`，再运行一次；生成的文件不要手改。
- Claude Code 的配置会预加载角色列出的技能（本机找不到的会在角色说明里注明）、限定工具、禁止角色再派子 Agent。Codex 的角色只能继承主会话的工具和权限，靠角色说明约束；Codex 只在信任这个项目后才读 `.codex/` 里的配置。
- `--check` 只检查是否最新，项目检查会调用它。

## 校验产物

```bash
python3 agent/tools/团队/校验产物.py agent/工作/<任务目录>
python3 agent/tools/团队/校验产物.py agent/账号数据/爆款库
```

- 检查字段和取值、依据（爆款库条目、项目文件）是否存在、创意评审选中的方案是否打过分、审片报告对应的成片在审片后有没有被改过、样本不足的经验有没有被标成已验证。
- 只看带 `artifact` 字段的 JSON；直接指定的文件都会校验。

## 测试

```bash
python3 -m unittest agent/tools/团队/tests/test_team.py
```
