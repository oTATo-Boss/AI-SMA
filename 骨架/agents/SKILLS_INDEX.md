# 项目技能索引

本索引用于项目技能选型与复用，实际需求以项目配置的 `skills.required` 和角色卡 `skills` 为准；启动只加载 `preload_skills`。来源、固定版本、完整包及依赖的唯一维护源是 [技能来源注册表](公共/技能来源.json)，安装遵循 [共享安装规则](公共/技能安装.md)。

技能真实安装到本机共享用途分类库；本模板不打包第三方技能、不提供自动安装脚本。`ready` 是来源包已固定，`candidate`/`blocked` 不得被报告成可用。技能文件齐全、客户端发现、运行工具和制作验证分别记录。

## 按任务选择

| 任务 | 优先入口 |
|---|---|
| 项目装配与团队交接 | video-project-orchestration |
| 创意、资料与剧本 | creative-director、content-planning、screenwriting；按片型补长视频或广告方法 |
| 导演、分镜和连续性 | direct-video、production-continuity |
| 图片与AI镜头 | asset-generation、ai-video-prompt、rh-minimax-h3、gpt-image-2-style-library |
| 二维、艺术与解释动画 | huashu-art-motion + Remotion / HyperFrames |
| 三维场景与动画 | Blender工作流与专长；Three.js路由与专长 |
| 剪辑、声音与成片 | video-production-pipeline、content-production、ffmpeg-skill；需要时加载配音与框架音频 |
| 包装、交付和运营 | publishing-delivery、titles-and-thumbnails、performance-analysis |

## 完整登记

来源包可能包含多个子技能和共享资源，依赖闭包按注册表计算。候选不自动成为项目必需项。

