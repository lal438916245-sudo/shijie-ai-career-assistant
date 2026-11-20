"""Authored local practice supplements; canonical Replay and history stay intact."""
import json
from pathlib import Path

BANK_PATH=Path(__file__).resolve().parents[1]/'examples/learning_journey_demo/practice_bank_v1.json'

def load_bank(data):
    bank=json.loads(BANK_PATH.read_text(encoding='utf-8'))
    if bank.get('version')!='practice-review-v1' or bank.get('source_kind')!='authored_fixed_demo':
        raise ValueError('固定练习包版本无效')
    tasks={t['task_id']:t for t in data['tasks']}
    originals={q['question_id']:q for q in data['questions']}
    templates={a['assessment_id']:(2 if a['kind']=='day' else 3,{x['task_id'] for x in a['scope_snapshot']['items']}) for a in data['assessments']}
    templates.update({r['retest_session_id']:(3,{q['task_id'] for q in [r['learning_context']]}) for r in data['retests']})
    templates.update({i['interview_id']:(5,None) for i in data['interviews']})
    if set(bank['templates'])!=set(templates):raise ValueError('固定练习范围不完整')
    all_ids=set()
    for key,items in bank['templates'].items():
        count,allowed=templates[key]
        if len(items)!=count:raise ValueError('固定练习题量无效')
        for item in items:
            if not item['id'] or item['id'] in all_ids or not item['text'].strip():raise ValueError('固定练习身份无效')
            all_ids.add(item['id'])
            if not item['topic_ids'] or not set(item['topic_ids'])<={t['topic_id'] for t in data['topics']}:raise ValueError('练习专题无效')
            if allowed is not None:
                if not item['task_ids'] or not set(item['task_ids'])<=allowed:raise ValueError('练习超出学习范围')
                if set(item['topic_ids'])!={topic for task in item['task_ids'] for topic in tasks[task]['topic_ids']}:raise ValueError('练习任务与专题不符')
            if item['id'] in originals:
                q=originals[item['id']]
                if item['text']!=q['text'] or item['topic_ids']!=q['topic_ids']:raise ValueError('历史题目不可改写')
            review=item['review']
            if any(not isinstance(review.get(k),str) or not review[k].strip() for k in ('reference_answer','explanation','notice')):raise ValueError('参考解析缺失')
            if any(not isinstance(review.get(k),list) or not review[k] or any(not isinstance(v,str) or not v.strip() for v in review[k]) for k in ('checkpoints','common_mistakes')):raise ValueError('参考检查点缺失')
            expected=[e for e in data['topic_evidence'] if any(a['attempt_id']==e['attempt_id'] and a['question_id']==item['id'] for a in data['attempts'])]
            if item['sample_evidence']!=expected:raise ValueError('不可伪造案例分项成绩')
    return bank

def legacy_items(data,run):
    """Old runs keep their original IDs/counts; do not add supplements to them."""
    ids=json.loads(run['items_json'])
    bank=load_bank(data)
    by_id={q['id']:q for items in bank['templates'].values() for q in items}
    return [by_id[qid] for qid in ids]
