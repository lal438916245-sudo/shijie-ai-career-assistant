"""Deterministic personal-input D rehearsal; never infer facts from fixed scores."""
import re
from copy import deepcopy
from workbench_learning_evidence import learning_handoff

VERSION = 'personal-resume-local-v1'


def make_personal_report(snapshot):
    original = snapshot['resume_text']
    sources = deepcopy(snapshot['sources'])
    base = next(s['record_id'] for s in sources if s['kind'] == 'input')
    diagnosis = next(s for s in sources if s['kind'] == 'diagnosis')
    items = []
    # Only whitespace/list layout changes. Keep every original character in order;
    # do not invent a name, proficiency, achievement, role or verified outcome.
    for match in re.finditer(r'[^\r\n]+', original):
        line = match.group()
        if len(line) < 25 or line.lstrip().startswith('#'):
            continue
        indent = '  ' if line.lstrip().startswith(('-', '*', '•')) else ''
        rewritten = re.sub(r'([；。])(?=\S)', r'\1\n' + indent, line)
        if rewritten == line:
            continue
        items.append({
            'item_id': f'personal-layout-{match.start()}', 'status': 'suggested',
            'title': '拆分已有经历，保留全部原文事实',
            'original_quote': line,
            'original_ref': {'start': match.start(), 'end': match.end(), 'quote': line},
            'suggested_text': rewritten, 'change_kind': 'layout_only',
            'reason': '仅在原有句号或分号后换行，方便阅读；未删减否定、待核验或课程练习等边界，也未新增事实。',
            'source_ids': [base], 'evidence_level': '用户简历自述 / 未经独立核验',
            'next_action': '逐字核对原文与改后内容；事实性改写仍需模型候选和本人核对。',
        })
        if len(items) == 5:
            break

    def supplement(sid, title, reason, action, level, quote='', extra=None):
        items.append({'item_id': 'personal-evidence-' + sid, 'status': 'supplement',
            'title': title, 'original_quote': quote, 'suggested_text': '',
            'reason': reason, 'next_action': action, 'evidence_level': level,
            'source_ids': list(dict.fromkeys([sid, *(extra or [])]))})

    rows = diagnosis['view'].get('requirements', [])
    pending = [r for r in rows if r.get('evidence_status') in ('not_provided', 'partial', 'explicit_absence')]
    supplement(diagnosis['record_id'], '按本次岗位诊断补齐可核对材料',
        f'本会话诊断有 {len(pending)} 项待补证要求。当前 A 为本地替身判断，未提供不等于不会；不能据此自动删除或新增个人技能。',
        '逐项核对下方诊断原记录中的 JD 原文，补充本人实际做过的动作、代码或作品，以及输入、预期与实际结果。',
        '本会话诊断 / 本地替身', extra=[base])
    for source in sources:
        rid, kind, view = source['record_id'], source['kind'], source['view']
        if kind == 'learning_progress':
            supplement(rid, '学习进度与真实成果分开核对',
                f"本任务保存状态为 {view['status']}；进度勾选不证明已掌握。",
                '补充本人练习文件和可复现步骤；尚未完成的内容不写成成果。', '用户进度记录')
        elif kind == 'learning_artifact':
            supplement(rid, '参考练习只作为补证线索',
                '已保存的是内置课程小样本及参考结果，不是用户提交且已独立验证的作品。',
                '参照原记录完成自己的练习，提供代码、输入、预期和实际输出后，再核对能否写进简历。',
                '内置参考材料 / fixed_sample')
        elif kind in ('assessment', 'retest'):
            supplement(rid, '根据原始答卷准备实践证据',
                '保存了本人的作答及本地替身反馈；预设分数、通过或复测状态不证明真实能力，不自动生成技能表述。',
                '查看这份答卷的题目和原始回答，将解法做成可复现的小样本；不足之处先补学，勿写成生产经验。',
                '用户答卷 / 本地替身反馈')
        elif kind == 'interview':
            findings = view.get('findings', [])
            # Quote the saved answer, never a fixed model's inferred achievement.
            chosen = next((f for f in findings if f.get('quote')), None)
            supplement(rid, '把面试自述变成待核对的材料清单',
                '只引用已结束面试的原始回答；本地反馈和口头自述均不能证明项目实际发生。',
                '从原始对话核对本人贡献、实现过程和验证边界；补充作品材料后再决定是否纳入简历。',
                '面试自述 / 未经独立核验', chosen['quote'] if chosen else '',
                [chosen['answer_record_id']] if chosen else [])

    report = {
        'contract_version': VERSION, 'result_origin': 'personal_local',
        'personal_input_profile': snapshot['personal_input_profile'],
        'scope': snapshot['scope'], 'input_digest': snapshot['input_digest'],
        'resume_text': original, 'position_title': snapshot['position_title'],
        'snapshot_revision': snapshot['revision'], 'created_at': snapshot['created_at'],
        'notice': '个人资料 · 本地规则建议，未调用模型。保留用户原文，仅提供排版整理和有来源的补证建议；固定评分与参考练习不能自动变成个人成果。',
        'items': items, 'sources': sources,
        'source_counts': {k: sum(s['kind'] == k for s in sources) for k in
            ('input', 'diagnosis', 'learning_progress', 'learning_artifact', 'assessment', 'retest', 'interview')},
        'approved_texts': [i['suggested_text'] for i in items if i['status'] == 'suggested'],
        'resume_has_header': True, 'preview_default_item_ids': [],
        'coverage_notice': '使用生成前冻结的本会话原文和记录；缺失记录明确留空，进行中的面试不纳入。整稿保留原有结构，不套用演示人物模板；没有可安全整理的段落时保留原稿。',
    }
    handoff = learning_handoff(snapshot)
    if handoff is not None:
        handoff['result_origin'] = 'personal_local'
        handoff['factual_verification'] = False
        handoff['notice'] = '这是本地流程记录齐备情况；参考成果与替身评分不证明用户完成了真实实践，不能自动写入个人简历。'
        report['learning_handoff'] = handoff
    return report
