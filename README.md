# DueBridge

CLI-first, MCP-compatible browser collection and material-reading tools for AI agents.

一个可以定制学校平台和浏览器的本地作业资料助手。它将网页列表及本地课程文件保存为 `DUEDATES.md` 和原始 JSON，供人或 AI 助手读取资料、核对截止日期。运行时不需要特定 Agent，不调用模型或上传服务，不自动答题或提交作业。MCP 将选取的资料返回客户端，后续数据处理取决于客户端配置。

**Python 3.11+。Arc 接入限 macOS；Chromium、Firefox、WebKit 接入使用 Playwright，适用于其支持的系统。当前版本 0.2.0。**

## 安装与快速开始

解压源码包，在源码目录打开终端：

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install .
```

Windows PowerShell 的激活命令是 `.\.venv\Scripts\Activate.ps1`；如果本机 Python 命令是 `python`，把第一行的 `python3` 换为 `python`。也可直接使用虚拟环境中的 Python，不必修改系统执行策略。Mac 同学可运行 `sh install.sh`，然后用 `./duebridge` 启动。

在存放课程资料的目录初始化。配置和输出属于这个目录，安装目录可以另放：

```sh
duebridge init --preset zju --browser arc
duebridge doctor
duebridge sync --source smartphysics
duebridge scan
duebridge show
```

`homework` 和 `duedates` 是同一个命令的兼容别名。使用源码包启动器时，将 `duebridge` 换成 `./duebridge`。指定其他目录用全局参数，例如 `duebridge --project /path/to/study scan`。

`init --preset zju` 生成 Blackboard、WebAssign、SmartPhysics、ZJUI Learn 和 PrairieLearn 配置；没有个人课程编号和抓取缓存。Blackboard 默认禁用，填写自己的 `courses` 后启用。PrairieLearn 默认禁用只是配置选择，**不代表本学期没有作业**。不同学期应自行核对平台和课程。

首次用 Arc 时，在 macOS 的自动化权限中允许当前终端控制 Arc，并在 Arc 菜单 **View → Developer → Allow JavaScript from Apple Events** 中手动启用。该设置允许获准的自动化程序执行网页脚本；本工具不会自动更改它。登录过期时在 Arc 中正常登录，CLI 会在等待时间内继续采集。

## CLI 与 MCP

CLI 是完整基础接口；MCP 是面向 Agent 的标准化适配层。两者直接调用同一套 Python 服务、浏览器后端、证据读取和任务逻辑，MCP 不重复实现采集，也不绕回子进程解析 CLI 文本。后台任务使用共同 worker。

```sh
duebridge refresh --source smartphysics --background
duebridge job job_REPLACE_WITH_RETURNED_ID
duebridge scan --all --json
duebridge overview
duebridge evidence
duebridge search "late policy"
duebridge read ev_REPLACE_WITH_RETURNED_ID --max-chars 16000
```

`refresh`、`capture` 是 `sync` 的别名。`overview/evidence/search/read/job` 默认返回 JSON；搜索片段只用于定位，读取时按 `next_offset` 分页，并用 `--revision` 核对内容版本。`scan` 保持旧版截止关键词筛选，`scan --all` 保存所有支持的课程资料全文，适合“读取资料”。

可选 MCP 支持，在源码目录安装：

```sh
python -m pip install ".[mcp]"
duebridge --project /path/to/study mcp config
duebridge --project /path/to/study mcp serve
```

`mcp config` 输出通用 `mcpServers` 配置；用已安装 DueBridge 的 Python 生成，再放进支持本地 stdio MCP 的客户端相应配置处。默认只读缓存，提供来源概览、证据列表、关键词搜索、分页全文和任务状态。加入 `--allow-refresh` 后才暴露后台采集、扫描和结构检查工具。Agent 可直接用 Shell 调 CLI，也可自动发现 MCP 工具；浏览器登录过期仍需人正常登录。完整命令、工具映射和连接方式见 [Agent 接入说明](docs/AGENT_INTERFACE.md)。

项目聚焦浏览器会话、二级列表、折叠内容及可修改的适配器。Canvas 等大平台优先在 Agent 客户端中并列接入现成的读取型 MCP；DueBridge 不提供 Canvas MCP 转发代理。已有项目对比见 [资料读取项目调研](docs/READING_ECOSYSTEM.md)。

## 浏览器选择

| 配置 engine | 接入方式 | 登录会话 |
| --- | --- | --- |
| `arc` | Arc 自带 AppleScript 接口，macOS | 现有正常窗口和 Profile |
| `chromium` | Playwright Chromium | 项目独立目录，首次需登录 |
| `chrome` / `edge` | Playwright 调用已安装的 Chrome / Edge | 项目独立目录，首次需登录 |
| `firefox` | Playwright Firefox（Linux CI 通过，本机 macOS 启动受限） | 项目独立目录，首次需登录 |
| `webkit` | Playwright WebKit | 项目独立目录，首次需登录 |
| `cdp` | 连接显式开启的本机 Chromium 调试端口 | 被连接浏览器的已有会话 |

Playwright 模式需要额外安装依赖和所选内核。请在源码目录安装可选依赖，再回到课程目录采集：

```sh
python -m pip install ".[browser]"
duebridge browser-install chromium
duebridge sync --browser chromium
```

把 `chromium` 换成 `firefox` 或 `webkit` 即可安装对应内核。`chrome` 和 `edge` 使用本机已安装的浏览器，不复制日常 Profile。`webkit` 指 Playwright 的 WebKit 浏览器，并不是接管已经打开的 Safari。运行结束后专属窗口关闭，登录目录保留；`duebridge login smartphysics --browser chromium` 可提前登录。

Chromium、Firefox、WebKit 已通过 GitHub Ubuntu CI 的模拟课程采集测试，本地 Chromium、WebKit、Edge 和 CDP 也有验证。本机 macOS 的 Playwright Firefox 仍在启动阶段报告 `Could not find profile folder`，原生 Playwright 最小启动也复现；Linux 通过不能推出所有 Mac 均已验证。完整范围见 `VALIDATION.md`。

CDP 仅支持本机地址，需自行启动带调试端口和专用用户目录的 Chromium 浏览器，再配置：

```toml
[browser]
engine = "cdp"
cdp_endpoint = "http://127.0.0.1:9222"
timeout = 180
```

不要把调试端口暴露到网络。程序不会自动开启它，也不会关闭连接到的浏览器。CDP 只用于 Chromium 系列。具体限制参考 [Playwright 浏览器类型文档](https://playwright.dev/python/docs/api/class-browsertype) 和 [浏览器安装文档](https://playwright.dev/python/docs/browsers)。

## 定制学校和课程

编辑 `homework.toml`。所有时间展示默认 `Asia/Shanghai`，平台截止日期原字段保持原样；源抓取时间和失败尝试时间分开记录。

```toml
timezone = "Asia/Shanghai"
output = "DUEDATES.md"

