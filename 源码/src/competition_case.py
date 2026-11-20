"""Read-only competition case, resource allowlist and source-boundary contract.

No network, SDK, credentials, grading or persistence is available here.
"""
from copy import deepcopy
from datetime import date
import hashlib
import json
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field

ROOT = Path(__file__).resolve().parents[1]
FILES = ('examples/competition_case/v1/case.json',
         'examples/competition_case/v1/cards/sql-join-grain.json',
         'knowledge_base/curated_resources/v1/catalog.json')
TOPICS = {'sql', 'stream', 'model', 'engineering'}
LEGACY_SCENARIO = 'career-pilot-learning-journey-03'
PUBLISHER_HOSTS = {'www.postgresql.org', 'nightlies.apache.org', 'www.kimballgroup.com',
                   'learn.microsoft.com', 'docs.python.org'}


class CaseContractError(ValueError):
    pass


def require(value, code):
    if not value:
        raise CaseContractError(code)


def unique(items, key):
    require(isinstance(items, list), 'invalid_collection')
    result = {}
    for item in items:
        value = item.get(key) if isinstance(item, dict) else None
        require(isinstance(value, str) and bool(value.strip()) and value not in result, 'duplicate_or_missing_identity')
        result[value] = item
    return result


def validate_catalog(catalog):
    require(catalog['catalog_version'] == 'curated-resources-v1', 'catalog_version')
    require(catalog['source_kind'] == 'external_reference' and catalog['evidence_use'] == 'reference_only', 'resource_is_not_ability_evidence')
    resources = unique(catalog['resources'], 'resource_id')
    require(8 <= len(resources) <= 24, 'catalog_scope')
    urls = set()
    for resource in resources.values():
        parsed = urlsplit(resource['url'])
        require(parsed.scheme == 'https' and parsed.hostname in PUBLISHER_HOSTS and
                not parsed.username and not parsed.password and parsed.port is None, 'resource_url_not_allowed')
        require(resource['url'] not in urls, 'duplicate_resource_page')
        urls.add(resource['url'])
        require(resource['topic_ids'] and set(resource['topic_ids']) <= TOPICS, 'unknown_resource_topic')
        require(resource['starting_level'] in ('topic_beginner', 'foundation'), 'resource_level')
        require(type(resource['estimated_read_minutes']) is int and 1 <= resource['estimated_read_minutes'] <= 30, 'resource_time')
        for field in ('title', 'publisher', 'prerequisites', 'language', 'version_scope', 'section',
                      'read_scope', 'learning_goal', 'use_boundary', 'estimate_basis'):
            require(isinstance(resource[field], str) and resource[field].strip(), 'missing_resource_metadata')
        review = resource['verification']
        require(review['status'] in ('verified', 'withdrawn', 'needs_recheck'), 'resource_verification')
        require(review['method'] == 'manual_web_content_review' and review['checked_content'].strip(), 'resource_review_detail')
        require(date.fromisoformat(review['checked_on']) <= date.fromisoformat(review['review_due_on']), 'resource_review_dates')
        require(resource['evidence_use'] == 'reference_only', 'resource_is_not_ability_evidence')
    require({t for r in resources.values() for t in r['topic_ids']} == TOPICS, 'resource_topic_coverage')
    return resources


def resolve_selection(catalog, selection, topic_ids, *, as_of=None):
    """Resolve one primary/one backup ID; never accept a generated URL or browse.

    A backup is a labeled companion, not a claim of equivalent coverage. A stale
    or withdrawn primary is not silently swapped; the local card stays usable.
    """
    resources = validate_catalog(catalog)
    require(isinstance(selection, dict) and set(selection) <= {'primary_id', 'backup_id'}, 'selection_accepts_ids_only')
    require(topic_ids and set(topic_ids) <= TOPICS, 'selection_topic')
    selected = [selection[k] for k in ('primary_id', 'backup_id') if selection.get(k) is not None]
    require(all(isinstance(rid, str) and rid in resources for rid in selected), 'unknown_resource_id')
    require(len(selected) == len(set(selected)), 'duplicate_selection')
    today = as_of or date.today()
    output = {'primary': None, 'backup': None, 'state': 'no_verified_match',
              'fallback': '暂无可用的已核对推荐；继续使用本卡中文引导和固定例子，不自动联网或生成链接。',
              'evidence_use': 'reference_only'}
    for key in ('primary_id', 'backup_id'):
        rid = selection.get(key)
        if rid is None:
            continue
        resource = resources[rid]
        require(set(resource['topic_ids']) & set(topic_ids), 'resource_topic_mismatch')
        review = resource['verification']
        if review['status'] != 'verified' or not date.fromisoformat(review['checked_on']) <= today <= date.fromisoformat(review['review_due_on']):
            continue
        output['primary' if key == 'primary_id' else 'backup'] = deepcopy(resource)
    if output['primary'] is not None:
        output['state'] = 'verified_primary'
    return output


