"""Per-process memoization of validated, sealed public replay GETs only."""
from collections import OrderedDict
from copy import deepcopy
from pathlib import Path
import hashlib,json,threading

READS={'state','records','plan','learning','assessment-options','assessment','interview','resume','publication'}
class ReplayReadCache:
    def __init__(self,limit=32):self.lock=threading.RLock();self.values=OrderedDict();self.limit=limit
    @staticmethod
    def stamp(service,token):
        from competition_showcase import PROFILE,REPLAY_TOKEN
        if service.case_profile!=PROFILE or token!=REPLAY_TOKEN:return None
        from competition_case import ROOT
        from workbench_published_resume import ASSET
        db=service._identity(token)[2];seal=(service._session_directory(REPLAY_TOKEN) if hasattr(service,'_session_directory') else service.directory)/'replay-sealed.json'
        if not seal.is_file() or any(Path(str(db)+s).exists() for s in ('-wal','-journal')):return None
        files=[db,seal,ASSET,*(ROOT/name for name in ('examples/competition_case/v2/manifest.json','examples/competition_case/v2/case.json','examples/competition_case/v2/cards/sql-join-grain.json','examples/competition_case/v2/cards/follow-along-v1.json','knowledge_base/curated_resources/v1/catalog.json'))]
        preparation=service.session_preparation
        if preparation is not None and preparation.path.exists():files.append(preparation.path)
        # Content hashes, rather than just mtime, retain tamper detection and
        # invalidate cached publications/configuration even with preserved times.
        h=hashlib.sha256()
        try:
            for file in files:
                h.update(str(file).encode());h.update(file.read_bytes())
        except OSError:return None # Missing assets use the original validated fallback/error.
        h.update(str(service.session_outbound_enabled).encode())
        return h.hexdigest()
    def read(self,service,token,kind,query,loader):
        if kind not in READS:return loader()
        stamp=self.stamp(service,token)
        if stamp is None:return loader()
        key=(stamp,kind,json.dumps(query,sort_keys=True))
        with self.lock:
            if key in self.values:
                self.values.move_to_end(key);return deepcopy(self.values[key])
            value=loader() # Existing provenance/quote/DB validation remains authoritative.
            if stamp==self.stamp(service,token):
                self.values[key]=deepcopy(value)
                while len(self.values)>self.limit:self.values.popitem(last=False)
            return value