[browser]
engine = "arc"
timeout = 180

[local]
paths = ["materials"]

[[sources]]
id = "school-blackboard"
adapter = "blackboard"
home = "https://blackboard.example.edu/"
domains = ["blackboard.example.edu"]
courses = [
  {name = "Calculus", id = "_1234_1"},
  {name = "Physics", id = "_5678_1"},
]
```

Blackboard 的课程 id 来自打开课程后 URL 中的 `course_id`，例如 `_1234_1`。不同学校的登录、权限及 API 版本可能不同；这里的适配器读取 Blackboard 原始成绩册列，不能承诺覆盖所有公告或内容页。其他域名的部署需自行验证。

支持的适配器：

- `blackboard`：读取配置课程的作业列，跟进分页，保留空日期；部分课程失败时保留旧资料。
- `webassign`：Cengage 只作为入口，实际作业来自 `assignment_domains` 中的 WebAssign。读取安全的列表二级页，动态列表回退会标明限制。
- `smartphysics`：读取完整 DOM 的 `.unit-assignment`，包含未展开单元；从入口发现课程。
- `zjuilearn` / `prairielearn`：逐门课 assessments 列表，保留提示框内的原始计分时间段。
- `generic`：按配置的 CSS 选择器读取名单内页面。
- `custom`：读取项目 `adapters/` 下的 JavaScript 解析器，供 Agent 修改小众网站逻辑；附离线样例检查。

适配器只适用于它对应的页面结构；仅改变域名无法把任意 LMS 自动变成 Blackboard 或 PrairieLearn。

## 接入其他作业网站

`duebridge init` 生成通用示例。替换域名和实际页面选择器，并设置 `enabled = true`：

```toml
[[sources]]
id = "my-course"
adapter = "generic"
home = "https://courses.example.edu/assignments"
domains = ["courses.example.edu"]

