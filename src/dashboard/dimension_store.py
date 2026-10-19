"""Local classification layouts, named views and confirmed mappings. No filter values."""
from copy import deepcopy
import json
import hashlib
import os
from pathlib import Path
import tempfile
import threading
import uuid

from etl.dimensions import BUILTINS, profile_key, validate_dimensions

from desktop.paths import AppPaths
STORE_PATH = AppPaths.current().runtime/'dimension_views.json'
_LOCK = threading.RLock()


def clean_layout(value, known, strict=True):
    if not isinstance(value, dict):
        raise ValueError('方案格式无效')
    slots, groups = value.get('slots', []), value.get('group_by', [])
    if not isinstance(slots,list) or not isinstance(groups,list) or len(slots)>128:
        raise ValueError('方案分类列表无效')
    if any(field is not None and not isinstance(field,str) for field in slots) or any(not isinstance(field,str) for field in groups):
        raise ValueError('方案分类编号无效')
    unknown = sorted({field for field in slots+groups if field is not None and field not in known})
    if strict and unknown:
        raise ValueError('方案包含失效分类：'+', '.join(unknown))
    slots = [field if field in known else None for field in slots]
    groups = [field for field in groups if field in known]
    if len([x for x in slots if x]) != len(set(x for x in slots if x)) or len(groups)!=len(set(groups)):
        raise ValueError('分类不能重复')
    while len(slots)>3 and slots[-1] is None:
        slots.pop()
    slots += [None]*max(0,3-len(slots))
    return {'slots':slots,'group_by':groups}, unknown


def mapping_signature(profile):
    return hashlib.sha256(json.dumps({key:profile.get(key) for key in ('profile_version','dimensions','forecast_dimensions')} | {'core_mappings':{name:value.get('mapping',{}) for name,value in profile['tables'].items() if name not in profile.get('lookup_tables',[])}},sort_keys=True,ensure_ascii=False).encode()).hexdigest()


