"""One cooperating adapter per local root; OS releases lease on process exit."""
import os
from pathlib import Path

class DirectoryLease:
    def __init__(self,directory):
        root=Path(directory).resolve();root.mkdir(parents=True,exist_ok=True)
        self.file=open(root/'.workflow-adapter.lock','a+b')
        try:
            self.file.seek(0,2)
            if self.file.tell()==0:self.file.write(b'0');self.file.flush()
            self.file.seek(0)
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(self.file.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError:
            self.file.close();self.file=None
            raise RuntimeError('已有工作流服务占用本目录，请保留现有服务或先正常停止它') from None
    def close(self):
        if self.file is not None:self.file.close();self.file=None