[sources.options]
selector = ".assignment-row"
empty_selector = ".no-assignments"
list_links = "a.assignment-list"
list_url_pattern = "^https://courses\\.example\\.edu/assignments(?:[/?]|$)"
```

`selector` 决定保留哪些作业行，包括隐藏元素。`empty_selector` 是页面明确表示空列表的标记；没匹配到作业行且没有空标记时会报错，不认定没有作业。两个 `list_*` 字段都配置才会跟进同站列表链接；默认仅读取当前页面。页面结构不同、内嵌跨域 iframe 或懒加载列表需要专门适配，覆盖范围仍需核对。

复杂页面可使用本地 `customReader`，流程是 `inspect` → 读取清理后的结构快照 → 编辑适配器 → `adapter-check` 离线检查 → 实际 `refresh`。结构快照保留隐藏 DOM，移除表单字段、脚本、iframe、已知凭据属性和 URL 参数；不会更新作业采集时间。未加载的懒加载内容、iframe 或需要交互的菜单仍需适配，工具不会把当前 DOM 当成全部作业。具体开发流程见 [自定义适配器](docs/CUSTOM_ADAPTERS.md)。

## 本地文件与输出

将 PDF、DOCX、HTML、Markdown、TXT、Notebook 放进配置的 `local.paths`。执行 `duebridge scan` 后，含 due / deadline / 截止等关键词的文件会保存全文，索引链接到全文缓存。支持的读取上限是单文件 20 MB、PDF 150 页。不做 OCR，不读取旧版 Office 文件；扫描失败另列。已有资料可能属于旧学期，也可能使用相对时间。

```sh
duebridge sync                        # 采集所有启用来源
duebridge sync --source webassign     # 只更新一个来源
duebridge sync --timeout 300          # 每来源等待最多 300 秒
duebridge status                      # 检查各来源独立的时间与最近错误
duebridge show --json                 # 给其他助手使用的原始 JSON
```

退出码：`0` 成功，`1` 配置或运行错误，`2` 部分来源/本地文件失败，`130` 用户取消。失败时保留已保存数据；最近失败另记，不把源抓取时间更新成尝试时间。来源历史页各有独立时间，新的采集不会自动表示全部课程已覆盖。工具按请求采集；`--background` 可启动本次后台任务，不是定时调度。

## 数据边界和分享

`homework.toml`、`.homework/`（包括浏览器登录目录与原文）、`materials/`、`DUEDATES.md` 都是用户数据，默认忽略。采集脚本排除表单字段、密码输入和已知凭据 URL 参数，不调用密码库或导出 Cookie；课程原文仍可能包含姓名等个人内容，分享时使用发布脚本生成的源码包，不直接压缩工作目录。

如果交给 AI 助手：先检查来源时间和覆盖范围，再读取索引链接的本地全文；保留原站来源，区分公告、syllabus 与平台日期，冲突时说明两者并按较早时间安排。不要仅凭缓存里的过期日期判断作业未完成。

## 开发与发布

浏览器实现位于 `src/homework_assistant/browsers/`，统一提供 `tabs/open/focus/execute/pause/close`。平台解析与列表采集位于 `assets/sites.js`、`assets/collector.js`，只处理原文和字段。Python 层负责配置、来源校验、缓存合并和输出。

```sh
python -m pip install -e ".[dev]"
python -m unittest discover -s tests
python -m playwright install chromium firefox webkit
HOMEWORK_TEST_ENGINES=chromium,firefox,webkit python -m unittest tests.test_browser_integration
python scripts/package.py
```

浏览器测试使用本地拦截的模拟课程页，不访问真实学生账号。真实网站适配和各系统权限需额外验证。测试运行情况见 `VALIDATION.md`。发布脚本只打包明确的源文件、文档与测试，并检查私有路径和个人编号；输出源码 ZIP、wheel、sdist 和 SHA-256 文件。

MIT 许可。项目从 Study CLI 提取，已有平台逻辑保留，但运行不依赖 Study 工程、旧扩展或 Codex 本机路径。GitHub：[CaesarPeng/DueBridge](https://github.com/CaesarPeng/DueBridge)。尚未发布到 PyPI；请从源码或 GitHub Release 安装。

## 类似项目

这些项目说明课程资料与作业日期的 CLI/自动整理方向已有实践：

| 项目 | 主要定位 |
| --- | --- |
| [d2l-cli](https://github.com/Aaryan-Kapoor/d2l-cli) | 为 AI 助手只读提供 Brightspace 课程、作业、截止日期与资料 |
| [canvas-cli](https://github.com/thedavidweng/canvas-cli) | Canvas LMS 的终端接口，提供稳定 JSON、分页和操作安全控制 |
| [Planit](https://github.com/tanjeffreyz/planit) | 抓取作业日期并汇入交互日历 |
| [Blackboard-LMS-CLI](https://github.com/Magnus2142/Blackboard-LMS-CLI) | Blackboard Learn REST API 命令行工具 |

DueBridge 的重点是可配置的平台与浏览器接入、现有 Arc 会话、本地课程文件全文，以及保留各来源的抓取时间和覆盖范围。它仍是资料采集层，日期推理交给使用者或上层助手。
