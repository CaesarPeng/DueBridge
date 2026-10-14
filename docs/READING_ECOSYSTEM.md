# 资料读取方向的现成项目

调研日期：2026-10-14。以下根据作者仓库及文档筛选，未接入真实学生账号，也没有宣称效果或权限已实测。DueBridge 聚焦会话复用、列表准确采集及小众站适配；第三方项目在 Agent 客户端并列连接，目前没有内置代理桥。

| 项目 | 能读什么 | 适合放在哪一层 | 关键边界 |
| --- | --- | --- | --- |
| [mtgibbs/canvas-lms-mcp](https://github.com/mtgibbs/canvas-lms-mcp) | Canvas 课程、作业、成绩和 missing work | Canvas 专用读取接口，优先复用 | 作者说明为只读；需 Canvas API token 和学校 base URL，不能复用 Arc 的登录来免配置 token |
| [Microsoft MarkItDown MCP](https://github.com/microsoft/markitdown/tree/main/packages/markitdown-mcp) | 把文件/网络 URI 转为 Markdown | 扩展资料格式转换 | 主要工具 convert_to_markdown；不是 LMS 会话或列表遍历器，本地文件读取范围取决于进程权限/挂载范围 |
| [shinpr/mcp-local-rag](https://github.com/shinpr/mcp-local-rag) | PDF、DOCX、Markdown、TXT 的本地语义+关键词检索及附近段落 | 资料较多时的检索层；本身也有 CLI/MCP | 初次下载模型后可离线；需 Node 22+，不负责 HTML 抓取/登录，不做 OCR，也有索引更新/删除工具 |
| [官方 Filesystem MCP](https://github.com/modelcontextprotocol/servers/tree/main/src/filesystem) | 指定根目录里的文本和目录 | 简单本地文件访问 | 同时含写入/移动等能力，并非纯只读；不做课程采集或 PDF 文字解析 |

推荐组合：Canvas 使用其专用 MCP；小众站、Arc 会话与隐藏/二级列表用 DueBridge；讲义先用 DueBridge scan --all 转为全文缓存，格式需求超出时再选 MarkItDown，文档规模大需要语义检索时再选 local-rag。DueBridge 0.2.0 本身只有关键词搜索，不内置向量库。

接入检索工具时只开放需要的材料/全文目录，别把包含浏览器会话的整个 .homework 作为资料根。搜索命中后仍读取原始上下文，核对来源、时区、学期和采集时间；不同服务器的时间和权限不能由 DueBridge 替它背书。

具体依据：[Canvas 作者 README](https://github.com/mtgibbs/canvas-lms-mcp#readme)、[MarkItDown MCP README](https://github.com/microsoft/markitdown/tree/main/packages/markitdown-mcp#readme)、[local-rag README](https://github.com/shinpr/mcp-local-rag#readme)、[Filesystem README](https://github.com/modelcontextprotocol/servers/tree/main/src/filesystem#readme)。安装与工具列表会变化，实际使用前应核对所选版本。
