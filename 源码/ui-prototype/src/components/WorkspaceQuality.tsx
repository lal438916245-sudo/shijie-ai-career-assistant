import { Component, createContext, useContext, useEffect, type ReactNode } from "react"
import { ArrowLeft, ArrowRight, ChevronRight, RefreshCw, ShieldCheck, TriangleAlert } from "lucide-react"
import { Button } from "@/components/ui/button"
import { FLOW_STEPS, VIEW_TITLES, type View } from "@/lib/routes.mjs"

export const PendingEditsContext=createContext<(key:string,dirty:boolean)=>void>(()=>{})
export function usePendingEdits(key:string,dirty:boolean) {
  const register=useContext(PendingEditsContext)
  useEffect(()=>{register(key,dirty)},[register,key,dirty])
  useEffect(()=>()=>register(key,false),[register,key])
}
export function WorkflowNav({view,onNavigate}:{view:View;onNavigate:(view:View)=>void}) {
  if(view==="new")return null
  return <nav className="workflow-strip" aria-label="固定演示流程"><span><ShieldCheck size={13}/>演示路径</span><ol>{FLOW_STEPS.map((step,index)=><li key={step.view}><button onClick={()=>onNavigate(step.view)} aria-current={view===step.view?"step":undefined}><b>{index+1}</b>{step.label}</button>{index<FLOW_STEPS.length-1&&<ChevronRight size={11}/>}</li>)}</ol><small>自由浏览 · 不代表学习完成进度</small></nav>
}
export function FlowFooter({view,onNavigate}:{view:View;onNavigate:(view:View)=>void}) {
  const index=FLOW_STEPS.findIndex(step=>step.view===view)
  if(index<0)return null
  const previous=index===0?"overview":FLOW_STEPS[index-1].view
  const next=index===FLOW_STEPS.length-1?"overview":FLOW_STEPS[index+1].view
  return <nav className="flow-footer" aria-label="演示流程前后步骤"><button onClick={()=>onNavigate(previous)}><ArrowLeft size={14}/>{VIEW_TITLES[previous]}</button><span>演示流程 {index+1} / {FLOW_STEPS.length}</span><Button variant="outline" size="sm" onClick={()=>onNavigate(next)}>{index===FLOW_STEPS.length-1?"返回成长概览":`下一步：${VIEW_TITLES[next]}`}<ArrowRight size={14}/></Button></nav>
}
export class PageBoundary extends Component<{children:ReactNode;onHome?:()=>void},{failed:boolean}> {
  state={failed:false}
  static getDerivedStateFromError(){return {failed:true}}
  render(){return this.state.failed?<section className="page-recovery" role="alert"><span><TriangleAlert size={26}/></span><h2>这一页暂时没有打开。</h2><p>可以返回概览继续浏览，或重新载入页面后再试。重新载入会清空尚未保存的练习内容。</p><div><Button variant="outline" onClick={this.props.onHome??(()=>window.location.assign("/#overview"))}><ArrowLeft size={14}/>返回成长概览</Button><Button onClick={()=>window.location.reload()}><RefreshCw size={14}/>重新载入页面</Button></div></section>:this.props.children}
}
