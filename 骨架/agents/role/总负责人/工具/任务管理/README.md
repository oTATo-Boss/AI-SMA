# 任务管理工具

总负责人的工具，素材制作也用它登记外部任务。入口 `任务管理.py`，Python 3.9+；macOS/Linux 使用 fcntl 锁，Windows 使用 msvcrt 锁，缺时区数据时由部署智能体用当前 Python 安装 tzdata。在项目根目录运行，参数路径都相对项目根目录，记录路径使用 `/`；`--revision` 用刚读到的任务版本。工具只写 agents/ 内的任务记录和任务总览，不复制交付、不发布、不调用生成服务、不创建常驻调度。目录、时区和交付包文件名读 `流程定义.json` 的 project、packages。

## 常用命令

```bash
python3 agents/role/总负责人/工具/任务管理/任务管理.py new --title '研究问题' --workflow research --goal '明确要回答的问题' --done-when '结论有来源，限制已说明'
python3 agents/role/总负责人/工具/任务管理/任务管理.py show 'agents/工作/任务目录'
python3 agents/role/总负责人/工具/任务管理/任务管理.py authorize 'agents/工作/任务目录' --revision 1 --scope '本人安排的研究范围' --source '本人在当前对话的原话'
python3 agents/role/总负责人/工具/任务管理/任务管理.py update 'agents/工作/任务目录' --revision 2 --phase 取证 --status 进行中 --next '读取已授权的证据'
python3 agents/role/总负责人/工具/任务管理/任务管理.py validate-all
python3 agents/role/总负责人/工具/任务管理/任务管理.py sync
```

- `new` 建记录、生成任务 ID、按流程加上必经确认并更新总览；新建不等于授权执行，用 `authorize` 登记本人的任务要求。
- `update` 可追加 `--input`、`--output`、`--issue`，修改阶段、状态、下一步或处理者。优先用命令改字段；直接编辑 JSON 时必须重读版本、增加 revision、更新时间，再 validate 和 sync。
- 用到的知识文件路径用 `update --input` 登记；`--next` 写当前步骤、有效文件和下一动作。`phase` 用流程定义里的阶段名，不写 G01 这类步骤编号。各任务类型的阶段和检查见 `agents/role/总负责人/知识/任务与异常.md` 第 3 节。

## 确认、检查、交付、验收

```bash
python3 agents/role/总负责人/工具/任务管理/任务管理.py gate 'agents/工作/任务目录' --revision 3 --key positioning --title '定位方案确认' --before-phase 沉淀 --decision approved --subject 'agents/工作/任务目录/定位与对标方案.md' --source '本人看过这份方案后的原话'
python3 agents/role/总负责人/工具/任务管理/任务管理.py check 'agents/工作/任务目录' --revision 4 --name '成片审查' --result passed --evidence 'agents/工作/任务目录/检查/审片报告.json' --summary '检查对象、方法、通过项和未验证范围'
python3 agents/role/总负责人/工具/任务管理/任务管理.py job 'agents/工作/任务目录' --tool RunningHub --task-id '<taskId>' --status submitted --record 'agents/工作/任务目录/工程/回执.json'
python3 agents/role/总负责人/工具/任务管理/任务管理.py check-package 'agents/工作/任务目录/交付暂存/完整包' --kind social-video --new-name '实际整理时间_内容名称'
python3 agents/role/总负责人/工具/任务管理/任务管理.py delivery 'agents/工作/任务目录' --revision 5 --path '交付/实际整理时间_内容名称' --kind social-video --source '实际复制完成并检查的记录位置'
python3 agents/role/总负责人/工具/任务管理/任务管理.py accept 'agents/工作/任务目录' --revision 6 --decision approved --source '本人对当前交付版本的原话或出处'
```

- **确认**：来源只登记本人真实的授权，不用智能体的判断或工具结果充当；工具记录方案文件哈希，文件变了确认就失效。核心方案变更时把对应确认登记为 `pending` 并写原因，工具会退回确认前的阶段等待本人。定位（positioning）、转型（direction）这类确认用 `--title`、`--before-phase` 加上；不能改流程本身的必经确认。
- **检查**：`passed` 必须有文件证据；没检查填 `unverified`，失败填 `failed`。同名检查更新后，旧结果留在运行记录。content 任务的"创意评审""成片审查"没通过，进不了"方案""交付"。
- **外部任务**：`job` 不用 `--revision`，带锁追加或更新 external_jobs（同一工具和任务 ID 再登记就更新状态），几个素材制作同时登记也不会冲突；回包位置要真实存在。
- **包类型**：`social-video` 是三文件视频包（文件名见流程定义 packages）；`prompt` 是 txt 和参考图；`other` 用于本人确认过的其他形式，只检查非空独立文件，不能拿来绕过具体交付规范。
- 新模板的 packages 还可写 `{"required": ["母版.mp4", "工程"], "optional": ["字幕.srt"], "allow_extra": false}`；required/optional 是顶层文件或目录，目录里的实际文件逐个做路径检查和哈希。旧列表格式仍要求精确文件清单。
- **check-package** 只检查文件清单、非空、文件头、文本编码和哈希，不解码视频，不看分辨率、审美、版权或提示词内容；名称不冲突只代表检查时没冲突，新增前要再确认。
- **delivery** 只登记已经新增到 `交付/` 的完整包；最新一条是当前版本，旧条目不能重写。登记新交付会恢复待验收，不继承旧版验收。
- **accept** 只记录本人对当前版本的真实验收并绑定文件哈希，不自动结束任务。

## 任务记录字段

每个任务只有一份 `task.json`，模板在 `模板/任务.json`。