def validate_package(package):
    try:
        return _validate_package(package)
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        if isinstance(exc, CaseContractError):
            raise
        raise CaseContractError('malformed_competition_package') from None


def _validate_package(package):
    case, card, catalog = package['case'], package['card'], package['catalog']
    require(case['contract_version'] == 'competition-case-v1' and (case['case_id'],case['version']) in {('competition-data-01',1),('career-pilot-showcase-20261107',2)}, 'case_identity')
    require(case['source_kind'] == 'curated_demo' and case['run_mode'] == 'demo' and case['evidence_use'] == 'presentation_only', 'case_source')
    topics = unique(case['topics'], 'topic_id')
    require(set(topics) == TOPICS, 'case_topic_coverage')
    require(len({t['gap_template_id'] for t in topics.values()}) == 4, 'gap_template_identity')
    tasks = unique(case['learning_tasks'], 'task_template_id')
    require(len(tasks) == 10 and len({t['day'] for t in tasks.values()}) == len(tasks), 'case_learning_tasks')
    resources = validate_catalog(catalog)
    gap_ids = {t['gap_template_id'] for t in topics.values()}
    for task in tasks.values():
        require(task['topic_ids'] and set(task['topic_ids']) <= topics.keys() and
                set(task['gap_template_ids']) == {topics[t]['gap_template_id'] for t in task['topic_ids']}, 'task_topic_or_gap')
        require(1 <= task['day'] <= 14 and 1 <= len(task['resource_ids']) <= 2 and
                len(set(task['resource_ids'])) == len(task['resource_ids']) and set(task['resource_ids']) <= resources.keys(), 'task_resources')
        require(all(set(resources[r]['topic_ids']) & set(task['topic_ids']) for r in task['resource_ids']), 'task_resource_topic')
    non_learning = [r['day'] for r in case['non_learning_days']]
    learning_days = {t['day'] for t in tasks.values()}
    require(len(non_learning) == len(set(non_learning)) and not learning_days & set(non_learning)
            and learning_days | set(non_learning) == set(range(1, 15)), 'schedule_scope')
    require([r['agent'] for r in case['agent_flow']] == ['A', 'B', 'F', 'C', 'E', 'D'], 'agent_runtime_order')
    require(case['deferred_scope']['counts_as_mastered'] is False, 'deferred_is_not_mastery')
    require(case['reuse_contract']['new_fifth_mode'] is False, 'no_extra_mode')
    require(card['card_version'] == 'beginner-card-v1' and card['card_id'] == 'CP-CARD-SQL-01' and
            card['case_id'] == case['case_id'] and card['task_template_id'] in tasks, 'card_identity')
    require(card['source_kind'] == 'curated_demo' and card['evidence_use'] == 'learning_content_only', 'card_is_not_assessment')
    require(card['basis']['jd_quote'] in case['position']['jd_text'], 'card_jd_quote')
    require(card['basis']['gap_template_id'] in gap_ids, 'card_gap_source')
    require(set(card['topic_ids']) <= TOPICS, 'card_topics')
    budget = card['budget']
    require(all(type(budget[k]) is int and budget[k] > 0 for k in
                ('learning_minutes', 'core_minutes', 'review_minutes', 'optional_minutes', 'total_minutes')), 'card_budget_values')
    require(sum(budget[k] for k in ('learning_minutes', 'core_minutes', 'review_minutes', 'optional_minutes')) == budget['total_minutes'] <= case['learning_preferences']['daily_minutes'], 'card_budget_total')
    require(type(budget['reading_minutes_in_learning']) is int and 0 < budget['reading_minutes_in_learning'] <= budget['learning_minutes'], 'reading_time_in_budget')
    require(sum(s['minutes'] for s in card['steps']) == budget['total_minutes'] and
            sum(s['minutes'] for s in card['steps'] if s['phase'] == 'learning') == budget['learning_minutes'], 'card_step_budget')
    for group in (card['worked_example'], card['exercise']):
        for table in ('orders', 'items'):
            require(group[table]['columns'] and group[table]['rows'] and all(len(r) == len(group[table]['columns']) for r in group[table]['rows']), 'card_table')
    require(card['exercise']['reference_answer'] and card['exercise']['hints'] and
            card['exercise']['checkpoints'] and card['fallback'] and card['offline_fallback'], 'card_learning_scaffold')
    # Review dates checked in selection at request time; integrity isn't a
    # promise that an external link will remain reachable.
    resolve_selection(catalog, card['resource_selection'], card['topic_ids'], as_of=date.fromisoformat(catalog['checked_on']))
    require(set(v for v in card['resource_selection'].values() if v) <= set(tasks[card['task_template_id']]['resource_ids']), 'card_task_resource_binding')
    require(all(b['purpose'] == 'learning_content_preview_only' and b['copy_grades'] is False and
                b['target_task_template_id'] in tasks and b['learning_card_id'] == card['card_id']
                for b in case['legacy_template_bindings']), 'legacy_binding_is_not_record_migration')
    return True