class DimensionStore:
    def __init__(self, path=None):
        self.path = Path(path or STORE_PATH)
        self.warning = None

    def read(self):
        try:
            data=json.loads(self.path.read_text(encoding='utf-8'))
            if data.get('version')!=1 or not isinstance(data.get('contexts'),dict):
                raise ValueError('unknown preference version')
            return data
        except FileNotFoundError:
            return {'version':1,'contexts':{}}
        except (OSError, ValueError, AttributeError):
            self.warning='本机分类方案暂无法读取，本次使用默认布局；原文件未删除。'
            return {'version':1,'contexts':{}}

    def context(self, key):
        value=self.read()['contexts'].get(key,{})
        return deepcopy(value) if isinstance(value,dict) else {}

    def update(self, key, **changes):
        temporary=None
        with _LOCK:
            data=self.read()
            if self.warning:
                return False
            context=data['contexts'].setdefault(key,{})
            context.update(deepcopy(changes))
            try:
                self.path.parent.mkdir(parents=True,exist_ok=True)
                with tempfile.NamedTemporaryFile('w',encoding='utf-8',dir=self.path.parent,prefix='.dimensions-',suffix='.tmp',delete=False) as stream:
                    temporary=Path(stream.name)
                    json.dump(data,stream,ensure_ascii=False,indent=2,allow_nan=False)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary,self.path)
                return True
            except OSError:
                self.warning='本次分类设置已生效，但无法保存到本机目录；重新打开后可能无法恢复。'
                return False
            finally:
                if temporary:
                    try:
                        temporary.unlink(missing_ok=True)
                    except OSError:
                        pass

    def layout(self, key, known):
        context=self.context(key)
        default={'slots':[field for field in BUILTINS if field in known],'group_by':[next(iter(known))] if known else []}
        try:
            layout, unknown=clean_layout(context.get('last_layout',default),known,False)
        except ValueError:
            self.warning='保存的分类布局无效，本次恢复默认；命名方案仍保留。'
            layout,unknown=clean_layout(default,known)
        return layout,unknown,context.get('active_scheme')

    def remember(self,key,layout,known,active=None):
        layout,_=clean_layout(layout,known)
        return self.update(key,last_layout=layout,active_scheme=active)

    def schemes(self,key):
        schemes=self.context(key).get('schemes',[])
        return [item for item in schemes if isinstance(item,dict) and all(k in item for k in ('id','name','layout'))] if isinstance(schemes,list) else []

    def save_scheme(self,key,name,layout,known,scheme_id=None):
        name=name.strip()
        if not name or len(name)>60:
            raise ValueError('方案名称请输入1—60个字符')
        layout,_=clean_layout(layout,known)
        schemes=self.schemes(key)
        if scheme_id is not None and not any(x['id']==scheme_id for x in schemes):
            raise ValueError('原方案已不存在')
        if any(x['name'].casefold()==name.casefold() and x['id']!=scheme_id for x in schemes):
            raise ValueError('方案名称已存在，请使用其他名称或更新当前方案')
        scheme_id=scheme_id or uuid.uuid4().hex
        schemes=[x for x in schemes if x['id']!=scheme_id]+[{'id':scheme_id,'name':name,'layout':layout}]
        if not self.update(key,schemes=schemes,last_layout=layout,active_scheme=scheme_id):
            raise ValueError(self.warning)
        return scheme_id

    def delete(self,key,scheme_id):
        context=self.context(key)
        return self.update(key,schemes=[x for x in self.schemes(key) if x['id']!=scheme_id],
                           active_scheme=None if context.get('active_scheme')==scheme_id else context.get('active_scheme'))

    def export(self,key,registry):
        return json.dumps({'format':'financebp_dimension_views','version':1,
                           'dimensions':[{'id':x['id'],'label':x['label']} for x in registry],
                           'schemes':self.schemes(key)},ensure_ascii=False,indent=2).encode('utf-8')

    def import_schemes(self,key,payload,known):
        data=json.loads(payload)
        if data.get('format')!='financebp_dimension_views' or data.get('version')!=1 or not isinstance(data.get('schemes'),list):
            raise ValueError('请选择有效的分类方案文件')
        existing=self.schemes(key)
        names={x['name'].casefold() for x in existing}
        imported=[]
        for item in data['schemes']:
            name=item['name'].strip()
            layout,_=clean_layout(item['layout'],known)
            if not name or len(name)>60 or name.casefold() in names:
                raise ValueError('方案名称为空、过长或已存在；请先重命名，未导入任何方案')
            names.add(name.casefold())
            imported.append({'id':uuid.uuid4().hex,'name':name,'layout':layout})
        if not self.update(key,schemes=existing+imported):
            raise ValueError(self.warning)
        return len(imported)

    def confirmed_profile(self,profile):
        context=self.context(profile_key(profile))
        override=context.get('mapping')
        if not override or (context.get("mapping_base_signature") and context["mapping_base_signature"]!=mapping_signature(profile)):
            return profile
        candidate={**deepcopy(profile),**deepcopy(override)}
        candidate['tables']={**deepcopy(profile['tables']),**{name:value for name,value in override.get('tables',{}).items() if name in override.get('lookup_tables',[])}}
        validate_dimensions(candidate)
        return candidate

    def confirm(self,profile,dimensions,tables=None,lookup_tables=None,base_profile=None):
        candidate=deepcopy(profile)
        candidate.update(profile_version=2,dimensions=dimensions)
        # Keep the source namespace, including when auxiliary lookup tables are added.
        candidate['profile_id']=profile_key(profile).split(':',1)[1]
        if tables is not None:
            candidate['tables']=deepcopy(tables)
        if lookup_tables is not None:
            candidate['lookup_tables']=list(lookup_tables)
        validate_dimensions(candidate)
        candidate.setdefault('forecast_dimensions', [*BUILTINS, *(item['id'] for item in dimensions)])
        override={key:candidate[key] for key in ('profile_version','profile_id','dimensions','tables','forecast_dimensions')}
        override['lookup_tables']=candidate.get('lookup_tables',[])
        if not self.update(profile_key(profile),mapping=override,mapping_base_signature=mapping_signature(base_profile or profile)):
            raise ValueError(self.warning)
        return candidate
