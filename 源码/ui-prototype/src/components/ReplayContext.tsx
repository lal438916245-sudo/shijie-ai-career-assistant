import { ArrowUpRight, FileSearch, Fingerprint, ShieldCheck } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog"
import { replay } from "@/data/demo"

export function ReplaySource({ compact = false }: { compact?: boolean }) {
  return <Dialog><DialogTrigger asChild><Button variant="ghost" size="sm" className={compact ? "replay-source compact" : "replay-source"}><FileSearch size={14} /> 查看样例来源 <ArrowUpRight size={12} /></Button></DialogTrigger><DialogContent className="replay-source-dialog"><DialogHeader><span className="dialog-hero-icon"><Fingerprint size={23} /></span><DialogTitle>每一项结论，都有来源。</DialogTitle><DialogDescription>{replay.meta.disclosure.note}</DialogDescription></DialogHeader><div className="source-input"><strong>经历摘要</strong><p>{replay.inputs.resume_summary}</p><strong>岗位要求摘要</strong><p>{replay.inputs.jd_summary}</p></div><dl className="source-identities">{[["输入标识", replay.inputs.source_id], ["资料包", replay.inputs.bundle_id], ["诊断报告", replay.trace.report_id], ["学习计划", replay.trace.plan_id], ["关联轨迹", replay.trace.trace_id]].map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl><p className="source-footnote">这是 {replay.meta.generated_at.slice(0, 10)} 的人工整理快照。本页只读取本地文件，不执行诊断、生成计划、出题、阅卷或模型调用。</p></DialogContent></Dialog>
}

export function ReplayBanner() {
  return <div className="replay-banner"><div><Badge variant="secondary" className="demo-badge">固定演示样例</Badge><span>{replay.inputs.target_role}</span></div><ReplaySource /><p><ShieldCheck size={13} /> 当前内容来自演示快照，与首次输入页保存的资料分开。</p></div>
}

export function ReplayFooter() {
  return <footer className="page-footer"><span>CAREER-PILOT <i /> 让努力留下证据</span><span>人工整理的固定演示 · 本轮无模型调用</span></footer>
}
