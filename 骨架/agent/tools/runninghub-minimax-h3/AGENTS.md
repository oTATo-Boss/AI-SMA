# RunningHub MiniMax H3 · 本项目规则

执行一律用 RH-minimax-H3 技能（入口见 `../../SKILLS_INDEX.md`），本文件只写本项目的授权、默认值和输出位置。接口、任务构造和恢复细节以技能及其 references 为准。本账号不用 RunningHub 时可以删掉本目录，并清空 `账号配置.yaml` 的 generation。

## 授权

（待填写：本人对本账号使用 RunningHub 的授权原话、范围和日期。）

没有写明持续授权之前：每批付费提交前先把任务数、规格和预计用途告诉本人，得到明确同意再提交。其他项目的授权不适用于本项目。

## 本项目约定

- 凭据：优先用技能自己的本机私有配置（`credentials.py status` 查看）；需要项目单独配置时，设置 `RUNNINGHUB_ENV_FILE` 指向本项目 `agent/.env`（权限 0600）。不读出、不打印 Key。
- 默认值见 `../../规范/账号配置.yaml` 的 generation；画质换算成像素档位填写，做不到的档位如实说明。
- 先 `--dry-run` 再提交；jobs、上传映射、回执和视频都放当前任务目录（例如 `工作/<任务>/产物/素材/`），不写进 tools/、交付/ 或受保护目录。
- 每次提交后立刻把 taskId、状态和回包位置登记到 task.json 的 external_jobs。结果不明先用 `--resume <taskId>` 查询；没有 taskId 的 SUBMIT_UNKNOWN 先去 RunningHub 任务和消费记录核对，不删回执、不盲目重提。
- 返回 SUCCESS 还不算成功：要有通过检查的视频文件。下载后报告视频路径、真实尺寸和时长、taskId 和 usage；usage 缺失就说明，不估算费用。

```bash
SKILL_DIR="<RH-minimax-H3 技能的安装目录>"   # 例如 ~/.claude/skills/rh-minimax-h3
python3 "$SKILL_DIR/scripts/credentials.py" status
python3 "$SKILL_DIR/scripts/rh_minimax_h3.py" "$PWD/agent/工作/<任务>/jobs.json" --output "$PWD/agent/工作/<任务>/产物/素材" --dry-run
```
