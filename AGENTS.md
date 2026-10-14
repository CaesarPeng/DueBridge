# DueBridge 开发约定

本目录是独立的开源候选项目。不要修改外层 Study 课程资料或原 CLI。

工具只采集原文和平台原始字段。不要把日期理解、提交状态猜测、自动答题或提交作业写进采集层。

新增浏览器实现 `browsers.Browser` 接口；新增平台使用独立适配器或 generic 配置。域名必须来自配置的明确名单。自动跟进仅限读取列表的请求。

`.homework/`、`homework.toml`、`materials/`、`DUEDATES.md` 和浏览器会话均为用户私有数据，不能进入源码发布包。发布脚本采用文件名单，禁止递归打包整个工作目录。

检查失败要保留源抓取时间，最近失败另记。每页的范围和时间必须保留。浏览器设置与登录须由用户正常完成，不自动更改安全权限。

验证：`python -m unittest discover -s tests`；浏览器集成：`python -m unittest tests.test_browser_integration`（安装 Playwright 和测试内核后）。
