# 验证记录

验证日期：2026-10-14（Asia/Shanghai）。环境：macOS / Apple Silicon / Python 3.12。

## 0.2.0 双接口验证

- 本地 Chromium/WebKit 的完整测试集共 32 个测试方法通过，含原有平台与 CDP 场景，以及新的 CLI/MCP 证据读取、后台任务、自定义适配器和结构检查场景。
- 使用官方 MCP Python SDK 的真实 stdio Client/Server：握手、工具发现、缓存证据搜索/全文读取、resources、prompt、预期错误和显式启用采集的工具集通过；后台 scan 启动真实 worker，任务完成后读取实际保存结果。
- 全文分页拼接、revision 更新检测、任意路径/符号链接拒绝、scan --all 收录无截止关键词资料、原文件修改提示、同项目写锁均通过。
- 浏览器模拟验证：登录等待后同一页面正常登录完成可续采；custom reader 读取隐藏行和二级列表；离线 HTML 检查阻断网络；结构快照保留隐藏 DOM、排除测试凭据与脚本、保持旧源时间；达到页数上限显式报告部分覆盖。
- 本地资料目录不能通过符号链接转入私有会话缓存；补充此场景后，9 个受影响的资料/Agent 接口测试通过。
- 安装后的 0.2.0 wheel 在隔离模式启动 stdio，通过生成的客户端配置完成后台 scan 与全文读取；发布名单检查通过。
- 自定义 reader 修改会使旧缓存不再匹配当前配置；MCP 不允许传任意代码或文件路径。第三方 Canvas/文档 MCP 仅做仓库调研，没有安装到客户端或访问真实账号。

0.1.x 的验证记录保留如下，不能视为 0.2.0 的每个平台都已重新实测。

## 已运行

- `HOMEWORK_TEST_ENGINES=chromium,webkit python -m unittest discover -s tests -v`：22 个测试方法全部通过，包括两个内核的真实浏览器启动、模拟课程采集和本机 CDP 连接。
- `HOMEWORK_TEST_ENGINES=edge python -m unittest tests.test_browser_integration -v`：初始 5 个平台场景全部通过，使用本机 Microsoft Edge。后续新增的登录、空列表和动态列表测试未在 Edge 上重复运行。
- Arc AppleScript 桥编译通过，实际读取现有 Arc 窗口标签列表成功；没有执行新项目的真实站点 sync。
- Chromium / WebKit：折叠物理作业行、Blackboard 分页与部分课程失败、ZJUI 提示框日期、自定义域名、通用 CSS 规则、安全列表链接、WebAssign 深页面转列表与动态列表回退、登录页面和空列表均有模拟验证。
- CDP：连接临时 Chromium 进程、采集通用列表，断开后外部浏览器进程仍在运行。
- 原始时间与旧资料保留、URL 凭据参数排除、来源名单校验、跨课程合并、本地 PDF/DOCX 全文、符号链接排除、配置路径与时区检查均通过。
- 源码启动器版本命令已运行。
- 使用系统 Python 3.14 在全新虚拟环境安装 wheel，运行版本、初始化、doctor、本地扫描、JSON 输出和 `duedates` 别名成功；全文包含截止日期前后的规则上下文。
- 解压源码 ZIP，在独立目录执行 `sh install.sh`，再运行源码启动器成功。安装不依赖 Study 工程或 Codex 路径。
- 源码 ZIP、wheel、sdist 的发布名单及内容检查通过，排除了私有配置、原文缓存、会话、材料和个人课程编号，并生成 SHA-256 校验文件。
- 0.1.1 的跨平台 CDP 启动修复已通过本地 Chromium/CDP 测试，Chromium/WebKit 的 22 个测试方法重新通过。
- GitHub Ubuntu CI 的 [修复提交 e872a54](https://github.com/CaesarPeng/DueBridge/actions/runs/38562724255) 五项作业全部成功：Python 3.11、3.13 的单元测试及 Chromium、Firefox、WebKit 的集成测试。Firefox 在 Linux 上已完成采集验证。
- DueBridge 0.1.1 wheel 在全新系统 Python 虚拟环境安装后，`duebridge`、`homework`、`duedates` 三个入口均返回正确版本。

## 限制

- 本机 macOS 下载的 Playwright Firefox 启动即报 `Could not find profile folder`；使用 Playwright 原生最小启动、不使用本项目代码时也复现。Linux 集成测试已通过，本机 macOS 的 Firefox 仍需排查。
- Chrome channel、Windows 及真实学校的登录/页面变化未在本次验证。初次 GitHub CI 的临时 CDP 浏览器启动失败，0.1.1 已改用独立 Playwright 进程启动，并让各内核分别跑完；修复后的 Ubuntu CI 已通过。
- 所有网页集成测试均拦截模拟数据，不访问真实学生账号；不能由模拟测试推出新项目已刷新真实课程数据。

测试使用模拟课程页，不访问真实学生账号。各学校的页面结构、真实登录流程和不同系统的浏览器权限，需要使用者在自己的环境中核对。
