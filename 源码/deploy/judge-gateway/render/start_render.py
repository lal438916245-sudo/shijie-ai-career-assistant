"""Free Render: private external ledger; default no model dispatch."""
import os,secrets,sys
from judge_gateway import main
probe=os.environ.get('SHIJIE_PROBE_ONLY','1')
if probe not in ('0','1'):raise SystemExit('SHIJIE_PROBE_ONLY must be 0 or 1')
database_url=os.environ.get('SHIJIE_DATABASE_URL','')
args=['judge_gateway.py','--policy','/app/policy.json','--host','0.0.0.0','--port',os.environ.get('PORT','10000')]
if probe=='1':
    os.environ['SHIJIE_PROVIDER_KEY']='probe-only-no-provider-key'
    os.environ['SHIJIE_JUDGE_PASS']=secrets.token_urlsafe(32)
    args+=['--probe-only']
    if not database_url:args+=['--ledger','/tmp/shijie-probe-'+secrets.token_hex(8)+'.db']
elif not database_url:
    raise SystemExit('SHIJIE_DATABASE_URL is required; no temporary/local billing fallback')
args+=['--previous-policy','/app/previous-policy.json']
sys.argv=args
main()
