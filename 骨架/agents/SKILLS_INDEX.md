# 项目技能索引

只登记本项目会用的技能：先按任务找技能，再完整读该技能的 SKILL.md。使用规则见 `agents/公共/规则.md` 第 6 节。每个智能体用哪些技能写在它的 `agent.yaml`。制作路线只用 `agents/账号/账号配置.yaml` 里 production_routes 启用的，下表括号里标了路线。

技能装在本机，不随项目复制：Codex 读 `~/.agents/skills` 和项目里的 `.agents/skills`，Claude Code 读 `~/.claude/skills` 和项目里的 `.claude/skills`。缺哪个就按"来源"安装；运行 `python3 agents/公共/工具/环境检查/检查环境.py` 会逐个检查。

## 按任务选技能

| 任务阶段 | 技能（按使用顺序） |
|---|---|
| 做内容（团队） | 由各智能体分工使用，每个智能体用的技能写在 `agents/role/<名字>/agent.yaml` |
| 社交内容启动、接续、跨阶段 | social-media-router |
| 爆款、对标、评论研究 | 数据一律用 Chrome 只读采集；方法借鉴 outlier-post-finder、comment-mining、creator-profile-teardown、trend-discovery、competitor-social-research；拿到视频文件时按 viral-outliers 逐帧加转写拆解，配置了 Gemini Key 时可用 video-content-analyzer；英文短视频参考 short-form-content-os |
| 选题、参考研究、脚本／分镜、图文每页方案 | 出创意用 creative-director；content-planning；视频加 direct-video；比较开场用 storytelling-hooks |
| 角色与场景素材、生成提示词、AI 原片（AI 生成路线） | asset-generation → ai-video-prompt → RH-minimax-H3；补图 Codex 用 imagegen，Claude 用 codex-imagegen |
| 艺术风格动画、动画复刻、解说动画 | huashu-art-motion（做视频和动效先评估它）+ direct-video |
| 界面演示、产品展示（代码动画路线） | video-shotcraft（Remotion）；也可以用 product-launch-video、bs-hyperframes-device-canvas-launch、bs-hyperframes-velocity-sting |
| 其他代码动画（代码动画路线） | Remotion 走 remotion-best-practices；HTML／GSAP 走 hyperframes |
| 讲解、方法、实录 | faceless-explainer；标题开场可用 bs-creatormotion-type-title-takeover |
| 剪辑、声音、气泡、成片检查、封面 | content-production + direct-video；配乐音效 media-use；抽帧 video-frames；台词气泡用项目工具（如有） |
| 标题、正文、标签、内容包 | publishing-delivery；打包用项目工具 发布包 |
| 后台数据、表现复盘 | performance-analysis |
| 技能安装、分类、索引维护 | skill-library-management |

social-media 的六个技能进入对应阶段时必须实际使用；窄任务只进入需要的阶段。共用工具在 `agents/公共/工具/README.md`，各智能体自带的工具在它的 `工具/`。

## 技能清单

需要：必需＝做内容离不开；推荐＝对应流程要用；可选＝特定场景才用。GitHub 来源一般可以用 `npx skills add <owner>/<repo>` 安装，也可以把对应目录复制到技能目录；skillry.dev 的技能按页面上的安装说明装。许可写"未声明"的，使用前自己确认。

### social-media · 社交内容

