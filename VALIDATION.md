# 验证记录

验证日期：2026-10-14（Asia/Shanghai）。环境：macOS / Apple Silicon / Python 3.12。

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

## 限制

- Firefox 后端已实现。本机下载的 Playwright Firefox 启动即报 `Could not find profile folder`；使用 Playwright 原生最小启动、不使用本项目代码时也复现。因此 Firefox 采集尚未验证，需在可启动 Firefox 的环境继续测试。
- Chrome channel、Windows 及真实学校的登录/页面变化未在本次本地验证。GitHub Ubuntu CI 已运行，两个 Python 版本的单元测试通过；初次 Chromium 作业的 CDP 临时浏览器启动失败，普通采集场景通过，Firefox/WebKit 被矩阵失败策略取消。0.1.1 已改用独立 Playwright 进程启动 CDP 测试浏览器，并让各内核分别跑完。
- 所有网页集成测试均拦截模拟数据，不访问真实学生账号；不能由模拟测试推出新项目已刷新真实课程数据。

测试使用模拟课程页，不访问真实学生账号。各学校的页面结构、真实登录流程和不同系统的浏览器权限，需要使用者在自己的环境中核对。
