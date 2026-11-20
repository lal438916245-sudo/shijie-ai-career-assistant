"""Validated, additive teaching content for published workbench tasks."""
import json

from competition_case import CaseContractError, ROOT, require, unique, validate_catalog

PATH = 'examples/competition_case/v1/cards/follow-along-v1.json'
VERSION = 'follow-along-card-v1'


def _strings(values, minimum=1):
    return isinstance(values, list) and len(values) >= minimum and all(
        isinstance(value, str) and value.strip() for value in values
    )


def _text(item, *fields):
    require(all(isinstance(item.get(key), str) and item[key].strip() for key in fields), 'follow_along_text')


def _tables(tables):
    by_title = unique(tables, 'title')
    require(bool(by_title), 'follow_along_table')
    for table in by_title.values():
        cols = table['columns']
        require(_strings(cols) and len(cols) == len(set(cols)) and bool(table['rows']) and
                all(isinstance(row, list) and len(row) == len(cols) and all(
                    type(cell) in (str, int) for cell in row) for row in table['rows']), 'follow_along_table')


def load_follow_along_cards(package, root=ROOT):
    case = package['case']
    if package.get('personal_input'):
        from personal_workbench_input import personal_cards
        return personal_cards(package,root)
    try:
        pack = json.loads((root / ('examples/competition_case/v2/cards/follow-along-v1.json' if case['case_id']=='career-pilot-showcase-20261107' else PATH)).read_text(encoding='utf-8'))
        require(pack['version'] == VERSION and pack['case_id'] == case['case_id'] and
                pack['case_version'] == case['version'], 'follow_along_identity')
        cards = unique(pack['cards'], 'task_template_id')
        templates = {t['task_template_id']: t for t in case['learning_tasks'] if t['task_template_id'] != 'CP-T01'}
        require(cards.keys() == templates.keys() and len(unique(pack['cards'], 'card_id')) == len(cards), 'follow_along_coverage')
        catalog = validate_catalog(package['catalog'])
        for task_id, card in cards.items():
            template = templates[task_id]
            require(card['card_version'] == VERSION and card['title'] == template['title'] and
                    card['topic_ids'] == template['topic_ids'] and card['resource_ids'] == template['resource_ids'] and
                    card['source_kind'] == 'curated_demo' and card['evidence_use'] == 'learning_content_only',
                    'follow_along_binding')
            _text(card, 'subtitle', 'prerequisites', 'fallback')
            _text(card['basis'], 'jd_quote', 'reason')
            require(card['basis']['jd_quote'] in case['position']['jd_text'], 'follow_along_jd')
            concepts = unique(card['concepts'], 'term')
            require(len(concepts) >= 3 and _strings(card['objectives'], 2) and _strings(card['reading_questions'], 2),
                    'follow_along_concepts')
            for concept in concepts.values():
                _text(concept, 'text')
            example = card['worked_example']
            _text(example, 'intro')
            require(_strings(example['explanation'], 3), 'follow_along_example')
            _tables(example['tables'])
            exercise = card['exercise']
            _text(exercise, 'prompt', 'deliverable', 'reference_answer')
            _tables(exercise['tables'])
            require(_strings(exercise['hints'], 2) and _strings(exercise['checkpoints'], 3), 'follow_along_exercise')
            _text(card['optional'], 'prompt', 'answer', 'deliverable')
            require(all(catalog[r]['estimated_read_minutes'] <= 20 for r in card['resource_ids']), 'follow_along_reading_budget')
        return cards
    except (OSError, KeyError, TypeError, ValueError, AttributeError) as exc:
        if isinstance(exc, CaseContractError):
            raise
        raise CaseContractError('follow_along_unavailable') from None


def follow_along_card(package, task):
    card = load_follow_along_cards(package)[task['task_template_id']]
    require(task['topic_keys'] == card['topic_ids'] and
            [task['resource_selection'][k] for k in ('primary_id', 'backup_id') if task['resource_selection'].get(k)] ==
            card['resource_ids'], 'follow_along_task_binding')
    budget = task['budget']
    learning, core, review, optional = (budget[k] for k in ('learning_minutes','core_minutes','review_minutes','optional_minutes'))
    total = learning + core + review + optional
    require(all(type(value) is int and value > 0 for value in (learning, core, review, optional)) and
            total <= package['case']['learning_preferences']['daily_minutes'] and budget['ending_policy'] == 'choose_one',
            'follow_along_task_budget')
    return {**card,
        'authorship':'Career-Pilot 人工编写的中文讲解、样本和练习。',
        'resource_slot_policy':'主资料和备选在同一阅读时段二选一。遇到陌生术语，先读本卡中文概念。',
        'offline_fallback':'直接按本卡表格和步骤手算，再用参考答案核对。',
        'assessment_boundary':'这是学习练习。正式日周考核与专题复测在独立入口保存答卷。',
        'completion_check':'完成必做和自查后，可在下方保存学习进度。选做由你决定。',
        'budget':{'total_minutes':total,'learning_minutes':learning,'core_minutes':core,'review_minutes':review,
                  'optional_minutes':optional,'notice':f'资料阅读计入学习时间。若安排日考核，最后 {optional} 分钟与选做二选一。'},
        'steps':[
            {'title':'看概念、按表跟做','minutes':learning,'instruction':'先读中文概念，按步骤复算样本；需要时选一份资料核对。'},
            {'title':'换一组数据独立练','minutes':core,'instruction':'先写出结果和依据，再按需查看提示。'},
            {'title':'对照参考、自查','minutes':review,'instruction':'核对答案、边界和遗漏，写下一个自己还想验证的点。'},
            {'title':'有余力再选做','minutes':optional,'instruction':'试一条边界变体，或把这一时段留给日考核。'},
        ]}
