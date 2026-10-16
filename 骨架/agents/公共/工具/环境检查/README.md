# 环境检查

检查本机能不能跑这个项目：命令行工具、应用、Python 包、登录状态，以及 `agents/SKILLS_INDEX.md` 里登记的技能。只读：不安装、不登录、不读取或输出密钥。依赖清单在 `依赖.json`；技能清单不重复，直接读技能索引，按名字在 `skill_roots` 列出的目录里查找。

```bash
python3 agents/公共/工具/环境检查/检查环境.py     # 在项目根目录运行；缺必需项时退出码为 1
```

什么时候跑：新建账号后、换电脑或重装后、工具或技能报错时、技能索引改过之后。

## 缺了怎么补

报告末尾会列出每个缺项的补法：工具给安装命令，技能给技能索引里的"来源"。安装软件、安装技能、登录账号都要先经本人同意；登录和输入 Key 由本人操作。

第一次在一台电脑上使用，按顺序：
1. 基础工具：macOS 先装 Homebrew，再 `brew install python ffmpeg node git`；安装 Google Chrome。需要 Claude 生图时安装 ChatGPT 桌面 App（自带 codex-cli）。
2. 技能：按 `agents/SKILLS_INDEX.md` 的"来源"安装，至少装齐"必需"的。Codex 读 `~/.agents/skills`，Claude Code 读 `~/.claude/skills` 或项目的 `.claude/skills`。
3. 登录和凭据（用到才需要）：本人登录 ChatGPT App；HeyGen CLI 用官方脚本安装后，本人运行 `heygen auth login --oauth`；RunningHub Key 由本人用 RH-minimax-H3 的 `credentials.py set` 隐藏输入；`python3 -m pip install requests`。
4. 再跑一次本检查，直到"结果：通过"。

同一台电脑再开新账号：工具、技能和登录都是共用的，不用重装；要让智能体只读查看平台后台时，再给新账号建一个 Chrome 个人资料并登录。