| 名称 | 作用 | 需要 | 来源 | 许可 |
|---|---|---|---|---|
| social-media-router | 判断目标和阶段，串联下面五个技能，交接规格、文件和检查结果 | 必需 | [my-skills](https://github.com/oTATo-Boss/my-skills) `skills/social-media/social-media-router` | MIT |
| content-planning | 参考研究、创意选择、脚本分镜和素材需求简报 | 必需 | [my-skills](https://github.com/oTATo-Boss/my-skills) `skills/social-media/content-planning` | MIT |
| asset-generation | 整理身份与参考素材、补图、写生成提示词、验收源素材 | 必需 | [my-skills](https://github.com/oTATo-Boss/my-skills) `skills/social-media/asset-generation` | MIT |
| content-production | 剪辑、声音、文字气泡、成片检查和封面 | 必需 | [my-skills](https://github.com/oTATo-Boss/my-skills) `skills/social-media/content-production` | MIT |
| publishing-delivery | 标题、正文、标签和逐篇待发布文件夹 | 必需 | [my-skills](https://github.com/oTATo-Boss/my-skills) `skills/social-media/publishing-delivery` | MIT |
| performance-analysis | 后台数据口径、可比分析和下一次测试 | 必需 | [my-skills](https://github.com/oTATo-Boss/my-skills) `skills/social-media/performance-analysis` | MIT |

### video · 视频与动效

| 名称 | 作用 | 需要 | 来源 | 许可 |
|---|---|---|---|---|
| ai-video-prompt | 创作、审查、按结果修改 AI 视频提示词 | 推荐 | [my-skills](https://github.com/oTATo-Boss/my-skills) `skills/video/ai/ai-video-prompt` | MIT |
| RH-minimax-H3 | RunningHub H3 生成、API 存入、任务构造、查询恢复和下载；项目授权见 `agents/role/素材制作/工具/runninghub-minimax-h3/README.md` | 推荐 | [my-skills](https://github.com/oTATo-Boss/my-skills) `skills/video/ai/rh-minimax-h3` | MIT |
| direct-video | 统筹审美、分镜、节奏、声音和成片验收 | 推荐 | [my-skills](https://github.com/oTATo-Boss/my-skills) `skills/video/creative/direct-video` | MIT |
| huashu-art-motion | 艺术风格配方、解说动画语法、代码渲染与成片验收 | 推荐 | [alchaincyf/huashu-art-motion](https://github.com/alchaincyf/huashu-art-motion)；`npx skills add alchaincyf/huashu-art-motion` | MIT |
| hyperframes | HTML、CSS、GSAP 做视频的入口，按需求转到子技能 | 推荐 | [heygen-com/hyperframes](https://github.com/heygen-com/hyperframes) `skills/hyperframes`；`npx skills add heygen-com/hyperframes --all` | 未声明 |
| remotion-best-practices | Remotion 入口，转到创建、字幕、预览、渲染等子技能 | 推荐 | [remotion-dev/skills](https://github.com/remotion-dev/skills) `skills/remotion-best-practices` | 未声明 |
| video-frames | 用 ffmpeg 提取静帧、缩略图和短片段，用于选素材和抽帧检查 | 推荐 | OpenClaw 内置技能模板，安装方式待核实；没有时直接用 ffmpeg 抽帧 | 未声明 |
| faceless-explainer | 不出镜的讲解视频：把文章、笔记或话题变成逐场景的文字、图形、图表画面 | 可选 | [heygen-com/hyperframes](https://github.com/heygen-com/hyperframes) `skills/faceless-explainer`；`npx skills add heygen-com/hyperframes --all` 会一起装 | 未声明 |
| product-launch-video | 从网址、文案或简报出产品发布片和演示（基于 HyperFrames） | 可选 | [heygen-com/hyperframes](https://github.com/heygen-com/hyperframes) `skills/product-launch-video`；`npx skills add heygen-com/hyperframes --all` 会一起装 | 未声明 |
| video-shotcraft | 真实页面截图、2.5D 运镜、卡点剪辑和音效（基于 Remotion） | 可选 | [Vincentwei1021/video-shotcraft](https://github.com/Vincentwei1021/video-shotcraft)（整个仓库就是技能） | Apache-2.0 |
| bs-creatormotion-type-title-takeover | 巨大标题在主体背后入场、主体切走后标题留下的开场 | 可选 | [skillry.dev](https://skillry.dev/skills/bs-creatormotion-type-title-takeover) | 未声明 |
| bs-hyperframes-device-canvas-launch | 真实界面放进暗色摄影棚设备画面，串联滚动、操作和品牌收尾 | 可选 | [skillry.dev](https://skillry.dev/skills/bs-hyperframes-device-canvas-launch) | 未声明 |
| bs-hyperframes-velocity-sting | 速度和方向匹配的连续剪切，做几秒的预热和片头 | 可选 | [skillry.dev](https://skillry.dev/skills/bs-hyperframes-velocity-sting)（上游待核实） | 未声明 |
| storytelling-hooks | 比较第一帧、字幕和可兑现的观看回报，不强制口播 | 可选 | [yaxeen/storytelling-skills](https://github.com/yaxeen/storytelling-skills) `skills/storytelling-hooks` | 未声明 |

### 研究与创意 · 外部收集

ScrapeCreators 套件的技能默认调用它家的付费 API，head-of-content 套件要 TubeLab、Apify、Gemini 的 Key；本项目的市场数据用 Chrome 获取，没有 Key 时只借用方法。两个套件里没列出的技能（ad-library-teardown、audience-research、content-repurposing、influencer-prospecting、product-demand-research、scrapecreators-api、social-listening-brief、content-planner、instagram-research、tiktok-research、x-research、youtube-research）用到时再按来源查看。

| 名称 | 作用 | 需要 | 来源 | 许可 |
|---|---|---|---|---|
| creative-director | 用 SIT、TRIZ、横向思维等方法系统地出创意，对照经典案例打分、改稿和失败预演 | 推荐 | [smixs/creative-director-skill](https://github.com/smixs/creative-director-skill) `creative-director` | CC BY 4.0（引用须署名 Serge Shima） |
| outlier-post-finder | 找出明显高于作者常态的作品，解释为什么有效，提炼钩子和形式 | 可选 | [ScrapeCreators/social-media-research-skills](https://github.com/ScrapeCreators/social-media-research-skills) `skills/outlier-post-finder` | MIT |
| comment-mining | 挖评论里的观众反应、用语、问题和需求 | 可选 | [ScrapeCreators/social-media-research-skills](https://github.com/ScrapeCreators/social-media-research-skills) `skills/comment-mining` | MIT |
| creator-profile-teardown | 拆解一个创作者或品牌账号的定位、内容支柱和爆款打法 | 可选 | [ScrapeCreators/social-media-research-skills](https://github.com/ScrapeCreators/social-media-research-skills) `skills/creator-profile-teardown` | MIT |
| trend-discovery | 发现赛道里的热门话题、标签、音乐、作品和形式 | 可选 | [ScrapeCreators/social-media-research-skills](https://github.com/ScrapeCreators/social-media-research-skills) `skills/trend-discovery` | MIT |
| competitor-social-research | 研究竞品的社媒策略，找出赛道里有效的内容和空白 | 可选 | [ScrapeCreators/social-media-research-skills](https://github.com/ScrapeCreators/social-media-research-skills) `skills/competitor-social-research` | MIT |
| transcript-intelligence | 从视频转写里提炼钩子、观点和可复用的脚本结构 | 可选 | [ScrapeCreators/social-media-research-skills](https://github.com/ScrapeCreators/social-media-research-skills) `skills/transcript-intelligence` | MIT |
| viral-outliers | 找细分赛道的爆款 Reels，下载后逐帧看、转写，再改成本账号可用的脚本模板（需要 opencli、ffmpeg、faster-whisper） | 可选 | [w-avw/instagram-viral-reels-research-claude-skill](https://github.com/w-avw/instagram-viral-reels-research-claude-skill) `skills/viral-outliers` | MIT |
| video-content-analyzer | 用 Gemini 实际看视频，提取钩子、结构和可复制的模式（需要 GEMINI_API_KEY） | 可选 | [bradautomates/head-of-content](https://github.com/bradautomates/head-of-content) `.claude/skills/video-content-analyzer` | MIT |
| short-form-content-os | 北美英文短视频从趋势、异常爆款、钩子到脚本、分镜和迭代的工作流 | 可选 | [trsgogogo/short-form-content-os](https://github.com/trsgogogo/short-form-content-os)（整个仓库就是技能） | MIT |

### 声音、图片与技能管理

| 名称 | 作用 | 需要 | 来源 | 许可 |
|---|---|---|---|---|
| media-use | 配乐、音效、图片、图标、配音、调色的统一入口，也能转录、字幕、抠像；记录来源，试听另报 | 推荐 | [heygen-com/hyperframes](https://github.com/heygen-com/hyperframes) `skills/media-use`；`npx skills add heygen-com/hyperframes --all` 会一起装 | 未声明 |
| codex-imagegen | Claude 通过本机 Codex CLI 调用 image_gen，可带参考图；用法注意见 `agents/公共/工具/README.md` | 可选 | [my-skills](https://github.com/oTATo-Boss/my-skills) `skills/image/codex-imagegen` | MIT |
| skill-library-management | 技能分类、目录索引、开发安装映射和客户端入口管理 | 可选 | [my-skills](https://github.com/oTATo-Boss/my-skills) `skills/Rules/skill-library-management` | MIT |

## Codex 内置与插件

Codex 用户：imagegen 是 Codex 内置技能；Remotion、HyperFrames、HeyGen 在 Codex 的插件管理里启用，版本和连接以当前会话为准。Claude 用户用上面的技能和 heygen 命令行。
