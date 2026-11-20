export default function ModelResultSource({provenance}:{provenance?:any}){
 if(!provenance)return null
 return <section className="wb-result-source" aria-label="模型结果来源"><strong>{provenance.simulated?'本地模拟结果':'真实模型结果'}</strong><details><summary>来源详情</summary><p>{provenance.provider} · {provenance.model}</p><p>单次回执：{provenance.execution_receipt_id}</p><p>来源按原调用保存，采用不再次调用；生成结果仍需核对。</p></details></section>
}
