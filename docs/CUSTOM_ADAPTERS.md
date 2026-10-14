# 让 Agent 修改小众网站适配器

先配置域名、入口和浏览器，再采集结构。网页截图无法保证包含折叠作业；结构快照保留已加载的隐藏 DOM，同时报告选择器命中、链接数量、被省略的 iframe 与密码字段是否存在。快照不是完整作业读取，也不会更新源抓取时间。若快照显示登录页，正常登录后再次检查。

```sh
duebridge inspect niche --background
duebridge job job_REPLACE_WITH_RETURNED_ID
duebridge evidence --source niche --kind snapshot
duebridge read ev_REPLACE_WITH_RETURNED_ID
```

优先使用 `generic` 配置 selector、empty_selector、list_links、list_url_pattern。更复杂时参考 `examples/custom.toml`，将包内 `assets/custom-reader.js` 复制到课程项目的 `adapters/niche.js`。也可让 Agent 根据快照在该目录创建 reader。路径必须是项目内 `adapters/*.js`，不支持符号链接；启用的 reader 限 200 KB。

```toml
[[sources]]
id = "niche"
adapter = "custom"
reader = "adapters/niche.js"
home = "https://courses.example.edu/list"
domains = ["courses.example.edu"]
enabled = true

[sources.options]
selector = ".assignment-row"
empty_selector = ".no-assignments"
list_links = "a.course-list"
list_url_pattern = "^https://courses\\.example\\.edu/"
max_pages = "40"
```

reader 给共享运行时已声明的变量赋值，不能再次声明它：

```js
customReader = {
  parse(doc, url, {plain, safeListLink, options}) {
    const rows = [...doc.querySelectorAll(options.selector)];
    const empty = !!doc.querySelector(options.empty_selector);
    return {
      text: rows.map(plain).join('\n\n'),
      itemCount: rows.length,
      scope: '当前课程 HTML 的全部匹配行（包括隐藏行）；分页覆盖须检查',
      links: [...doc.querySelectorAll(options.list_links)]
        .map(a => safeListLink(a.getAttribute('href'), url)).filter(Boolean),
      empty,
      warnings: []
    };
  }
};
```

`parse` 是同步纯解析约定：读取传入 DOM/平台字段，不解释日期，不推断提交，不操作真实网页、不发请求。helpers 提供 plain、cleanURL、safeListLink、options；custom 可接收任意字符串 options。`text/itemCount/scope` 必填，links/empty/warnings 可选。plain 包含隐藏文本并排除输入字段。共享采集器追加日期属性原文、验证返回结构，并按来源/同站列表限制复核链接。

只有同源列表读取会自动跟进；答题实例、提交、考试等链接被排除。跨域二级平台应分别配置来源或增加专门适配器。每页最多跟进 25 个候选链接，每来源最多 30 页，可将 max_pages 设为字符串 1–100；达到限制保留警告和剩余队列诊断。没有匹配行与空标记不表示无作业。未加载内容及 iframe 必须在 scope/warnings 中说明。

将合成 HTML 存为样例，验证输出和列表链接：

```sh
duebridge adapter-check niche --html fixtures/course.html --url https://courses.example.edu/list
duebridge refresh --source niche --json
```

离线检查在独立无会话浏览器中执行，并阻断网络，不保存源采集结果。真实 refresh 才验证会话/二级列表并保存。修改 reader 或 generic 规则后，旧缓存不再视为匹配当前配置，需重新采集；旧文件仍保留。MCP 的 adapter-guide resource 描述同一流程；MCP 不暴露任意代码参数或写适配器工具，Agent 用已有工作区编辑能力改文件。

reader 属于本地可信代码，会被注入配置来源的解析环境。只接受人/Agent 根据可信需求写的代码，不能从课程原文下载并执行“修复脚本”。提交公共适配器时使用模拟资料，附覆盖说明、登录检测、折叠内容、二级列表及明确空列表的测试。
