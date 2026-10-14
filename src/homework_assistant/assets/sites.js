// Site-specific raw-text parsers; no date interpretation.
const PRIVATE_KEYS = new Set(['userpass','password','passwd','auth','authorization','access_token','id_token','refresh_token','token','session','sessionid','sid','code','state','ticket','csrf','csrf_token','signature']);
function cleanURL(raw) {
  const url = new URL(raw);
  if (url.protocol !== 'https:' || url.username || url.password) throw Error('仅保存 HTTPS 课程来源');
  url.hash = '';
  for (const key of [...url.searchParams.keys()]) if (PRIVATE_KEYS.has(key.toLowerCase())) url.searchParams.delete(key);
  return url.href;
}
function platformFor(raw) {
  try {
    const u = new URL(raw), h = u.hostname;
    if (u.protocol !== 'https:' || u.username || u.password || (u.port && u.port !== '443')) return null;
    if(SOURCE_CONFIG.domains.some(p=>hostMatches(h,p)))return SOURCE_CONFIG.platform;
  } catch {}
  return null;
}
function hostMatches(host,pattern){return pattern.startsWith('*.')?host.endsWith(pattern.slice(1)):host===pattern;}
function isAssignmentSource(raw) {
  const id=platformFor(raw);
  if(!id)return false;
  const host=new URL(raw).hostname;
  return SOURCE_CONFIG.assignment_domains.some(p=>hostMatches(host,p));
}