新项目配置是 `agents/项目/项目配置.yaml` 的 JSON 文本且 schema_version=2；工具自动创建 v2 任务。只有旧账号配置时继续创建 v1 任务，读取和更新已有 v1 记录不会静默升级。流程的 phases 可为旧字符串列表，或 `{id, name, owners, requires}` 对象列表；任务记录保存 name，CLI 同时接受 id。阶段 owners/requires 为总负责人拆任务的编排依据，工具通过 required_checks/gates 执行检查门槛，不运行后台阶段调度。

| 字段 | 内容 |
|---|---|
| `goal`、`done_when` | 目标和可检查的完成条件 |
| `phase`、`status`、`next_action` | 当前阶段、执行状态、下一步（完成或取消时可以为空） |
| `inputs`、`outputs` | 相对项目根目录的依据和成果路径 |
| `approvals`、`gates` | 任务授权来源；流程确认及对应文件版本 |
| `checks`、`deliveries`、`acceptance` | 检查结果和证据；交付版本和文件哈希；本人验收和对应版本 |
| `external_jobs` | 工具、任务 ID、状态、回包位置和已知消耗，不写凭据 |
| `issues`、`migration` | 限制和未解决事项；旧任务状态的出处和未确认信息 |
| `revision`、时间、`owner` | 记录版本、北京时间、当前处理者（协调标记，不扩大授权） |
| v2 `parent_id`、`depends_on` | 上级任务 ID 和直接前置任务 ID；不能引用缺失任务、自己或形成循环；目录仍是单层，不移动旧任务 |
| v2 `unit` | null 或 `{type, id}`；type 为 project/episode/chapter/sequence/scene/shot/work-package |
| v2 `input_versions` | 每个实际输入的 path/sha256；来自前置任务时附 task_id；JSON 产物可附 artifact_version |
| v2 `review_mode` | independent 或 self；项目 execution_mode 为 single/serial 时默认 self，原生分工默认 independent |

### v2 长项目与恢复

```bash
python3 agents/role/总负责人/工具/任务管理/任务管理.py new --title '第一场分镜' --workflow content --goal '将剧本第一场转为分镜' --done-when '镜头可执行且连续性通过' --parent-id '<项目任务ID>' --depends-on '<剧本任务ID>' --unit-type scene --unit-id S01
python3 agents/role/总负责人/工具/任务管理/任务管理.py update 'agents/工作/<任务目录>' --revision 1 --input 'agents/工作/<任务目录>/剧本.md'
python3 agents/role/总负责人/工具/任务管理/任务管理.py refresh-inputs 'agents/工作/<任务目录>' --revision 2 --source '已检查剧本新版的变更范围，安排重审相关镜头'
```

新建依赖任务会绑定前置任务当前 outputs 的文件版本，update --input 会绑定具体文件；没有任何绑定产物的前置任务不能开始执行。上游文件、版本或输出清单变化时 validate 和状态推进失败，不自动重做付费工作。`refresh-inputs` 是显式重新接收输入：更新哈希、撤销旧检查和验收、重新打开确认、退回首阶段；历史交付和运行记录保留。它不代表受影响内容已重做或已审过。

passed 检查的 review_mode 要与 v2 评审报告一致；requires_independent=true 的门槛必须有真正独立的结构化评审报告。检查工具同时验证报告绑定的素材，不能只绑定一份写着“通过”的文本。

### 外部服务提交意图

```bash
python3 agents/role/总负责人/工具/任务管理/任务管理.py job-intent 'agents/工作/<任务目录>' --tool '生成服务' --submission-key S01-v1 --request 'agents/工作/<任务目录>/工程/请求.json'
python3 agents/role/总负责人/工具/任务管理/任务管理.py job 'agents/工作/<任务目录>' --tool '生成服务' --submission-key S01-v1 --status unknown --record 'agents/工作/<任务目录>/工程/请求.json'
python3 agents/role/总负责人/工具/任务管理/任务管理.py job-recover 'agents/工作/<任务目录>' --submission-key S01-v1
python3 agents/role/总负责人/工具/任务管理/任务管理.py job 'agents/工作/<任务目录>' --tool '生成服务' --submission-key S01-v1 --task-id '<服务返回ID>' --status submitted --record 'agents/工作/<任务目录>/工程/回执.json'
```

调用服务之前先保存去除凭据的请求并登记意图；提交键只能登记一次。支持 intent/unknown/submitted/running/succeeded/failed/cancelled。回包不明先登记 unknown，再查询服务或核对实际回执；job-recover 只读状态，不调用服务、不批准重复提交。同一意图不能改绑另一个服务任务 ID。服务不支持查询或幂等键时，记录真实限制，不能仅因本地未存 ID 就重提。旧 job --task-id 命令继续可用。

结束条件：处于流程末阶段，关联有效成果，至少一项有证据的检查通过且没有未解决的失败；内容和交付任务还要有当前交付和本人验收。done_when 的每一项都要在检查说明里对应，一次机器检查不能替代全部完成条件。发布不是结束条件。

## 错误与恢复

- 版本冲突就重读，不强制覆盖。路径越界、软链接、写入硬链接、引用凭据、交付版本变化、确认文件变动、缺证据都会被拒绝。
- 写入用单任务编辑锁和原子替换；运行记录是历史，task.json 是当前状态。进程在保存任务后、写历史或更新总览前中断时，以 task.json 为准，重新 validate 和 sync，不重做已保存的业务动作。
- 这些保护只覆盖管理工具自己的操作；工程制作、其他命令和直接编辑仍遵守项目权限。没有后台常驻执行器，智能体在对话中按记录推进。
- 测试：`OTATO_TEST_ARTIFACT_DIR=<隔离目录> python3 -m unittest agents/role/总负责人/工具/任务管理/tests/test_task_management.py`（只写隔离夹具，可指定当前维护任务的检查目录）。
