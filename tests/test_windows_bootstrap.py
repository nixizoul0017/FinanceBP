"""Exercise the actual Windows PowerShell5.1 native argument boundary."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.name=='nt' and shutil.which('powershell.exe'), 'Windows PowerShell integration')
class WindowsBootstrapTests(unittest.TestCase):
    def invoke(self, root, python):
        environment={**os.environ,'PYTHONUTF8':'1'}
        if python is not None:
            environment['FINANCEBP_PYTHON']=str(python)
        else:
            environment.pop('FINANCEBP_PYTHON',None)
        result=subprocess.run(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass',
                               '-File',str(root/'scripts/launch_windows.ps1'),'-CheckOnly'],
                              cwd=root,env=environment,capture_output=True,timeout=90)
        self.assertEqual(result.returncode,0,result.stdout.decode(errors='replace')+result.stderr.decode(errors='replace'))
        self.assertIn(b'PYTHON_READY:',result.stdout)
        return result

    def test_current_environment_detected_by_windows_powershell(self):
        self.invoke(ROOT,sys.executable)

    def test_fresh_folder_with_spaces_detects_installed_python(self):
        with tempfile.TemporaryDirectory(prefix='FinanceBP Windows ') as directory:
            root=Path(directory)
            (root/'scripts').mkdir()
            shutil.copy2(ROOT/'scripts/launch_windows.ps1',root/'scripts/launch_windows.ps1')
            self.assertFalse((root/'.venv').exists())
            self.invoke(root,sys.executable)
            # Also exercise automatic installed-Python discovery with no override.
            self.invoke(root,None)


if __name__=='__main__':
    unittest.main()
