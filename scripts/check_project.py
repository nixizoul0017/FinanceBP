"""Check all shipped Markdown links, required inputs, source syntax and exclusions."""
import ast
import json
from pathlib import Path
import re
from urllib.parse import unquote
from package_project import ROOT, release_files


def check(root=ROOT):
    root=Path(root).resolve()
    files=release_files(root)
    names={p.relative_to(root).as_posix() for p in files}
    required={'START.cmd','START.command','scripts/desktop_launcher.py','scripts/launch_windows.ps1','scripts/manage.py','scripts/manage.ps1','docs/PROJECT_LOG.md','docs/PATHS.md','docs/USER_GUIDE.md',
              'tests/fixtures/sample_sql_reference.json','tests/fixtures/monthly_reference.json','tests/fixtures/report_reference.json'}
    errors=['Missing: '+x for x in sorted(required-names)]
    shell_bytes=(root/'START.command').read_bytes()
    if b'\r' in shell_bytes or shell_bytes.startswith(b'\xef\xbb\xbf'):
        errors.append('START.command must use LF without a UTF-8 BOM')
    links=0
    for path in files:
        if path.suffix=='.py':
            ast.parse(path.read_text(encoding='utf-8-sig'),filename=str(path))
        if path.suffix!='.md': continue
        for target in re.findall(r'!?\[[^\]]*\]\(([^)]+)\)',path.read_text(encoding='utf-8-sig')):
            if re.match(r'^[a-zA-Z][\w+.-]*:',target) or target.startswith('#'): continue
            base=unquote(target.split('#',1)[0].strip('<>'))
            if not base: continue
            links+=1
            destination=(path.parent/base).resolve()
            if not destination.is_relative_to(root) or destination.relative_to(root).as_posix() not in names:
                errors.append(path.relative_to(root).as_posix()+' -> '+target)
    bad=[x for x in names if any(part in {'.venv','outputs','dist','node_modules','__pycache__'} for part in Path(x).parts)
         or x.endswith(('.local.json','.log','.pyc')) or Path(x).name=='secrets.toml']
    errors.extend('Unexpected release member: '+x for x in bad)
    result={'passed':not errors,'release_files':len(files),'local_markdown_links_checked':links,'errors':errors}
    output=root/'outputs/validation'
    output.mkdir(parents=True,exist_ok=True)
    (output/'project_structure.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))
    return result


if __name__=='__main__':
    raise SystemExit(0 if check()['passed'] else 1)
