# tools

所有 agent 共用的项目工具和外部工具用法。每个工具一个子文件夹，`AGENTS.md` 是该工具唯一的规则源，`CLAUDE.md` 只引用它；用工具前先读它。工具输出只写在 `agent` 当前任务目录；外部任务 ID、状态和回包位置及时登记到任务 `task.json` 的 `external_jobs`。

| 工具 | 文件夹 | 用途 |
|---|---|---|
| 任务管理 | [任务管理](任务管理/README.md) | 任务状态、授权、确认、检查、交付验收和总览生成 |
| 项目检查 | [项目检查](项目检查/AGENTS.md) | 一键检查规则链接、任务记录、受保护目录、密钥、阅读量和配置一致性 |
| 环境检查 | [环境检查](环境检查/AGENTS.md) | 检查本机工具、登录状态和项目技能是否齐全，缺了给出补法（只读，不安装） |
| 写入保护 | [写入保护](写入保护/AGENTS.md) | Claude Code 的写入拦截：不写 发布内容/、固定资产/，不改已有交付 |
| 发布包 | [发布包](发布包/AGENTS.md) | 把成片、封面、文案整理成三文件交付包并做技术检查 |
| RunningHub MiniMax H3 | [runninghub-minimax-h3](runninghub-minimax-h3/AGENTS.md) | 本项目的 H3 授权、默认值和输出位置；执行用 RH-minimax-H3 技能 |

新增工具照同样结构建子文件夹，并在这张表里加一行。

## HeyGen CLI

HyperFrames、faceless-explainer、media-use 等的配乐、音效和素材搜索按需用 HeyGen CLI；Codex 也可以用已连接的 HeyGen 插件。涉及配音或对口型时先核对任务的声音要求（`../规范/内容与交付.md` 第 2 节）和授权。

- 安装：官方命令 `curl -fsSL https://static.heygen.ai/cli/install.sh | bash`，装在 `~/.local/bin/heygen`。是否安装或更新按当前任务授权决定，不因读到文档就执行。
- 登录：OAuth（`heygen auth login --oauth`），由本人在浏览器完成，agent 不输入账号密码。用免费额度，不用按量扣费的 API Key 模式；免费额度用完或需要付费时先问本人。
- 现状以 `heygen auth status` 的实际输出为准；每次使用都检查当前登录、额度和实际能力。
- 凭据在 `~/.heygen/credentials`，不打开、不复制、不输出；看状态用 `heygen auth status`。排查 HyperFrames／media-use 整条链路用 `npx hyperframes media-use resolve --doctor`，链路诊断通过不等于素材或成片合格。
- 不用本地 Kokoro 配音。faceless-explainer 等流程在 HeyGen 失败时可能自动退到 Kokoro（默认英文男声 am_michael）：生成前先查认证，生成后核实声音确实来自 HeyGen；HeyGen 用不了就停下告诉本人，不自动换声音服务。
- 配乐在 HeyGen 不可用时，可以先用已授权的自备音乐或本地合成，并说明来源和替代。来源与许可、实际试听、媒体流映射分别记录。
- 抠像可以在本地用 u2net；本项目已接入的对口型流程走 HeyGen，能力不可用时不用抠像或伪造文件代替。

## 图片生成

- Codex 直接用 imagegen；Claude 通过 codex-imagegen 调用本机已登录的 Codex CLI，用 `--ref` 绑定真实参考图。
- codex-imagegen 的 `--workdir` 用独立的临时目录，`--out` 指向 `agent` 当前任务目录；不要把素材或交付目录当执行根目录，否则子调用会把它当成项目根，往里写 AGENTS.md 和 SKILLS_INDEX.md。
- 先看输入图，生成后实际查看再用；文件保存成功不等于参考一致或视觉验收通过。

## 视频检测与文字叠加

- video-frames 用 FFmpeg 提取静帧、缩略图和短片段；文件检查、抽帧、连续播放、试听分开报告。
- Homebrew 等常见版本的 FFmpeg 可能没编进 drawtext、subtitles、ass 滤镜，先用 `ffmpeg -filters` 确认。没有时用 PIL 生成透明 PNG 再 overlay，或在 HyperFrames、Remotion 里做。

## Remotion 渲染

如果随工程携带的 Headless Shell 出现 Waiting for root component 超时，在工程目录运行 compositions、still 或 render 时改用本机 Chrome：`--browser-executable="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"`（macOS 路径）。这是本地隔离渲染进程，不用账号资料。不要因为检查失败就升级依赖或改作品内容。代表帧只验证入口和资源加载，不替代整片审看和试听。