def load_package(root=ROOT):
    root = Path(root)
    try:
        manifest = json.loads((root / 'examples/competition_case/v1/manifest.json').read_text(encoding='utf-8'))
        require(manifest['manifest_version'] == 1 and manifest['contract_version'] == 'competition-case-v1' and
                manifest['case_id'] == 'competition-data-01' and set(manifest['files']) == set(FILES), 'manifest_identity')
        documents = []
        for name in FILES:
            raw = (root / name).read_bytes()
            require(hashlib.sha256(raw).hexdigest() == manifest['files'][name], 'manifest_digest_mismatch')
            documents.append(json.loads(raw))
        package = dict(zip(('case', 'card', 'catalog'), documents))
        validate_package(package)
        return package
    except (OSError, KeyError, json.JSONDecodeError) as exc:
        raise CaseContractError('competition_package_unavailable') from None


def preview_for_legacy(scenario_id, task_id, *, package=None, as_of=None):
    if scenario_id != LEGACY_SCENARIO or task_id != 'T03-01':
        return None
    package = load_package() if package is None else package
    validate_package(package)
    case = package['case']
    bindings = [b for b in case['legacy_template_bindings'] if b['source_scenario_id'] == scenario_id and b['source_task_id'] == task_id]
    require(len(bindings) == 1, 'ambiguous_legacy_binding')
    return {'source_kind': 'curated_demo', 'purpose': 'learning_content_preview_only',
        'case_id': case['case_id'], 'case_version': case['version'], 'binding': deepcopy(bindings[0]),
        'card': deepcopy(package['card']),
        'resources': resolve_selection(package['catalog'], package['card']['resource_selection'], package['card']['topic_ids'], as_of=as_of),
        'notice': '统一案例的人工学习内容预览；只复用学习模板，不导入历史成绩，也不评价本次输入。原任务的进度、考核范围和答卷身份保持原样。'}


class SourceEnvelope(BaseModel):
    """Source labels are necessary, not sufficient, for real grading admission."""
    model_config = ConfigDict(extra='forbid', strict=True, str_strip_whitespace=True)
    contract_version: Literal['competition-source-v1'] = 'competition-source-v1'
    record_id: str = Field(min_length=1, max_length=120)
    record_kind: Literal['input','diagnosis','plan','plan_review','learning_card','learning_progress','learning_artifact','assessment','retest','mastery','interview','resume','resource']
    run_mode: Literal['demo','real','shared']
    source_kind: Literal['synthetic_input','curated_demo','fixed_stub_output','user_input','user_progress','real_model_output','deterministic_projection','external_reference','user_review']
    evidence_use: Literal['presentation_only','learning_content_only','learning_progress_only','reference_only','assessment_candidate','derived_mastery','recommendation']
    case_id: str | None = None
    session_id: str | None = None
    trace_id: str | None = None
    plan_id: str | None = None
    execution_receipt_id: str | None = None
    simulated: bool = True


