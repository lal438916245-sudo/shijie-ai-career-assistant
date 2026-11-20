import {Button} from './ui/button'

export function LearningArtifactView({artifact}:{artifact:any}){
  const tables=artifact.exercise.tables??[
    {title:'练习订单表',...artifact.exercise.orders},{title:'练习明细表',...artifact.exercise.items},
  ]
  return <section className="wb-artifact-view">
    <p className="wb-chip">课程小样本 · 固定演示</p>
    <h3>{artifact.title}</h3>
    <p>{artifact.summary}</p>
    <details><summary>核对练习输入与参考结果</summary>
      <p>{artifact.exercise.prompt}</p>
      {tables.map((table:any)=><div className="wb-artifact-table" key={table.title}>
        <h4>{table.title}</h4><table><thead><tr>{table.columns.map((name:string)=><th key={name}>{name}</th>)}</tr></thead>
          <tbody>{table.rows.map((row:any[],index:number)=><tr key={index}>{row.map((cell:any,column:number)=><td key={column}>{String(cell)}</td>)}</tr>)}</tbody>
        </table></div>)}
      <p>{artifact.exercise.reference_answer}</p>
      <ul>{artifact.exercise.checkpoints.map((point:string)=><li key={point}>{point}</li>)}</ul>
    </details>
    <p className="wb-muted">{artifact.notice}</p>
  </section>
}

export function ResumeLearningHandoff({handoff,onSource,onLearnTask,sources=[]}:{
  handoff:any;sources?:any[];onSource?:(id:string)=>void;onLearnTask?:(id:string)=>void
}){
  if(!handoff)return null
  const personal=handoff.result_origin==='personal_local'
  return <section className="wb-learning-handoff" aria-label="学习到简历的证据">
    <h3>从学习计划到简历，这些变化有据可查。</h3>
    <div className="wbd-counts">
      <span className="wb-chip">已完成 {handoff.completed_tasks}/{handoff.total_tasks} 项任务</span>
      <span className="wb-chip">已保存 {handoff.artifact_tasks} 项练习成果</span>
      <span className="wb-chip">{personal?'本地流程记录齐备':'可形成课程表述'} {handoff.ready_tasks} 项</span>
    </div>
    <p className="wb-muted">{handoff.notice}</p>
    {handoff.tasks.map((task:any)=><details className="wb-handoff-task" key={task.task_id}>
      <summary>{task.title} · {task.ready?(personal?'记录齐备，实际成果待核验':'已形成课程练习表述'):'待补齐证据'}</summary>
      {task.ready?<p>{task.artifact_summary}</p>:<ul>{task.blockers.map((reason:string)=><li key={reason}>{reason}</li>)}</ul>}
      <div className="multi-actions">
        {onLearnTask&&<Button variant="outline" size="sm" onClick={()=>onLearnTask(task.task_id)}>打开对应学习任务</Button>}
        {onSource&&task.source_ids.map((id:string)=><Button variant="outline" size="sm" key={id} onClick={()=>onSource(id)}>
          查看{({learning_progress:'完成记录',learning_artifact:'练习成果',assessment:'日周考核答卷',retest:'专题复测答卷'} as Record<string,string>)[sources.find(source=>source.record_id===id)?.kind]??'关联记录'}
        </Button>)}
        {onSource&&task.interview_ids.map((id:string)=><Button variant="outline" size="sm" key={id} onClick={()=>onSource(id)}>回看岗位面试反馈</Button>)}
      </div>
    </details>)}
  </section>
}
