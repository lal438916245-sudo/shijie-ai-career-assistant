import {CircleCheck,FlaskConical,Layers3,LoaderCircle} from 'lucide-react'

export type ExperienceMode='case'|'local'|'real'|'pending'|'loading'|'unavailable'
export function modeForSession({entryMode,loading=false,failed=false,data}:{entryMode:'demo'|'personal';loading?:boolean;failed?:boolean;data?:any}):ExperienceMode{
 if(entryMode==='demo')return 'case'
 if(loading)return 'loading'
 if(failed)return 'unavailable'
 const runtime=data?.session_runtime
 if(runtime?.execution_mode==='local_sdk_rehearsal')return 'local'
 if(runtime?.execution_mode==='real_model')return runtime.simulated===true?'local':runtime.simulated===false?'real':'unavailable'
 // Explicit legacy local adapters are simulations; configuration readiness alone
 // must never be mistaken for an active, authorized real-model session.
 if(data?.personal_input&&data?.abf&&!runtime)return 'local'
 return 'pending'
}
const copy:Record<ExperienceMode,{label:string;hint:string}>={
 case:{label:'案例回放',hint:'只读查看，不调用模型；历史结果各自保留来源。'},
 local:{label:'本地模拟',hint:'固定替身返回，实际模型费用0元；不代表针对性智能分析。'},
 real:{label:'真实模型',hint:'点击生成后处理本次资料，结果保存在当前准备中。'},
 pending:{label:'尚未生成',hint:'资料保存后，点击生成才会发送给AI服务。'},
 loading:{label:'模式读取中',hint:'正在核对当前会话，尚未确认其运行模式。'},
 unavailable:{label:'模式未确认',hint:'会话未能读取，请先恢复；不推断为本地或真实模式。'},
}
export function ExperienceModeBadge({mode}:{mode:ExperienceMode}){
 const item=copy[mode],Icon=mode==='real'?CircleCheck:mode==='case'?Layers3:mode==='loading'?LoaderCircle:FlaskConical
 return <span className={'prototype-pill experience-mode mode-'+mode} role="status" aria-live="polite" aria-atomic="true" aria-label={'当前模式：'+item.label} title={item.hint}>
  <Icon size={14} aria-hidden="true"/><strong>{item.label}</strong>
  {(mode==='case'||mode==='local')&&<span className="experience-mode-detail"> · {mode==='case'?'不调用模型':'费用0元'}</span>}
 </span>
}
