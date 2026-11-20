export type PlanDiagnostics={contract_version:string;summary:string;issue_count:number;issues:{code:string;path:string;message:string;requirement_number?:number;days?:number[];missing_days?:number[];extra_count?:number;missing_count?:number;unknown_count?:number}[]}

function location(path:string){
 const task=path.match(/^phases\[(\d+)\]\.tasks\[(\d+)\]/)
 if(task)return `第${Number(task[1])+1}阶段 · 第${Number(task[2])+1}项任务`
 const phase=path.match(/^phases\[(\d+)\]/)
 if(phase)return `第${Number(phase[1])+1}阶段`
 if(path.includes('source_gap_ids'))return '任务与差距关联'
 if(path.includes('.day'))return '每日安排'
 return ({overall_goal:'计划总体目标',phases:'学习阶段','$':'计划返回内容'} as Record<string,string>)[path]??'计划字段'
}

export default function PlanValidationDetails({details,legacy=false}:{details?:PlanDiagnostics|null;legacy?:boolean}){
 if(!details)return legacy?<p>这份旧回执未记录具体校验规则，无法还原失败原因。</p>:null
 const diagnosis=details.contract_version==='evidence-a-v1'
 const title=diagnosis?'岗位诊断校验明细':'学习计划校验明细'
 return <section className="model-preview-result" aria-label={title}><h4>{title}</h4><p>{details.summary}</p><ul>{details.issues.map((item,index)=><li key={index}><strong>{diagnosis?(item.requirement_number?`第${item.requirement_number}项JD判断`:'诊断证据与岗位层级'):location(item.path)}</strong>：{item.message}{item.days?.length?`；重复天数 ${item.days.join('、')}`:''}{item.missing_days?.length?`；缺少第 ${item.missing_days.join('、')} 天`:''}{item.extra_count?`；超出范围 ${item.extra_count} 项`:''}{item.missing_count?`；缺少 ${item.missing_count} 条来源`:''}{item.unknown_count?`；未知来源 ${item.unknown_count} 条`:''}</li>)}</ul><details><summary>查看具体字段位置</summary><ul>{details.issues.map((item,index)=><li key={index}><code>{item.path}</code> · {item.code}</li>)}</ul></details>{details.issue_count>details.issues.length&&<p>共{details.issue_count}项问题，仅列出前{details.issues.length}项。</p>}<p>{diagnosis?'当前诊断未保存；简历和岗位输入保留。':'当前计划未保存；已完成诊断保留。'}本次请求不会自动重试。</p></section>
}
