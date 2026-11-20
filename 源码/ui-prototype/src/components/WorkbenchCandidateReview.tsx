const topics:Record<string,string>={sql:'SQL 与结果口径',model:'建模与数据质量',stream:'实时与恢复',engineering:'工程与测试'}
const confidence:Record<string,string>={high:'较充分',medium:'需留意边界',low:'证据不足，建议人工复核'}

export function WorkbenchCandidateReview({stage,candidate}:{stage:string;candidate:any}){
  if(stage==='c_question')return <section><h4>待采用的新题</h4><p className="wbd-text">{candidate.prompt}</p>
    <p>对应专题：{candidate.topic_keys?.map((key:string)=>topics[key]??key).join('、')}。采用后仍需作答与独立评分，参考解析在提交后开放。</p></section>
  if(stage==='c_grade')return <section><h4>本题评分与证据</h4>
    <p>{candidate.status==='scored'?'分项完整，可核对采用':'评分待复核，不能记作通过或失败'} · 证据置信：{confidence[candidate.confidence]}</p>
    {candidate.topics.map((topic:any)=><section key={topic.topic_key}><h5>{topics[topic.topic_key]??topic.topic_key} · {candidate.server_scores.find((s:any)=>s.topic_key===topic.topic_key)?.score??'待复核'}</h5>
      {topic.dimensions.map((d:any)=><div key={d.key}><p>{d.key==='result'?'结论与结果':'依据与边界'}：{d.score??'待复核'} · {d.rationale}</p>
        {d.evidence.map((ref:any,index:number)=><blockquote className="wbd-text" key={index}>{ref.quote}</blockquote>)}</div>)}</section>)}<p>{candidate.feedback}</p></section>
  if(stage==='e_turn')return <section><h4>待采用的面试问题</h4><p className="wbd-text">{candidate.text}</p>
    <p>{candidate.question_kind==='followup'?'接续上一轮的追问':'岗位主问题'} · 岗位引用：{candidate.requirement_ids.join('、')}。采用后保留原轮数与会话范围。</p></section>
  if(stage==='e_report')return <section><h4>逐轮复盘与原话依据</h4>{candidate.findings.map((f:any,index:number)=><section key={f.answer_turn_id}>
    <h5>第 {index+1} 轮 · {confidence[f.confidence]}</h5><p>{f.observation}</p><p>改进建议：{f.suggestion}</p>
    {f.evidence.map((ref:any,n:number)=><blockquote className="wbd-text" key={n}>{ref.quote}</blockquote>)}</section>)}</section>
  return <section><h4>简历修改对照</h4>
    {['resume-self-report-first-v1','resume-self-report-first-v2'].includes(candidate.revision_contract)&&<p>根据现有资料整理，学习、考核和面试记录可选。请核对每项自述与修改，补充材料清单不阻塞已有经历的整理。</p>}
    {typeof candidate.full_draft_preview==='string'&&<details><summary>完整简历候选预览（尚未保存）</summary>
      <p>预览包含所有未被拦截的建议；正式版本按下方勾选的修改生成。</p><p className="wbd-text">{candidate.full_draft_preview}</p></details>}
    {candidate.items.length===0&&<p>本次没有可采用的修改，保留原稿。可补充本人实际做过的项目与个人贡献，不必先完成学习或考核。</p>}
    {candidate.items.map((item:any,index:number)=><section key={item.item_id}>
    <h5>修改 {index+1} · {item.server_status==='blocked_unsupported_upgrade'?'缺少证据，已拦截':'待本人确认事实'}</h5>
    <p>原文</p><blockquote className="wbd-text">{item.original_ref.quote}</blockquote><p>修改后</p><p className="wbd-text">{item.proposed_text}</p><p>{item.rationale}</p>
    {item.supporting_refs?.map((ref:any,n:number)=><blockquote className="wbd-text" key={n}>课程成果依据：{ref.quote}</blockquote>)}</section>)}
    {candidate.missing_evidence.length>0&&<><h5>仍需补齐的材料</h5><ul>{candidate.missing_evidence.map((s:string,n:number)=><li key={n}>{s}</li>)}</ul></>}</section>
}
