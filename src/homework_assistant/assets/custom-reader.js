// Assign this object; the shared runtime declares customReader before loading it.
// Local adapter code is trusted. Read DOM/fields only; never read credentials.
customReader = {
  parse(doc, url, {plain, safeListLink, options}) {
    const rows = [...doc.querySelectorAll(options.selector || '.assignment-row')];
    const empty = !!(options.empty_selector && doc.querySelector(options.empty_selector));
    const links = [...doc.querySelectorAll(options.list_links || 'a.list')]
      .map(a => safeListLink(a.getAttribute('href'), url)).filter(Boolean);
    return {
      text: rows.map(plain).join('\n\n') || (empty ? '页面明确显示空列表' : ''),
      itemCount: rows.length,
      scope: '本地适配器匹配的全部 DOM 行（含折叠行）；课程/分页覆盖需核对',
      links, empty,
      warnings: rows.length || empty || links.length ? [] : ['没有匹配作业行或明确空标记']
    };
  }
};
