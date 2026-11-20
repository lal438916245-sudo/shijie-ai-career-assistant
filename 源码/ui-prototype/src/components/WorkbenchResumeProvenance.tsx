import {Sparkles,FileCheck2} from 'lucide-react'

export default function WorkbenchResumeProvenance({report}:{report:any}){
 const real=report.model_application?.simulated===false
 const personal=Boolean(report.personal_input_profile)&&!real
 const origin=report.result_provenance
 return <section className={'wbd-provenance '+(real?'is-real':'is-fixed')} aria-label="本份简历结果来源">
  <div className="wbd-origin-heading">{real?<Sparkles size={18}/>:<FileCheck2 size={18}/>}<strong>{real?'真实模型结果 · 已核对采用':personal?'个人资料 · 本地建议':'固定演示建议'}</strong></div>
  <p>{real?'本份修改由真实模型生成，已逐条核对并保存为正式简历版本。':personal?(report.model_application?'本次修改来自已核对采用的SDK本地替身，未调用真实模型；仍需本人核实原文与证据。':'基于用户自己的简历和本会话记录整理，不调用模型；当前仅提供排版与补证建议。'):'本份建议为人工编写的固定示例，用于体验原文对照和证据流程。'}</p>
  {real&&origin&&<div className="wbd-origin-facts"><span>{origin.provider} · {origin.model}</span><span>{new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',dateStyle:'short',timeStyle:'short'}).format(new Date(origin.generated_at))} 北京时间</span><span>历史调用 {origin.requests} 次 · {origin.usage.total_tokens.toLocaleString('zh-CN')} tokens</span><span>平台费用核对：小于 0.01 元，未提供精确值</span></div>}
  <div className="wbd-evidence-origin"><span>简历修改：<strong>{real?'真实模型生成':personal?'本地规则整理':'固定演示'}</strong></span><span>原简历、学习成果、考核、复测与面试：<strong>{personal?'用户原文与作答；参考练习和评分为本地替身':'固定虚构演示'}</strong></span></div>
  <p className="wb-muted">{real?'真实生成不代表上游记录来自真实学习，也不证明生产经验；使用前仍需本人核实。':'固定成绩不代表真实学习成效。'} 查看、切换、复制和定位来源均不调用模型。</p>
  {real&&origin?.missing_evidence?.length>0&&<details><summary>仍需补充的材料（{origin.missing_evidence.length}项）</summary><ul>{origin.missing_evidence.map((text:string)=><li key={text}>{text}</li>)}</ul><p>这些材料仍待补充，生成结果不代表材料已经提交。</p></details>}
  {real&&origin&&<details><summary>查看本次调用用量与保留边界</summary><p>输入 {origin.usage.prompt_tokens.toLocaleString('zh-CN')}、输出 {origin.usage.completion_tokens.toLocaleString('zh-CN')} tokens；正常结束，无截断。原简历和旧建议均保留。</p><p>思考模式关闭，输出上限 {origin.max_output_tokens.toLocaleString('zh-CN')} tokens。历史费用保守估算 {origin.peak_estimate_cny} 元，与平台核对的实付范围分别记录。</p></details>}
 </section>
}
