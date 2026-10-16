# 团队工具

多智能体协作用的两个脚本，在项目根目录运行，Python 3.9+ 标准库。团队说明见 `agents/README.md`，产物格式见 `agents/公共/合同.md`。

## 生成登记文件

```bash
python3 agents/公共/工具/团队/生成角色.py
python3 agents/公共/工具/团队/生成角色.py --check
```

- 读 `agents/role/*/agent.yaml`，给每个子智能体生成 Claude 的 `.claude/agents/<编号>.md` 和 Codex 的 `.codex/agents/<编号>.toml`；总负责人（`main: true`）是主对话，不生成。登记文件只有名字、派工说明、思考深度、工具限制和一句"先完整读你的说明书和经验"，所以改说明书不用重新生成；改了配置卡再运行一次。生成的文件不要手改。
- 同时生成 `.codex/config.toml`，把 `agents/账号/账号配置.yaml` 的 autonomy.max_parallel_agents 写成 Codex 同时干活的子智能体上限。这个文件已经被本人改成自己的设置时不覆盖，只提示。
- Claude 的登记文件会预加载配置卡列出的技能（本机找不到的会注明）、限定工具、禁止子智能体再派子智能体。Codex 的子智能体沙盒和审批跟着主对话走，靠说明书约束；Codex 只在信任这个项目后才读 `.codex/` 里的配置。
- 同时检查智能体包：每个都要有 `AGENT.md`、`agent.yaml`、`记忆/经验.md`，编号不能重复。
- `--check` 只检查是否最新，项目检查会调用它。

## 校验产物

```bash
python3 agents/公共/工具/团队/校验产物.py agents/工作/<任务目录>
python3 agents/公共/工具/团队/校验产物.py agents/账号/爆款库
```

- 检查字段和取值、依据（爆款库条目、项目文件）是否存在、创意评审选中的方案是否打过分、审片报告对应的成片在审片后有没有被改过、样本不足的经验有没有被标成已验证。
- 只看带 `artifact` 字段的 JSON；直接指定的文件都会校验。

## 测试

```bash
python3 -m unittest agents/公共/工具/团队/tests/test_team.py
```
