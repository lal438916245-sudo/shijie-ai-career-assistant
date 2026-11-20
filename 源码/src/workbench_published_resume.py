"""Read-only publication of one audited D result over its exact sealed fictional replay.

No model transport, vault, mutation or arbitrary filesystem path is accepted here.
The original sealed DB and acceptance ledger stay separate and unchanged.
"""
from copy import deepcopy
from pathlib import Path
import hashlib,json
from competition_showcase import PROFILE,REPLAY_TOKEN
from competition_workbench import WorkbenchError,digest
from workbench_candidate_adoption import WorkbenchCandidateAdoption

ASSET=Path(__file__).resolve().parent.parent/'examples/competition_case/v2/results/d-20261110.json'
ASSET_SHA256='7a1d003f851fb1f8ffa7199be2065d491e14eedc1a65476ee7f5759c2a5a636b'

class PublicationUnavailable(ValueError):pass

def require(value):
    if not value:raise PublicationUnavailable('真实D结果或来源暂时无法核对，未展示未核对的内容；固定回放仍可查看。')

def load_publication(service,token,*,asset=ASSET,expected_digest=ASSET_SHA256):
    if service._session_directory(token)!=service.directory:return None
    if service.case_profile!=PROFILE or token!=REPLAY_TOKEN or not (service.directory/'replay-sealed.json').is_file():return None
    try:
        raw=asset.read_bytes();require(len(raw)<2000000 and hashlib.sha256(raw).hexdigest()==expected_digest)
        blob=json.loads(raw);require(blob['version']=='published-d-v1')
        state=service.state(token);base_records=service.records(token)['records']
        require(state['read_only_demo'] and state['scope']==blob['scope'] and state['input_digest']==blob['input_digest'])
        require(state['revision']==blob['base_revision'] and len(base_records)==blob['base_record_count'])
        require(hashlib.sha256(service._identity(token)[2].read_bytes()).hexdigest()==blob['base_database_sha256'])
        formal=blob['resume'];report=formal['report'];provenance=blob['provenance'];delta=blob['records']
        require(formal['scope']==state['scope'] and report['scope']==state['scope'] and report['input_digest']==state['input_digest'])
        require(formal['model_requests']==0 and not formal['real_dispatch_enabled'] and formal['checks']==[])
        require(provenance['candidate_simulated'] is False and provenance['learning_evidence_simulated'] is True
                and provenance['reviewed'] is True and provenance['requests']==1 and provenance['finish_reason']=='stop')
        usage=provenance['usage'];require(usage['prompt_tokens']+usage['completion_tokens']==usage['total_tokens'])
        require(len(delta)==2 and len({r['record_id'] for r in delta})==2)
        app_row=next(r for r in delta if r['payload']['event']=='candidate_adopted');app=app_row['payload']
        report_row=next(r for r in delta if r['payload']['event']=='resume_report')
        require(app['stage']=='d_revision' and app['candidate_simulated'] is False and app['scope']==state['scope'])
        require(app['review_confirmed'] is True and app['candidate_digest']==digest(app['candidate']))
        require(app['target_id']==blob['base_resume_id'] and app['formal_resume_id']==formal['resume_id'])
        require(app['revision']==state['revision']+1 and report['snapshot_revision']==app['revision'])
        require(report_row['record_id']==formal['resume_id']+':report' and report_row['payload']['report']==report)
        require(app_row['record_id']==app['record_id'] and app_row['parent_ids']==[blob['base_resume_id']+':report'])
        require(report_row['parent_ids']==[app['record_id']])
        index={r['record_id']:r for r in [*base_records,*delta]}
        require(len(index)==len(base_records)+2)
        for row in delta:
            require(all(row['envelope'][k]==v for k,v in state['scope'].items()))
            require(all(parent in index and index[parent]['seq']<row['seq'] for parent in row['parent_ids']))
        base=service.resume(token,blob['base_resume_id'])['report']
        require(base['resume_text']==report['resume_text'])
        WorkbenchCandidateAdoption._validate_selection('d_revision',app['candidate'],app['selected_item_ids'])
        require(WorkbenchCandidateAdoption._adopted_resume_report(base,app)==report)
        source_index={s['record_id']:s for s in base['sources']}
        for item in app['candidate']['items']:
            ref=item['original_ref'];require(report['resume_text'][ref['start']:ref['end']]==ref['quote'])
            for ref in item['supporting_refs']:
                require(ref['source_id'] in source_index and ref['source_id'] in index)
                source=source_index[ref['source_id']]
                require(source['kind']=='learning_artifact' and source['view']['summary'][ref['start']:ref['end']]==ref['quote'])
        result=deepcopy(blob)
        result['provenance']['missing_evidence']=deepcopy(app['candidate']['missing_evidence'])
        return result
    except (OSError,ValueError,KeyError,TypeError,StopIteration,WorkbenchError):
        raise PublicationUnavailable('真实D结果或来源暂时无法核对，未展示未核对的内容；固定回放仍可查看。') from None

def provenance_report(report,provenance):
    return {**deepcopy(report),'result_provenance':deepcopy(provenance)}

def published_read(service,token,kind,value,*,loader=load_publication):
    if kind not in ('state','records'):return value
    try:blob=loader(service,token)
    except PublicationUnavailable as exc:return {**value,'publication_status':{'status':'unavailable','notice':str(exc)}}
    if blob is None:return value
    value=deepcopy(value);provenance=blob['provenance'];formal=blob['resume'];report=formal['report']
    value['publication_status']={'status':'ready','resume_id':formal['resume_id'],'provenance':provenance,
                                 'base_revision':blob['base_revision'],'adopted_revision':report['snapshot_revision']}
    if kind=='state':
        # revision remains the sealed base's mutation revision. Published results are a read-only view.
        value['base_record_count']=value['record_count'];value['published_record_count']=2;value['record_count']+=2
        value['resume_reports'].insert(0,{'resume_id':formal['resume_id'],'created_at':report['created_at'],
           'snapshot_revision':report['snapshot_revision'],'source_counts':report['source_counts'],'result_origin':'real_model_reviewed'})
    else:
        delta=deepcopy(blob['records'])
        next(r for r in delta if r['payload']['event']=='resume_report')['payload']['report']=provenance_report(report,provenance)
        value['records']=sorted([*delta,*value['records']],key=lambda row:row['seq'],reverse=True)
    return value

def published_resume(service,token,rid,*,loader=load_publication):
    # Only the pinned public result may be looked up; never look in an arbitrary trial directory.
    try:blob=loader(service,token)
    except PublicationUnavailable:
        # Existing fixed reports remain available even when publication validation fails.
        if rid=='RESUME_320d298d4fd15323bf4877f7':raise WorkbenchError('本份真实D结果的来源暂时无法核对，请重新读取或查看保留的固定建议。') from None
        return None
    if blob is None or blob['resume']['resume_id']!=rid:return None
    formal=deepcopy(blob['resume']);formal['report']=provenance_report(formal['report'],blob['provenance'])
    return formal
