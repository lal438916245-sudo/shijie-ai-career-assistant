"""Task execution status is separate from generated plans, grading and mastery."""
import json
import sqlite3

STATUSES={'not_started','in_progress','completed','deferred'}


class ProgressConflict(ValueError):pass


def read_progress(conn,task_ids):
    result={tid:{'status':'not_started','reason':'','revision':0} for tid in task_ids}
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='learning_task_progress'").fetchone():return result
    for tid,status,reason,revision in conn.execute('SELECT task_id,status,reason,revision FROM learning_task_progress'):
        if tid in result:result[tid]={'status':status,'reason':reason,'revision':revision}
    return result


def update_progress(conn,plan_id,task_id,status,reason,revision):
    if type(task_id) is not int or task_id<1 or not isinstance(status,str) or status not in STATUSES or not isinstance(reason,str) or len(reason)>1000 or type(revision) is not int or revision<0:
        raise ValueError('学习状态参数无效')
    reason=reason.strip()
    if status=='deferred' and not reason:raise ValueError('暂缓学习请填写原因，便于之后恢复')
    try:
        conn.execute('BEGIN IMMEDIATE')
        row=conn.execute('SELECT plan_id FROM study_tasks WHERE id=? AND seq=1 AND task_type IN (?,?,?)',(task_id,'理论学习','实战编码','复习')).fetchone()
        if not row or row[0]!=plan_id:raise ValueError('任务不属于当前会话计划')
        conn.execute('CREATE TABLE IF NOT EXISTS learning_task_progress(task_id INTEGER PRIMARY KEY,status TEXT NOT NULL,reason TEXT NOT NULL,revision INTEGER NOT NULL)')
        current=read_progress(conn,[task_id])[task_id]
        if current['revision']!=revision:raise ProgressConflict('学习状态已变化，请重新读取后再修改')
        conn.execute('INSERT INTO learning_task_progress VALUES(?,?,?,?) ON CONFLICT(task_id) DO UPDATE SET status=excluded.status,reason=excluded.reason,revision=excluded.revision',(task_id,status,reason,revision+1))
        conn.commit()
        return {'status':status,'reason':reason,'revision':revision+1}
    except Exception:
        conn.rollback();raise