def validate_source(value):
    try:
        row = SourceEnvelope.model_validate(value).model_dump()
    except ValueError:
        raise CaseContractError('source_envelope_schema') from None
    scope = ('case_id', 'session_id', 'trace_id', 'plan_id')
    if row['record_kind'] == 'resource':
        require(row['run_mode'] == 'shared' and row['source_kind'] == 'external_reference' and
                row['evidence_use'] == 'reference_only' and all(row[k] is None for k in scope), 'resource_reference_scope')
        return row
    require(all(isinstance(row[k], str) and row[k] for k in scope) and row['run_mode'] != 'shared', 'record_scope_required')
    allowed_uses = {
        'input': {'presentation_only','recommendation'},
        'diagnosis': {'presentation_only','recommendation'},
        'plan': {'presentation_only','recommendation'},
        'plan_review': {'presentation_only','recommendation'},
        'learning_card': {'learning_content_only'},
        'learning_artifact': {'learning_content_only'},
        'learning_progress': {'learning_progress_only'},
        'assessment': {'presentation_only','assessment_candidate'},
        'retest': {'presentation_only','assessment_candidate'},
        'mastery': {'derived_mastery'},
        'interview': {'presentation_only','recommendation'},
        'resume': {'presentation_only','recommendation'},
    }
    require(row['evidence_use'] in allowed_uses[row['record_kind']], 'record_evidence_use')
    require(row['source_kind'] != 'external_reference', 'external_reference_must_be_resource')
    if row['source_kind'] in ('user_input','synthetic_input'):
        require(row['record_kind'] == 'input', 'input_source_is_not_generated_result')
    if row['source_kind'] == 'user_review':
        require(row['record_kind'] in ('diagnosis','plan','plan_review','assessment','retest','interview','resume') and row['run_mode']=='demo' and row['simulated'] is True and row['evidence_use']=='presentation_only', 'review_does_not_promote_synthetic_session')
    if row['source_kind'] == 'user_progress':
        require(row['record_kind'] == 'learning_progress', 'progress_source_is_not_assessment')
    if row['source_kind'] == 'deterministic_projection':
        require(row['record_kind'] == 'mastery', 'projection_is_not_model_recommendation')
    if row['source_kind'] in ('synthetic_input','curated_demo','fixed_stub_output'):
        require(row['run_mode'] == 'demo' and row['simulated'] is True and
                row['evidence_use'] in ('presentation_only','learning_content_only'), 'synthetic_cannot_be_real_evidence')
    if row['run_mode'] == 'real':
        require(row['simulated'] is False, 'real_record_cannot_be_simulated')
    if row['source_kind'] == 'real_model_output':
        require(row['run_mode'] == 'real' and row['simulated'] is False and
                bool(row['execution_receipt_id']), 'model_output_needs_real_receipt')
    if row['record_kind'] == 'learning_progress':
        require(row['source_kind'] == 'user_progress' and row['evidence_use'] == 'learning_progress_only', 'learning_is_not_grading')
    if row['evidence_use'] == 'assessment_candidate':
        require(row['run_mode'] == 'real' and row['record_kind'] in ('assessment','retest') and
                row['source_kind'] == 'real_model_output', 'only_scored_answers_are_candidates')
    if row['record_kind'] in ('diagnosis','interview','resume','resource'):
        require(row['evidence_use'] not in ('assessment_candidate','derived_mastery'), 'record_cannot_directly_raise_mastery')
    if row['record_kind'] == 'mastery':
        require(row['source_kind'] == 'deterministic_projection' and row['evidence_use'] == 'derived_mastery', 'mastery_must_be_projection')
    return row


def validate_handoff(child, parents):
    child = validate_source(child)
    parents = [validate_source(p) for p in parents]
    require(len({p['record_id'] for p in parents}) == len(parents) and child['record_id'] not in {p['record_id'] for p in parents}, 'handoff_identity')
    for parent in parents:
        if parent['record_kind'] == 'resource':
            require(child['record_kind'] in ('plan','plan_review','learning_card'), 'reference_is_not_scoring_evidence')
        else:
            require(all(parent[k] == child[k] for k in ('case_id','session_id','trace_id','plan_id','run_mode')), 'cross_scope_or_mode_handoff')
    if child['record_kind'] == 'mastery':
        if child['run_mode'] == 'real':
            require(parents and all(p['evidence_use'] == 'assessment_candidate' for p in parents), 'mastery_needs_scored_answer_references')
        else:
            require(parents and all(p['record_kind'] in ('assessment','retest') and p['evidence_use'] == 'presentation_only'
                                   for p in parents), 'demo_mastery_needs_demo_answer_references')
    # These guards do not replace the grading/rubric/fingerprint/commit sequence
    # checks in the existing mastery service. No score is computed or written.
    return True
