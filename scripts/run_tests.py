"""Run regression with disposable preferences and financial workspace."""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--pattern',default='test*.py')
    args=parser.parse_args()
    base=ROOT/'outputs/validation'
    base.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='regression-',dir=base) as directory:
        env={**os.environ,'FINANCEBP_DESKTOP':'0','FINANCEBP_DATA_DIR':directory,
             'FINANCEBP_RUN_DIR':'','FINANCEBP_RESOURCES_DIR':'','PYTHONUTF8':'1'}
        return subprocess.run([sys.executable,'-m','unittest','discover','-s','tests','-p',args.pattern,'-v'],cwd=ROOT,env=env).returncode


if __name__=='__main__': raise SystemExit(main())
