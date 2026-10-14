async function collectSource(config) {
  const id=platformFor(location.href);
  if(id!==config.platform || (id==='webassign'&&!isAssignmentSource(location.href)))return {waiting:true,message:'请进入课程的 WebAssign 作业列表'};
  if(document.readyState!=='complete')return {waiting:true,message:'正在加载课程页面'};
  const snapshot=document.documentElement.cloneNode(true);
  snapshot.querySelectorAll('script,style,iframe,object').forEach(n=>n.remove());
  snapshot.querySelectorAll('input,textarea,select').forEach(n=>{
    if(n.getAttribute('type')==='password'){
      const marker=document.createElement('input');marker.type='password';n.replaceWith(marker);
    }else n.remove();
  });
  let current;
  try{current=parseCourseHTML({html:snapshot.outerHTML,url:location.href,platform:id});}
  catch(e){
    if(id==='generic'||id==='custom')return {waiting:true,message:'页面选择规则/适配器无效或未匹配，请先 inspect 并核对读取接口'};
    current={links:[],warnings:[],text:''};
  }
  if(current.requiresLogin)return {waiting:true,message:'请在浏览器中正常登录'};
  const origin=location.origin;
  async function get(raw,json=false){
    const u=new URL(raw,origin);
    if(u.origin!==origin||u.protocol!=='https:'||u.username||u.password)throw Error('课程来源不一致');
    const r=await fetch(u.href,{credentials:'same-origin',cache:'no-store',signal:AbortSignal.timeout(15000)});
    if(r.status===401||r.status===403||new URL(r.url).origin!==origin)throw Error('需要重新登录或接口访问受限');
    if(!r.ok)throw Error('网站暂时不可用（'+r.status+'）');
    if(json){if(!(r.headers.get('content-type')||'').includes('json'))throw Error('需要重新登录');return r.json();}
    const c=parseCourseHTML({html:await r.text(),url:r.url,platform:id});
    if(c.requiresLogin)throw Error('需要重新登录');return c;
  }
  if(id==='blackboard'){
    const api={fetched_at:new Date().toISOString(),courses:[],errors:[]};
    await Promise.all(config.courses.map(async course=>{
      const columns=[],seen=new Set();let next='/learn/api/public/v2/courses/'+course.id+'/gradebook/columns?limit=200';
      try{
        while(next){
          const u=new URL(next,origin);
          if(u.origin!==origin||!u.pathname.startsWith('/learn/api/public/')||seen.has(u.href)||seen.size>=100)throw Error('作业分页异常');
          seen.add(u.href);const data=await get(u.href,true);
          if(!Array.isArray(data.results))throw Error('作业列结构变化');
          columns.push(...data.results.map(c=>({id:c.id,name:c.name,contentId:c.contentId,due:c.grading?.due??null,availability:c.availability})));
          next=data.paging?.nextPage||null;
        }
        api.courses.push({...course,columns,fetched_at:new Date().toISOString()});
      }catch(e){api.errors.push({course:course.name,message:e.message});}
    }));
    if(!api.courses.length)return {waiting:true,message:api.errors[0]?.message||'需要登录 Blackboard'};
    return {api,warnings:api.errors.map(e=>e.course+'：'+e.message)};
  }
  function listURL(raw){
    const u=new URL(raw,origin);if(u.origin!==origin)return null;
    if(id==='generic'||id==='custom')return safeListLink(u.href,location.href);
    if(id==='smartphysics')return u.searchParams.has('enrollmentID')?origin+'/Course?enrollmentID='+encodeURIComponent(u.searchParams.get('enrollmentID')):origin+'/';
    if(id==='zjuilearn'||id==='prairielearn'){
      const course=/\/pl\/course_instance\/(\d+)/.exec(u.pathname)?.[1];
      return course?origin+'/pl/course_instance/'+course+'/assessments':origin+'/pl/';
    }
    if(/student\.pl$/i.test(u.pathname)){
      u.searchParams.set('action','home/index');for(const k of ['assignment','assignment_id','question','question_id'])u.searchParams.delete(k);
      for(const [k,v] of new URL(location.href).searchParams)if(k.toLowerCase()==='userpass'&&!u.searchParams.has(k))u.searchParams.set(k,v);
      return u.href;
    }
    if(/\/student\/.*\/(home|assignments|calendar)(\/|$)/i.test(u.pathname))return u.href;
    return null;
  }
  const seeds=[...config.seeds,location.href];
  if(id==='smartphysics')seeds.unshift(origin+'/',config.home);
  if(id==='zjuilearn'||id==='prairielearn')seeds.unshift(origin+'/pl/');
  const queue=seeds.map(listURL).filter(Boolean),seen=new Set(),pages=[],warnings=[...(current.warnings||[])];
  const maxPages=Math.min(100,Math.max(1,Number(config.options?.max_pages)||30));
  if(id==='webassign')queue.push(...(current.links||[]));
  function isList(c){return id==='generic'||id==='custom'?(c.itemCount>0||c.empty):id==='smartphysics'?c.itemCount>0:id==='zjuilearn'||id==='prairielearn'?/\/assessments\/?$/.test(new URL(c.url).pathname):!c.navigationOnly&&!!c.text;}
  if((id==='smartphysics'||id==='generic'||id==='custom')&&isList(current)){
    if(id==='smartphysics')current.scope='当前课程页面的全部 DOM 作业行，包含未展开单元';
    pages.push(current);seen.add(cleanURL(location.href));
  }
  if(id==='generic'||id==='custom')queue.push(...(current.links||[]));
  // SmartPhysics ships its full unit rows in the loaded course DOM. Other
  // lists are refreshed by GET; dynamic WebAssign can fall back to its DOM.
  while(queue.length&&seen.size<maxPages){
    const raw=queue.shift(),key=cleanURL(raw);if(seen.has(key))continue;seen.add(key);
    try{
      const c=await get(raw);
      if(isList(c))pages.push(c);
      warnings.push(...(c.warnings||[]));
      for(const link of c.links||[])if(!seen.has(cleanURL(link)))queue.push(link);
    }catch(e){
      warnings.push(id==='smartphysics'&&current.itemCount>0&&new URL(raw).pathname==='/'
        ?'课程入口的后台请求未成功；已打开课程的全部作业行已读取，其他课程覆盖需核对':e.message);
    }
  }
  const remaining=[...new Set(queue.map(cleanURL))].filter(key=>!seen.has(key));
  if(remaining.length)warnings.push('达到 '+maxPages+' 页读取上限，尚有列表页未核对');
  if(id==='webassign'&&!pages.length&&isList(current)){
    current.scope='当前浏览器已加载的 WebAssign 动态作业列表；二级列表覆盖需核对';
    pages.push(current);
    warnings.push('WebAssign 从已打开的动态列表读取；服务器 HTML 未提供完整列表，二级列表覆盖需核对');
  }
  if(!pages.length)return {waiting:true,message:warnings[0]||'请进入课程作业列表'};
  return {pages:pages.map(({links,...c})=>c),warnings:[...new Set(warnings)],
          diagnostics:{visited_pages:seen.size,remaining_queue:remaining.length,page_limit:maxPages}};
}
