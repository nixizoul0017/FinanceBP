"""Silent install, same-version overlay and uninstall with isolated personal data."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))


def run():
    from desktop.events import atomic_json
    from finance.store import WorkspaceStore
    build=ROOT/'outputs/desktop_build'
    setup=ROOT/'dist/FinanceBP-1.0.0-windows-x64-setup.exe'
    installation=build/'installed'
    personal=build/'installer_personal_data'
    if not installation.resolve().is_relative_to(build.resolve()): raise ValueError('Invalid installation test path')
    if not personal.resolve().is_relative_to(build.resolve()): raise ValueError('Invalid personal test path')
    atomic_json(personal/'runtime/ui_preferences.json',{'version':1,'theme':'plum'})
    atomic_json(personal/'runtime/dimension_views.json',{'version':1,'contexts':{'identity:keep':{'last_layout':{'slots':['product_id','channel_id','region_id'],'group_by':['product_id']}}}})
    store=WorkspaceStore(personal/'runtime/finance_workspace.sqlite3')
    with store.connection(True) as db:
        db.execute('INSERT OR REPLACE INTO settings VALUES (?,?)',('keep-company-and-source','{"acceptance":"preserve"}'))
    names=['runtime/ui_preferences.json','runtime/dimension_views.json','runtime/finance_workspace.sqlite3']
    def hashes(): return {name:hashlib.sha256((personal/name).read_bytes()).hexdigest() for name in names}
    before=hashes()
    checks=[]
    def check(name,condition):
        checks.append({'check':name,'passed':bool(condition)})
        if not condition: raise AssertionError(name)
    def install(log):
        result=subprocess.run([str(setup),'/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/MERGETASKS=!desktopicon',
                               '/DIR='+str(installation),'/LOG='+str(build/log)],timeout=180)
        check(log+'_exit_zero',result.returncode==0)
        check(log+'_executable_present',(installation/'FinanceBP.exe').is_file())
    install('install-final.log')
    check('installation_preserves_personal_data',hashes()==before)
    install('overlay-install.log')
    check('same_version_overlay_preserves_personal_data',hashes()==before)
    # Do not launch the app during this step; only the verified test installation
    # is removed. Personal files live outside it and must stay byte-identical.
    result=subprocess.run([str(installation/'unins000.exe'),'/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART',
                           '/LOG='+str(build/'uninstall-final.log')],timeout=90)
    check('uninstaller_exit_zero',result.returncode==0)
    for _ in range(40):
        if not (installation/'FinanceBP.exe').exists(): break
        time.sleep(.25)
    check('uninstaller_removes_executable',not (installation/'FinanceBP.exe').exists())
    check('uninstaller_preserves_personal_data',hashes()==before)
    install('reinstall-final.log')
    check('reinstall_keeps_company_identity_and_records',hashes()==before)
    return {'passed':True,'checks':checks,'personal_data_sha256':before,'same_version_overlay_tested':True,
            'cross_version_upgrade_tested':False,'clean_machine_tested':False,
            'installation':str(installation),'setup_sha256':hashlib.sha256(setup.read_bytes()).hexdigest()}


if __name__=='__main__':
    output=ROOT/'outputs/desktop_build/installation-lifecycle.json'
    try: result=run()
    except Exception as error:
        import traceback
        result={'passed':False,'error':str(error),'traceback':traceback.format_exc()}
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({key:result[key] for key in ('passed','error') if key in result}))
    raise SystemExit(0 if result['passed'] else 1)
