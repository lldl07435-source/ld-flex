from pathlib import Path
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from ldcell.kernel import check_library
try:check_library()
except RuntimeError:
    subprocess.run([sys.executable,str(ROOT/'tools'/'build.py')],cwd=ROOT,check=True)
subprocess.run([sys.executable,str(ROOT/'app.py')],cwd=ROOT,check=True)
