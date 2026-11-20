"""Packaged Windows entry. Modules and assets are resolved relative to bundle."""
import sys
from pathlib import Path
if not getattr(sys,'frozen',False):sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from delivery_runtime import main
if __name__=='__main__':raise SystemExit(main())
