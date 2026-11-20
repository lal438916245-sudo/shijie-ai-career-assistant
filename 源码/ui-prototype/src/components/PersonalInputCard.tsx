import {useEffect,useState} from 'react'
import {Card} from './ui/card'
import {Button} from './ui/button'
import {Textarea} from './ui/textarea'
export type PersonalDraft={target_role:string;resume_text:string;jd_text:string}
export default function PersonalInputCard({busy,startDate,onDate,onCreate,onDirty}:{busy:boolean;startDate:string;onDate:(value:string)=>void;onCreate:(draft:PersonalDraft)=>Promise<any>;onDirty:(dirty:boolean)=>void}){
 const [role,setRole]=useState(''),[resume,setResume]=useState(''),[jd,setJD]=useState(''),[error,setError]=useState('')
 useEffect(()=>{onDirty(Boolean(resume.trim()||jd.trim()))},[resume,jd,role,onDirty])
 const save=async()=>{if(busy)return;setError('');if(!role.trim()||resume.trim().length<20||jd.trim().length<20){setError('请填写岗位名称，以及至少20字的简历/概况和JD。');return}
  try{const result=await onCreate({target_role:role,resume_text:resume,jd_text:jd});if(result)onDirty(false)}catch(e){setError((e as Error).message)}}
 return <Card className="multi-card" aria-label="个人简历与岗位输入"><span className="micro-label">YOUR INPUT · YOUR SESSION</span><h2>填写简历和目标岗位。</h2><p>支持个人概况或完整文本简历。先完成岗位诊断，再核对优化简历。</p>
 <p className="wb-call-note">资料将用于AI分析，请使用真实经历并移除不必要的敏感信息。</p>
 <div className="wb-date-grid"><label>目标岗位<input type="text" maxLength={120} value={role} placeholder="例如：数据开发、游戏客户端开发、Agent工程" disabled={busy} onChange={e=>setRole(e.target.value)}/></label><label>准备日期<input type="date" value={startDate} disabled={busy} onChange={e=>onDate(e.target.value)}/></label></div>
 <div className="wb-input-grid"><label>我的简历／个人概况<Textarea value={resume} maxLength={60000} disabled={busy} onChange={e=>setResume(e.target.value)} placeholder="粘贴你实际已有的技能、教育、项目和个人贡献。没有做过的内容不用补造。"/></label><label>目标岗位JD<Textarea value={jd} maxLength={30000} disabled={busy} onChange={e=>setJD(e.target.value)} placeholder="粘贴岗位职责、任职要求与加分项，尽量保留原分段。"/></label></div>
 <details className="wb-binding-details"><summary>资料保存说明</summary><p>原文保存后不覆盖，修改资料请新建求职准备。学习计划与成长的完整流程可在案例入口查看。</p></details>
 {error&&<p role="alert" className="multi-error">{error}</p>}
 <Button disabled={busy||!startDate} onClick={save}>保存资料，进入求职准备</Button>
 </Card>
}
