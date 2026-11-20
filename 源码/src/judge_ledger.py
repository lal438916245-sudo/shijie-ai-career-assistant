"""Private budget persistence. Never fall back from Postgres to a new local ledger."""
from contextlib import closing,contextmanager
from pathlib import Path
from urllib.parse import urlsplit,parse_qsl
import sqlite3

class GatewayError(ValueError):
    def __init__(self,status,code):
        self.status=status;self.code=code;super().__init__(code)

class JudgeLedger:
    def __init__(self,path=None,*,database_url=None):
        self.backend='postgres' if database_url else 'sqlite'
        self._errors=(sqlite3.Error,)
        self._driver=None;self._database_url=None
        self.path=None
        if database_url:
            try:
                u=urlsplit(database_url)
                if u.scheme not in ('postgres','postgresql') or not u.hostname or not u.username or not u.path.strip('/') or u.fragment:
                    raise ValueError()
                if any(c in database_url for c in ('\n','\r','\x00')):raise ValueError()
                # Cloud hosts must use TLS; no remote sslmode=disable loophole.
                q=dict(parse_qsl(u.query))
                if u.hostname not in ('127.0.0.1','localhost','::1') and q.get('sslmode','require') not in ('require','verify-ca','verify-full'):
                    raise ValueError()
            except (ValueError,TypeError):raise ValueError('Invalid private Postgres URL; no credentials printed') from None
            try:import psycopg
            except ImportError:raise ValueError('Postgres driver unavailable; no local fallback') from None
            self._driver=psycopg;self._errors+=(psycopg.Error,);self._database_url=database_url
            self._sslmode=q.get('sslmode','disable' if u.hostname in ('127.0.0.1','localhost','::1') else 'require')
        else:
            if path is None:raise ValueError('A persistent ledger destination is required')
            self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True)

    def table(self,name):return ('shijie_gateway.' if self.backend=='postgres' else '')+name
    def sql(self,statement):return statement.replace('?','%s') if self.backend=='postgres' else statement

    def connect(self):
        try:
            if self.backend=='sqlite':return sqlite3.connect(self.path,timeout=10)
            return self._driver.connect(self._database_url,connect_timeout=10,sslmode=self._sslmode,
                options='-c statement_timeout=10000 -c lock_timeout=10000',application_name='shijie-budget-gateway')
        except self._errors:raise GatewayError(503,'ledger_unavailable_no_new_dispatch') from None

    @contextmanager
    def transaction(self,*,lock=False):
        try:
            with closing(self.connect()) as c,c:
                if lock:
                    if self.backend=='sqlite':c.execute('BEGIN IMMEDIATE')
                    else:
                        row=c.execute('SELECT digest FROM shijie_gateway.policy WHERE singleton=1 FOR UPDATE').fetchone()
                        if not row:raise GatewayError(503,'ledger_policy_missing_no_dispatch')
                yield c
        except self._errors:raise GatewayError(503,'ledger_unavailable_no_new_dispatch') from None

    def check(self):
        with self.transaction() as c:c.execute('SELECT 1').fetchone()

    def initialize(self,fingerprint,*,probe_only=False,previous_fingerprint=None,migration=None):
        if probe_only and self.backend=='postgres':
            # Check connection without creating a billable policy with a temporary probe pass.
            self.check();return
        with self.transaction() as c:
            if self.backend=='postgres':
                # One fixed lock and schema for all replicas/restarts. No caller-chosen namespace.
                c.execute('SELECT pg_advisory_xact_lock(746512349876120)')
                c.execute('CREATE SCHEMA IF NOT EXISTS shijie_gateway')
            c.execute(f'CREATE TABLE IF NOT EXISTS {self.table("policy")}(singleton INTEGER PRIMARY KEY CHECK(singleton=1),digest TEXT NOT NULL)')
            c.execute(f'CREATE TABLE IF NOT EXISTS {self.table("calls")}(id TEXT PRIMARY KEY,body_digest TEXT NOT NULL,stage TEXT NOT NULL,status TEXT NOT NULL,reserve BIGINT NOT NULL CHECK(reserve>=0),charge BIGINT CHECK(charge>=0),response TEXT,created DOUBLE PRECISION NOT NULL)')
            old=c.execute(f'SELECT digest FROM {self.table("policy")}'+(' FOR UPDATE' if self.backend=='postgres' else '')).fetchone()
            if previous_fingerprint and old is None:raise ValueError('Upgrade requires existing ledger; refusing an empty replacement database')
            if old and old[0]!=fingerprint:
                if old[0]!=previous_fingerprint or not migration:raise ValueError('Gateway policy changed: preserve original ledger; do not reset budget')
                calls=self.table('calls')
                if c.execute(f"SELECT 1 FROM {calls} WHERE status='dispatching'").fetchone():raise ValueError('An original request is still in progress; do not migrate or reset it')
                count,total,held=c.execute(f'SELECT count(*),coalesce(sum(coalesce(charge,reserve)),0),coalesce(sum(CASE WHEN charge IS NULL THEN reserve ELSE 0 END),0) FROM {calls}').fetchone()
                c.execute(f'CREATE TABLE IF NOT EXISTS {self.table("policy_migrations")}(new_digest TEXT PRIMARY KEY,old_digest TEXT NOT NULL,details_json TEXT NOT NULL,retained_calls BIGINT NOT NULL,retained_micro_cny BIGINT NOT NULL,retained_unknown_micro_cny BIGINT NOT NULL,created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP)')
                c.execute(self.sql(f'INSERT INTO {self.table("policy_migrations")} (new_digest,old_digest,details_json,retained_calls,retained_micro_cny,retained_unknown_micro_cny) VALUES(?,?,?,?,?,?)'),(fingerprint,old[0],migration,int(count),int(total),int(held)))
                c.execute(self.sql(f'UPDATE {self.table("policy")} SET digest=? WHERE singleton=1'),(fingerprint,))
            c.execute(self.sql(f'INSERT INTO {self.table("policy")} VALUES(1,?) ON CONFLICT(singleton) DO NOTHING'),(fingerprint,))

    def status(self):
        with self.transaction() as c:
            n,total,unknown=c.execute(f'SELECT count(*),coalesce(sum(coalesce(charge,reserve)),0),coalesce(sum(CASE WHEN charge IS NULL THEN reserve ELSE 0 END),0) FROM {self.table("calls")}').fetchone()
        return int(n),int(total),int(unknown)

    def reserve(self,rid,body_hash,stage,amount,now,settings):
        calls=self.table('calls')
        with self.transaction(lock=True) as c:
            old=c.execute(self.sql(f'SELECT body_digest,status,response FROM {calls} WHERE id=?'),(rid,)).fetchone()
            if old:
                if old[0]!=body_hash:raise GatewayError(409,'request_identity_conflict')
                if old[1]=='completed':
                    if not isinstance(old[2],str) or not old[2]:raise GatewayError(503,'ledger_receipt_invalid_no_dispatch')
                    return old[2]
                raise GatewayError(409,'request_already_dispatched_query_original_receipt')
            n,total=c.execute(f'SELECT count(*),coalesce(sum(coalesce(charge,reserve)),0) FROM {calls}').fetchone()
            if n>=settings['max_calls'] or total+amount>settings['budget_micro_cny'] or c.execute(f'SELECT 1 FROM {calls} WHERE charge>reserve').fetchone():
                raise GatewayError(429,'sponsor_budget_exhausted')
            if c.execute(f"SELECT 1 FROM {calls} WHERE status='dispatching'").fetchone():raise GatewayError(429,'sponsor_busy_no_dispatch')
            c.execute(self.sql(f'INSERT INTO {calls} VALUES(?,?,?,?,?,?,?,?)'),(rid,body_hash,stage,'dispatching',amount,None,None,now))
        # Reaching here means the reservation COMMIT succeeded, including on Postgres.
        return None

    def finish(self,rid,*,status,cost,response=None):
        with self.transaction() as c:
            result=c.execute(self.sql(f'UPDATE {self.table("calls")} SET status=?,charge=?,response=? WHERE id=? AND status=\'dispatching\''),(status,cost,response,rid))
            if result.rowcount!=1:raise GatewayError(503,'ledger_receipt_conflict_preserve_hold')
