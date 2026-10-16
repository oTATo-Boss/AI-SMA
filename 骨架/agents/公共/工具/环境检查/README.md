# 环境检查

读取项目配置的 `skills.required`、声明式 `agents/公共/技能来源.json` 和本目录 `依赖.json`，核对实际共享技能完整包、精确来源内容、客户端入口身份与必要运行命令。旧账号项目可按角色卡 `skills` 字段读取需求。

```text
python3 agents/公共/工具/环境检查/检查环境.py
python3 agents/公共/工具/环境检查/检查环境.py --json
python3 agents/公共/工具/环境检查/检查环境.py --record
```

Windows 使用实际检测可用的 Python 3 命令。退出码 0 表示本次文件、入口与命令检查通过；1 表示有缺项、冲突或检查错误。未运行客户端或制作小样的状态始终是 `not_verified`，不隐含成功。

默认只读；`--record` 只保存本次实测结果，不安装、不登录、不输出凭据。共享技能安装由部署智能体依据 [技能安装规则](../../技能安装.md) 操作。用户的一句话部署已授权所选项目的普通技能与工具安装；需要登录或管理员权限时按实际情况处理。

API：`inspect(root, *, home=None, check_tools=True, bindings=None) -> dict`。`home` 用于隔离环境或测试；`bindings` 为技能名到真实技能目录，只提供候选，不绕过验证。`record(root, result)` 保存该次 `inspect` 结果。旧团队生成器所需的 `skill_index()`、`index_rows()` 保留，但按名字查找到文件不证明其内容正确。

完整包验证采用来源清单中的每个 Git blob，保留相对资源和执行权限；记录正文、旧回执、相同名字、相同入口文本都不能替代来源证据。Claude 链接须解析到同一实体；Windows junction 按目录身份检查。当前实现不声称插件等价，也不声称有客户端运行时发现证据。

针对性验证：

```text
python3 -m unittest discover -s agents/公共/工具/环境检查/tests -v
```

用临时 home 与项目测试缺共享资源、同名不同内容、多实体冲突、错误链接目标、未知客户端、伪造回执、目录逃逸、待发布来源和依赖循环；不修改真实共享库。
