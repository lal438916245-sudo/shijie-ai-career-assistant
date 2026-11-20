import { Card } from "@/components/ui/card"

type Kind="day"|"week"|"retest"|"interview"
const policies:Record<Kind,{title:string;now:string;basis:string;future:string}>={
 day:{title:"每日考核",now:"新开的固定样例每份 2 题；同一天有多个任务时，可分别选择对应样例。旧答卷保留原题量。",basis:"先按当前已保存的学习日期查找任务，再展示与所选任务关联的预设题。题目并非根据学习状态或笔记生成。",future:"建议每次 2～3 题，覆盖当天学习目标和关键知识点；具体题量可随任务量调整。"},
 week:{title:"每周考核",now:"新开的固定周考核每份 3 题，提供两个预设周期；旧答卷保留原题量。",basis:"题目与覆盖任务由预设案例确定；跨专题范围可能与调整后的本周安排不同。",future:"建议每次 3～5 题，围绕实际学习范围、重点和已记录的薄弱点设计综合应用题。"},
 retest:{title:"专题复测",now:"每次展示 1 题，作答后由你选择继续或结束；SQL 与工程测试新样例各 3 题；旧答卷保留原题量。",basis:"题目对应选定专题及预存合成历史中的薄弱分项；不会根据你刚刚的作答或学习笔记改变。",future:"建议逐题生成并反馈，下一题参考此前答题与补学证据；题量上限及用户选择规则仍需后续实现和验证。"},
 interview:{title:"岗位模拟面试",now:"本案例预设 5 个面试官问题，逐题对话；整场结束后开放参考表达，可提前结束。问题中可能包含预设追问，并非 5 个独立主问题。",basis:"人工编排的问题围绕数据开发岗位，覆盖 SQL、实时计算、建模和工程测试；不根据当前回答生成追问。",future:"建议以 5 个主问题为默认，按回答需要适度追问，覆盖岗位要求与已有学习证据；真实题量与追问规则尚未接入。"}
}
export default function QuestionPolicy({kind}:{kind:Kind}){const p=policies[kind];return <Card className="multi-card question-policy"><div><span className="micro-label">HOW QUESTIONS WORK · 出题说明</span><h2>{p.title}怎样出题？</h2></div><div className="question-policy-columns"><section><h3>这次演示</h3><p>{p.now}</p></section><section><h3>题目依据</h3><p>{p.basis}</p></section></div><details><summary>查看后续真实功能的建议设计</summary><p>{p.future}</p><p>这是待实现方案，当前不调用模型，不会按此动态出题或评价回答。</p></details></Card>}