const normal=t=>String(t||'').split('\n').map(x=>x.trim()).join('\n').replace(/\n{3,}/g,'\n\n').trim();
function plain(node){
  if(!node)return '';const copy=node.cloneNode(true);
  copy.querySelectorAll('script,style,input,textarea,select,iframe,object').forEach(e=>e.remove());
  for(const cell of copy.querySelectorAll('td,th'))cell.after(copy.ownerDocument.createTextNode('\t'));
  for(const block of copy.querySelectorAll('p,div,section,article,h1,h2,h3,h4,tr,li,br')){block.before(copy.ownerDocument.createTextNode('\n'));block.after(copy.ownerDocument.createTextNode('\n'));}
  return normal(copy.textContent);
}
function tips(doc){return [...doc.querySelectorAll('[data-content],[data-bs-content],[data-original-title]')].map(e=>plain(new DOMParser().parseFromString(e.getAttribute('data-content')||e.getAttribute('data-bs-content')||e.getAttribute('data-original-title')||'','text/html').body)).filter(Boolean);}
function safeLink(raw,base){try{const u=new URL(raw,base);if(u.origin===new URL(base).origin&&platformFor(u.href))return u.href;}catch{}return null;}
function safeListLink(raw,base){
  const target=safeLink(raw,base);if(!target)return null;
  if(/(?:assessment_instance|question|submit|submission|exam|answer)(?:[/?=&_]|$)/i.test(target))return null;
  const pattern=SOURCE_CONFIG.options?.list_url_pattern;
  if(pattern&&!new RegExp(pattern).test(target))return null;
  return target;
}
function sanitizeHTML(doc,base){
  const copy=doc.documentElement.cloneNode(true);
  copy.querySelectorAll('script,style,input,textarea,select,iframe,object,embed,meta,base').forEach(n=>n.remove());
  for(const node of [copy,...copy.querySelectorAll('*')])for(const attr of [...node.attributes]){
    if(/^on/i.test(attr.name)||/(?:password|token|session|csrf|authorization|nonce)/i.test(attr.name))node.removeAttribute(attr.name);
    else if(['href','src','action','formaction'].includes(attr.name)){
      try{node.setAttribute(attr.name,cleanURL(new URL(attr.value,base).href));}catch{node.removeAttribute(attr.name);}
    }else if(attr.name==='style'&&/url\s*\(/i.test(attr.value))node.removeAttribute(attr.name);
  }
  return copy.outerHTML;
}
function login(doc,url){
  const content=doc.body?.textContent||'';
  const configured=['generic','custom'].includes(SOURCE_CONFIG.platform)&&SOURCE_CONFIG.options;
  const genericRows=configured&&((configured.selector&&doc.querySelector(configured.selector))||(configured.empty_selector&&doc.querySelector(configured.empty_selector)));
  const hasRows=!!genericRows||!!doc.querySelector('.unit-assignment,.course-title a[href*="Course"],a[href*="/pl/course_instance/"]') || /Available credit|My Assignments/.test(content);
  const signIn=[...doc.querySelectorAll('a,button')].some(e=>/^(sign\s*in|log\s*in|登录)/i.test(plain(e)));
  return /\/login|\/signin|\/sign-in|\/Account\/(Login|SignIn)/i.test(new URL(url).pathname) || ((!hasRows)&&(!!doc.querySelector('input[type="password"]')||signIn));
}
function parseCourseHTML({html,url,platform=platformFor(url)}) {
  const doc=new DOMParser().parseFromString(html,'text/html');
  if(login(doc,url))return {requiresLogin:true,links:[]};
  const raw=plain(doc.body),result={platform,url:cleanURL(url),title:doc.title,text:raw,fetched_at:new Date().toISOString(),links:[],warnings:[]};
  const extra=tips(doc);if(extra.length)result.text+='\n\n提示框原文：\n'+[...new Set(extra)].join('\n\n');
  const dateMeta=[...doc.querySelectorAll('.duedate,[datetime],[data-timezone],[data-zone]')].flatMap(e=>['datetime','data-date','data-start','data-due','data-timezone','data-zone','title'].map(key=>e.hasAttribute(key)?`${key}: ${e.getAttribute(key)}`:'').filter(Boolean));
  const links=new Set();
  if(platform==='custom') {
    if(!customReader||typeof customReader.parse!=='function')throw Error('customReader.parse 未定义');
    const value=customReader.parse(doc,url,{plain,cleanURL,safeListLink,options:SOURCE_CONFIG.options||{}});
    if(!value||typeof value.text!=='string'||!Number.isInteger(value.itemCount)||value.itemCount<0||typeof value.scope!=='string')throw Error('customReader 返回值需要 text、itemCount、scope');
    Object.assign(result,{text:value.text,itemCount:value.itemCount,scope:value.scope,empty:value.empty===true});
    result.warnings.push(...(Array.isArray(value.warnings)?value.warnings.map(String):[]));
    for(const raw of value.links||[]){const target=safeListLink(raw,url);if(target)links.add(target);else result.warnings.push('适配器的链接被来源/列表限制排除，需要核对覆盖');}
  } else if(platform==='generic') {
    const options=SOURCE_CONFIG.options||{};
    if(!options.selector)throw Error('generic 适配器需要 options.selector');
    const rows=[...doc.querySelectorAll(options.selector)];
    result.itemCount=rows.length;
    result.empty=!!(options.empty_selector&&doc.querySelector(options.empty_selector));
    result.scope='配置选择器 '+options.selector+' 的全部 DOM 行（含隐藏元素）；覆盖范围需核对';
    result.text=rows.map(plain).join('\n\n')||(result.empty?'页面匹配了配置的空列表标记':'没有匹配到配置的作业行');
    if(options.list_links&&options.list_url_pattern){
      const pattern=new RegExp(options.list_url_pattern);
      for(const a of doc.querySelectorAll(options.list_links)){
        const target=safeLink(a.getAttribute('href'),url);
        if(target&&pattern.test(target)&&!/(?:assessment_instance|question|submit|submission|exam|answer)(?:[/?=&_]|$)/i.test(target))links.add(target);
      }
    }
  } else if(platform==='smartphysics') {
    // Structural hooks are independently implemented from the public site's interface.
    const rows=[...doc.querySelectorAll('.unit-assignment')];
    if(rows.length){
      result.itemCount=rows.length;result.scope='完整课程 HTML 中的全部作业行，包含折叠单元';
      result.text=doc.title+'\n\n'+result.scope+'\n';
      for(const row of rows){
        let parent=row.parentElement,unit='';
        while(parent&&parent!==doc.body){const h=parent.querySelector('.UnitTitle');if(h){unit=plain(h);break;}parent=parent.parentElement;}
        const rowText=plain(row);if(rowText)result.text+='\n'+(unit?'单元：'+unit+'\n':'')+rowText+'\n';
      }
      if(extra.length)result.text+='\n提示框原文：\n'+extra.join('\n\n');
    } else {
      if(/^\/Course$/i.test(new URL(url).pathname))result.warnings.push('课程结构存在，但没有匹配到完整作业行；需要核对页面结构，不能视为无作业');
      for(const a of doc.querySelectorAll('.course-title a[href*="enrollmentID"],a[href*="/Course?enrollmentID="]')){
        if(a.closest('#PastEnrollments'))continue;
        const target=safeLink(a.getAttribute('href'),url);if(target&&/^\/Course$/i.test(new URL(target).pathname))links.add(target);
      }
    }
  } else if(platform==='zjuilearn'||platform==='prairielearn') {
    for(const a of doc.querySelectorAll('a[href]')){
      const target=safeLink(a.getAttribute('href'),url);if(!target)continue;const u=new URL(target);
      if(/^\/pl\/course_instance\/\d+\/?$/.test(u.pathname))u.pathname=u.pathname.replace(/\/$/,'')+'/assessments';
      else if(!/^\/pl\/course_instance\/\d+\/assessments\/?$/.test(u.pathname))continue;
      links.add(u.href);
    }
    result.itemCount=[...doc.querySelectorAll('tr')].filter(r=>r.querySelectorAll('td').length>=3).length;
    result.scope='课程作业列表及提示框中的原始计分时间段';
  } else if(platform==='webassign') {
    if(!isAssignmentSource(url))return {navigationOnly:true,links:[]};
    if(!/Current Assignments|Past Assignments|No current assignments/i.test(raw) && !(/My Assignments/i.test(raw)&&/\bDue\b/i.test(raw)))throw Error('尚未识别 WebAssign 作业列表；请进入 My Assignments，旧资料保留');
    result.scope='WebAssign 作业列表及可读取的列表二级页面';
    for(const a of doc.querySelectorAll('a[href]')){
      if(!/^(My Assignments|Current Assignments|Past Assignments|Calendar|Home)$/i.test(plain(a)))continue;
      const target=safeLink(a.getAttribute('href'),url);if(!target)continue;const u=new URL(target);
      const action=u.searchParams.get('action')||'';
      if(/student\.pl$/i.test(u.pathname)&&/^(home\/index|assignments\/(list|index|current|past)|calendar\/(index|list|view|month))(?:$|[/?])/i.test(action))links.add(target);
    }
  }
  if(dateMeta.length)result.text+='\n\n页面日期属性原文：\n'+[...new Set(dateMeta)].join('\n');
  const here=new URL(url);here.hash='';links.delete(here.href);
  if(links.size>25)result.warnings.push('当前页列表链接超过 25 条，尚有链接未读取');
  result.links=[...links].slice(0,25);
  return result;
}
