# 账号运营项目模板 v0

给 AI agent（Claude Code、Codex）用的社交媒体账号运营项目骨架。新建一个账号就生成一个独立项目，里面有：

- 入口：6 条红线和"什么任务读什么"的路由，agent 启动时自动加载；
- 长期规范：账号配置、定位与策略、内容与交付等，按账号填写；
- 五类 SOP：账号定位与对标、生成类视频、代码类视频、发布材料交付、数据分析与反馈；
- 工具：任务管理（状态、确认、交付版本）、项目检查、环境检查、写入保护、发布包。

适合一个人运营小红书、抖音等短视频账号，内容主要靠 AI 生成和代码视频完成：agent 负责策划、制作、检查和整理交付，本人负责确认、验收和发布。

## 需要什么

- macOS 或 Linux（任务管理工具用到 fcntl，Windows 不支持）
- Python 3.9+、ffmpeg／ffprobe、Node 18+、git、Google Chrome
- Claude Code 或 Codex。写入保护钩子只对 Claude Code 生效，Codex 按入口红线执行
- 技能：见 `骨架/agent/SKILLS_INDEX.md` 的"来源"列，至少装齐"必需"的 social-media 六个技能
- 可选：HeyGen CLI（配乐、音效）、ChatGPT 桌面 App（Claude 通过 Codex 生图）、RunningHub 账号（AI 视频生成，付费）

不用事先逐项核对：新建账号时会自动跑环境检查，缺什么都会列出来并给出补法。

## 新建账号

```bash
python3 新建账号.py --name 账号名 --dest 项目目录 --browser-profile Chrome资料名
```

- 不写 `--dest` 时，建在当前目录下的 `@账号名`；目录已存在就停止，不合并、不覆盖。
- 脚本会复制 `骨架/`、填入账号名和浏览器资料、写第一条日志、生成任务总览，再运行项目检查和环境检查，最后列出所有"待填写"的位置。
- 用 Claude Code 打开新项目时，会询问是否信任项目里的设置（`.claude/settings.json` 里的写入保护钩子），选信任才会生效。

## 工具和技能怎么装

工具、技能和登录都装在本机，所有账号项目共用，不复制进项目。

1. 基础工具：macOS 先装 Homebrew，再 `brew install python ffmpeg node git`；安装 Google Chrome。
2. 技能：按 `骨架/agent/SKILLS_INDEX.md` 的"来源"安装。Claude Code 读 `~/.claude/skills` 和项目里的 `.claude/skills`，Codex 读 `~/.codex/skills`。
3. 用到才需要：ChatGPT 桌面 App（自带 codex-cli，Claude 生图用）；HeyGen CLI（官方脚本安装后本人运行 `heygen auth login --oauth`）；RunningHub Key（本人用 RH-minimax-H3 的 `credentials.py set` 隐藏输入）；`python3 -m pip install requests`。
4. 每个账号单独做一件事：在 Chrome 里给它建一个个人资料，登录这个账号的平台后台。agent 做只读研究时只用这个资料。

装完在项目里运行 `python3 agent/tools/环境检查/检查环境.py`，直到"结果：通过"。

## 新账号先填什么

1. `agent/规范/账号配置.yaml`：目标、受众、身份、平台、声音、封面设计逻辑；标"默认"的值按需改。
2. `agent/规范/账号信息.md`：本人、品牌、产品和账号事实。
3. `agent/规范/定位与策略.md`：按 `agent/sop/账号定位与对标分析.md` 做一轮研究，本人确认后写入。
4. `agent/规范/内容与交付.md` 第 1–3 节：品牌、声音、制作路线；第 5 节"可以正常出现"一项。
5. `agent/附录/`：账号与主页、可用素材；品牌资产放进 `固定资产/`。
6. `agent/SKILLS_INDEX.md`：删掉不用的技能，补上本账号要用的。
7. 要用 RunningHub 时，在 `agent/tools/runninghub-minimax-h3/AGENTS.md` 写明本人的授权；没写就每次付费提交前先问。

填完后运行 `python3 agent/tools/项目检查/检查.py`，确认没有失效链接和配置不一致。

## 项目结构

```text
@账号名/
├── AGENTS.md、CLAUDE.md    入口：红线、启动、任务路由（agent 自动加载）
├── .claude/settings.json   Claude Code 写入保护钩子
├── agent/                  agent 的工作区：规范、SOP、工具、任务、日志、附录、账号数据
├── 交付/                   完整交付，只能新增全新目录
├── 发布内容/               本人采用并归档的内容，agent 只读
└── 固定资产/               品牌和角色等原始资产，agent 只读
```

| 类别 | 文件 | 怎么处理 |
|---|---|---|
| 通用 | 入口的结构和红线、`agent/规范/项目规则.md`、`agent/sop/`、`agent/tools/`、`.claude/settings.json`、`.ignore` | 原样使用 |
| 账号填写 | 账号配置、账号信息、定位与策略、内容与交付第 1–3 节、偏好与经验、外部知识、选题池、附录、技能索引、付费服务授权 | 按上面的顺序填 |
| 运行中产生 | `agent/工作/`、`agent/log/`、`agent/账号数据/`、`交付/`、`发布内容/`、`固定资产/`、`agent/历史资料/` | 空目录开始 |

## 维护模板

维护模板时先读 `AGENTS.md`。通用文件的改进先在真实账号项目里验证，再同步到 `骨架/`，并在下面"版本"里记一行。

## 待决

- 技能来源：23 个技能里 21 个来源已确认；video-frames、bs-hyperframes-velocity-sting 只有部分信息。许可写"未声明"的技能，别人使用前要自己确认。
- 跨账号共用的信息（本人资产、代码仓库、平台规则类外部知识）现在每个账号各存一份，可以考虑以后挪到一个共享位置。
- 本地审阅台（看板、媒体审阅、确认和批注按钮）：以后再说。
- 验收指标：启动必读不超过 8 千字符；单个任务动手前要读的项目文档约 2 万字符以内；新建后检查通过，30 分钟内能开工。

## 许可

MIT，见 `LICENSE`。模板引用的技能各有自己的许可，以各自仓库为准；模板用到的作者自己的 11 个技能（在 my-skills 里）都是 MIT。

## 版本

- v0（2026-10-14）：首个版本。按"发给别人用"整理：去掉本机路径，技能改为按名字查找并写明来源，新建账号后自动检查环境。
- v0.1（2026-10-14）：技能索引按各技能的来源记录更新来源，加许可列。
- v0.2（2026-10-14）：作者自己的技能全部以 MIT 发布，许可列同步更新。
- v0.3（2026-10-14）：去掉没用到的 systematic-debugging。