| 名称 | 一句话用途 | 状态 | 来源 |
|---|---|---|---|
| social-media-router | 社媒工作阶段识别与串联 | ready | [my-social](https://github.com/oTATo-Boss/my-skills/tree/a1c222490297dff1b7eb21f614df72fd3b3607fe/skills/social-media) |
| content-planning | 参考研究、创意与内容方案 | ready | [my-social](https://github.com/oTATo-Boss/my-skills/tree/a1c222490297dff1b7eb21f614df72fd3b3607fe/skills/social-media) |
| asset-generation | 身份参考、提示词与素材验收 | ready | [my-social](https://github.com/oTATo-Boss/my-skills/tree/a1c222490297dff1b7eb21f614df72fd3b3607fe/skills/social-media) |
| content-production | 剪辑、声音、文字与成片验收 | ready | [my-social](https://github.com/oTATo-Boss/my-skills/tree/a1c222490297dff1b7eb21f614df72fd3b3607fe/skills/social-media) |
| publishing-delivery | 标题文案与交付文件整理 | ready | [my-social](https://github.com/oTATo-Boss/my-skills/tree/a1c222490297dff1b7eb21f614df72fd3b3607fe/skills/social-media) |
| performance-analysis | 后台指标口径、对比与复盘 | ready | [my-social](https://github.com/oTATo-Boss/my-skills/tree/a1c222490297dff1b7eb21f614df72fd3b3607fe/skills/social-media) |
| direct-video | 导演方案、分镜、节奏与视听验收 | ready | [direct-video](https://github.com/oTATo-Boss/my-skills/tree/a1c222490297dff1b7eb21f614df72fd3b3607fe/skills/video/creative/direct-video) |
| ai-video-prompt | AI镜头提示词与按结果修订 | ready | [ai-video-prompt](https://github.com/oTATo-Boss/my-skills/tree/a1c222490297dff1b7eb21f614df72fd3b3607fe/skills/video/ai/ai-video-prompt) |
| rh-minimax-h3 | RunningHub生成、查询恢复与素材下载 | ready | [rh-minimax-h3](https://github.com/oTATo-Boss/my-skills/tree/a1c222490297dff1b7eb21f614df72fd3b3607fe/skills/video/ai/rh-minimax-h3) |
| skill-library-management | 完整技能包、来源、分类与入口维护 | ready | [skill-library-management](https://github.com/oTATo-Boss/my-skills/tree/a1c222490297dff1b7eb21f614df72fd3b3607fe/skills/Rules/skill-library-management) |
| creative-director | 创意方法、提案与评估 | ready | [creative-director](https://github.com/smixs/creative-director-skill/tree/ac06eb255371da35d1db0a146dbfcca8c8857543/creative-director) |
| storytelling-hooks | 开场信息与观看承诺 | ready | [storytelling](https://github.com/yaxeen/storytelling-skills/tree/24ef3c1e3d7fde66cc5f1c5953cd6c1d7afc0b4f/skills) |
| long-form-youtube | 长视频章节、叙事与脚本结构 | ready | [storytelling](https://github.com/yaxeen/storytelling-skills/tree/24ef3c1e3d7fde66cc5f1c5953cd6c1d7afc0b4f/skills) |
| titles-and-thumbnails | 标题与封面配合 | ready | [storytelling](https://github.com/yaxeen/storytelling-skills/tree/24ef3c1e3d7fde66cc5f1c5953cd6c1d7afc0b4f/skills) |
| channel-formula | 比较真实作品提炼栏目模式 | ready | [storytelling](https://github.com/yaxeen/storytelling-skills/tree/24ef3c1e3d7fde66cc5f1c5953cd6c1d7afc0b4f/skills) |
| retention-audit | 留存曲线与时间点诊断 | ready | [storytelling](https://github.com/yaxeen/storytelling-skills/tree/24ef3c1e3d7fde66cc5f1c5953cd6c1d7afc0b4f/skills) |
| carousel-narratives | 图文逐页叙事 | ready | [storytelling](https://github.com/yaxeen/storytelling-skills/tree/24ef3c1e3d7fde66cc5f1c5953cd6c1d7afc0b4f/skills) |
| huashu-art-motion | 艺术画风、解释动画与制作验收 | ready | [huashu-art-motion](https://github.com/alchaincyf/huashu-art-motion/tree/2571ee0a9a0467c4d99e935ea9e0fadda19210b0/.) |
| hyperframes | HTML视频的路线入口 | ready | [hyperframes](https://github.com/heygen-com/hyperframes/tree/ba08acb1f506b06757bd77a7e7f491d412647fbd/skills) |
| hyperframes-core | 组合、时序、轨道与确定性 | ready | [hyperframes](https://github.com/heygen-com/hyperframes/tree/ba08acb1f506b06757bd77a7e7f491d412647fbd/skills) |
| hyperframes-animation | 动画机制与场景转换 | ready | [hyperframes](https://github.com/heygen-com/hyperframes/tree/ba08acb1f506b06757bd77a7e7f491d412647fbd/skills) |
| hyperframes-cli | 预览、检查与渲染命令 | ready | [hyperframes](https://github.com/heygen-com/hyperframes/tree/ba08acb1f506b06757bd77a7e7f491d412647fbd/skills) |
| hyperframes-creative | 画面风格、字体、色彩与设计 | ready | [hyperframes](https://github.com/heygen-com/hyperframes/tree/ba08acb1f506b06757bd77a7e7f491d412647fbd/skills) |
| hyperframes-keyframes | 可寻址关键帧与运动 | ready | [hyperframes](https://github.com/heygen-com/hyperframes/tree/ba08acb1f506b06757bd77a7e7f491d412647fbd/skills) |
| hyperframes-registry | 官方组件与转场复用 | ready | [hyperframes](https://github.com/heygen-com/hyperframes/tree/ba08acb1f506b06757bd77a7e7f491d412647fbd/skills) |
| hyperframes-studio | 已有工程的预览编辑 | ready | [hyperframes](https://github.com/heygen-com/hyperframes/tree/ba08acb1f506b06757bd77a7e7f491d412647fbd/skills) |
| hyperframes-audio | 已有音轨混音、效果与自动化 | ready | [hyperframes](https://github.com/heygen-com/hyperframes/tree/ba08acb1f506b06757bd77a7e7f491d412647fbd/skills) |
| media-use | 配乐、音效、图像与素材处理 | ready | [hyperframes](https://github.com/heygen-com/hyperframes/tree/ba08acb1f506b06757bd77a7e7f491d412647fbd/skills) |
| music-to-video | 以音乐结构驱动影像 | ready | [hyperframes](https://github.com/heygen-com/hyperframes/tree/ba08acb1f506b06757bd77a7e7f491d412647fbd/skills) |
| product-launch-video | 产品发布片与演示 | ready | [hyperframes](https://github.com/heygen-com/hyperframes/tree/ba08acb1f506b06757bd77a7e7f491d412647fbd/skills) |
| embedded-captions | 已有口播素材的字幕 | ready | [hyperframes](https://github.com/heygen-com/hyperframes/tree/ba08acb1f506b06757bd77a7e7f491d412647fbd/skills) |
| faceless-explainer | 用画面解释文章与知识 | ready | [hyperframes](https://github.com/heygen-com/hyperframes/tree/ba08acb1f506b06757bd77a7e7f491d412647fbd/skills) |
| general-video | 自定义HTML视频组合 | ready | [hyperframes](https://github.com/heygen-com/hyperframes/tree/ba08acb1f506b06757bd77a7e7f491d412647fbd/skills) |
| remotion-best-practices | Remotion入口与完整子技能包 | ready | [remotion](https://github.com/remotion-dev/skills/tree/32b241b97f4e0e4ab61fe9a41b05e6e64503f8c5/skills/remotion-best-practices) |
| video-shotcraft | 产品片镜头、真实界面与节奏 | ready | [video-shotcraft](https://github.com/Vincentwei1021/video-shotcraft/tree/5ddbf521038b0a7accfb6dc1e0a9eb29c67277ab/.) |
| ffmpeg-skill | 剪辑、音频、转码与技术检查 | ready | [ffmpeg-skill](https://github.com/kajisho5/ffmpeg-skill/tree/1f7e7e3ad1c30cb39fe9032abb5b39cca8e63376/.) |
| voicestudio | 本地语音后端、配音与转录 | ready | [voicestudio](https://github.com/debpalash/VoiceStudio/tree/4df5033e5a1a92e22936fb4d7d2d39e03cf10a91/skills/voicestudio) |
| auto-editor-transcribe | 音视频转录及时间信息 | ready | [auto-editor-transcribe](https://github.com/WyattBlue/auto-editor/tree/4928ad4201126973ca38e5b09c245b9e75219cf0/skills/auto-editor-transcribe) |
| gpt-image-2-style-library | 图像风格和提示词参考 | ready | [gpt-image-2-style-library](https://github.com/freestylefly/awesome-gpt-image-2/tree/63e6176fa01be51c000108dacd72716d3e46784b/agents/skills/gpt-image-2-style-library) |
| outlier-post-finder | 异常高表现作品研究 | ready | [social-research](https://github.com/ScrapeCreators/social-media-research-skills/tree/64ba7b4dea71e130d2712ffb6c1c1024b3b7c4b2/.) |
| comment-mining | 观众评论与需求提取 | ready | [social-research](https://github.com/ScrapeCreators/social-media-research-skills/tree/64ba7b4dea71e130d2712ffb6c1c1024b3b7c4b2/.) |
| creator-profile-teardown | 账号定位与内容打法拆解 | ready | [social-research](https://github.com/ScrapeCreators/social-media-research-skills/tree/64ba7b4dea71e130d2712ffb6c1c1024b3b7c4b2/.) |
| trend-discovery | 话题、形式与音乐趋势 | ready | [social-research](https://github.com/ScrapeCreators/social-media-research-skills/tree/64ba7b4dea71e130d2712ffb6c1c1024b3b7c4b2/.) |
| competitor-social-research | 竞品内容比较 | ready | [social-research](https://github.com/ScrapeCreators/social-media-research-skills/tree/64ba7b4dea71e130d2712ffb6c1c1024b3b7c4b2/.) |
| transcript-intelligence | 转写内容的观点与结构提取 | ready | [social-research](https://github.com/ScrapeCreators/social-media-research-skills/tree/64ba7b4dea71e130d2712ffb6c1c1024b3b7c4b2/.) |
| humanizer-zh | 保留事实与语气的中文润色 | ready | [humanizer-zh](https://github.com/op7418/Humanizer-zh/tree/f4518a8eab97b8bfebc66a89d34320a89bef6930/.) |
| guizang-social-card-skill | 社交卡片与封面制作 | ready | [guizang-social-card-skill](https://github.com/op7418/guizang-social-card-skill/tree/cf4b810fac1c73fb65a2bb31d8c9278d82cbc4c5/.) |
| threejs-choose-skills | 三维能力选型与跨模块交接 | ready | [threejs-choose-skills](https://github.com/linegel/threejs-complete-set-of-skill/tree/e3c9563a070b214aa73b84d1ea6026c9ec4db6cb/skills/threejs-choose-skills) |
| threejs-visual-validation | 三维画面验证 | ready | [threejs-visual-validation](https://github.com/linegel/threejs-complete-set-of-skill/tree/e3c9563a070b214aa73b84d1ea6026c9ec4db6cb/skills/threejs-visual-validation) |
| threejs-scene | 三维场景结构与摄影机 | ready | [threejs-core](https://github.com/cesartevisual/threejs-skills/tree/84f9bcb4bea1f7a28d57fe7f0af78f7f9c3dc467/skills) |
| threejs-materials | 材质与表面表达 | ready | [threejs-core](https://github.com/cesartevisual/threejs-skills/tree/84f9bcb4bea1f7a28d57fe7f0af78f7f9c3dc467/skills) |
| threejs-animation | 三维物体和角色动画 | ready | [threejs-core](https://github.com/cesartevisual/threejs-skills/tree/84f9bcb4bea1f7a28d57fe7f0af78f7f9c3dc467/skills) |
| threejs-webgpu | WebGPU渲染与TSL | ready | [threejs-core](https://github.com/cesartevisual/threejs-skills/tree/84f9bcb4bea1f7a28d57fe7f0af78f7f9c3dc467/skills) |
| blender-pro-workflow | 三维制作阶段与交付 | ready | [blender](https://github.com/RobLe3/cc-blender-skill/tree/a2634b588e80265e796aa53f8ab178d75105c2af/plugin) |
| blender-animation | 三维关键帧与动画 | ready | [blender](https://github.com/RobLe3/cc-blender-skill/tree/a2634b588e80265e796aa53f8ab178d75105c2af/plugin) |
| blender-cameras | 摄影机与镜头语言 | ready | [blender](https://github.com/RobLe3/cc-blender-skill/tree/a2634b588e80265e796aa53f8ab178d75105c2af/plugin) |
| blender-lighting | 场景和产品布光 | ready | [blender](https://github.com/RobLe3/cc-blender-skill/tree/a2634b588e80265e796aa53f8ab178d75105c2af/plugin) |
| blender-materials | 材质节点与表面 | ready | [blender](https://github.com/RobLe3/cc-blender-skill/tree/a2634b588e80265e796aa53f8ab178d75105c2af/plugin) |
| blender-modeling | 建模与形体 | ready | [blender](https://github.com/RobLe3/cc-blender-skill/tree/a2634b588e80265e796aa53f8ab178d75105c2af/plugin) |
| blender-rendering | 渲染设置与成片输出 | ready | [blender](https://github.com/RobLe3/cc-blender-skill/tree/a2634b588e80265e796aa53f8ab178d75105c2af/plugin) |
| video-project-orchestration | 片型装配、团队与阶段交接 | ready | [video-project-orchestration](https://github.com/oTATo-Boss/my-skills/tree/f4aba90fa8dc83ffaaed6c07952f52bb962f213c/skills/video/production/video-project-orchestration) |
| screenwriting | 影视剧本、场次与分集结构 | ready | [screenwriting](https://github.com/oTATo-Boss/my-skills/tree/f4aba90fa8dc83ffaaed6c07952f52bb962f213c/skills/video/creative/screenwriting) |
| production-continuity | 跨镜头和跨集连续性 | ready | [production-continuity](https://github.com/oTATo-Boss/my-skills/tree/f4aba90fa8dc83ffaaed6c07952f52bb962f213c/skills/video/production/production-continuity) |
| video-production-pipeline | 制作路线与工程交付 | ready | [video-production-pipeline](https://github.com/oTATo-Boss/my-skills/tree/f4aba90fa8dc83ffaaed6c07952f52bb962f213c/skills/video/production/video-production-pipeline) |
| animejs | 动画API与时间线 | candidate | [candidate-local](https://github.com/oTATo-Boss/my-skills) |
| animejs-creative-motion | 动态字体、SVG与创意动效 | ready | [animejs-creative-motion](https://github.com/oTATo-Boss/my-skills/tree/f4aba90fa8dc83ffaaed6c07952f52bb962f213c/skills/animejs/animejs-creative-motion) |
| animejs-workflows | React集成与资源生命周期 | ready | [animejs-workflows](https://github.com/oTATo-Boss/my-skills/tree/f4aba90fa8dc83ffaaed6c07952f52bb962f213c/skills/animejs/animejs-workflows) |
| animejs-example-library | 官方示例源码与资源快照 | ready | [animejs-example-library](https://github.com/oTATo-Boss/my-skills/tree/f4aba90fa8dc83ffaaed6c07952f52bb962f213c/skills/animejs/animejs-example-library) |
| codex-imagegen | 通过Codex工具生成与编辑图片 | ready | [codex-imagegen](https://github.com/oTATo-Boss/my-skills/tree/f4aba90fa8dc83ffaaed6c07952f52bb962f213c/skills/image/codex-imagegen) |
| ai-liveaction-fusion | 真人实拍与AI镜头融合 | candidate | [candidate-local](https://github.com/oTATo-Boss/my-skills) |
| fashion-picture | 人物服装与时尚图像 | candidate | [candidate-local](https://github.com/oTATo-Boss/my-skills) |
| video-frames | 视频抽帧与片段提取 | candidate | [candidate-local](https://github.com/oTATo-Boss/my-skills) |
| bs-hyperframes-velocity-sting | 速度匹配的短片头 | candidate | [candidate-local](https://github.com/oTATo-Boss/my-skills) |

## 执行边界

市场研究可借鉴研究套件的方法；数据渠道按项目配置，文件安装不证明API或账号已登录。社媒优化、平台阈值不能直接套到电影、科普或MV。

框架技能只服务选定制作路线，不能覆盖项目简报、授权范围、版本锁和交付目标。Anime.js三个适配入口已有公开固定版本；其余候选先补来源再加入路线。Codex系统生图与插件工具由客户端管理；项目不把缓存当通用可安装技能。

角色具体分配见 `role/<角色>/agent.yaml`；执行期间新增技能时同步项目配置、来源注册与安装验证，不静默删掉缺失分配。
