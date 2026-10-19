"""本地不可覆盖预测版本；保存失败不留下半份版本，来源数据库保持只读。"""
from copy import deepcopy
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import tempfile
from zoneinfo import ZoneInfo

from etl.common import ROOT, encode
from desktop.paths import AppPaths


def content_digest(pack):
    canonical=json.dumps(pack,ensure_ascii=False,sort_keys=True,default=encode,allow_nan=False,separators=(",",":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def load_forecast(path):
    record=json.loads(Path(path).read_text(encoding="utf-8"))
    if record.get("content_sha256")!=content_digest(record["result"]):
        raise ValueError("预测版本内容校验失败")
    if record.get("run_id")!="FC9_"+record["content_sha256"][:24]:
        raise ValueError("预测版本身份校验失败")
    return record


def saved_forecasts(entity_id,directory=None):
    directory=Path(directory) if directory is not None else AppPaths.current().forecasts
    if not directory.exists():
        return []
    result=[]
    for path in sorted(directory.glob("FC9_*.json"),key=lambda p:p.stat().st_mtime_ns,reverse=True):
        try:
            record=load_forecast(path)
            if record["result"]["metadata"]["entity_id"]==entity_id:
                result.append({"run_id":record["run_id"],"path":str(path),"created_at":record["created_at"],"cutoff_month":record["result"]["metadata"]["cutoff_month"],"method":record["result"]["metadata"]["method"]})
                if len(result)>=10:
                    break
        except (ValueError,KeyError):
            # 损坏版本不进入可复核列表，仍保留原文件供人工处理。
            continue
    return result


def save_forecast(pack,directory=None):
    directory=Path(directory) if directory is not None else AppPaths.current().forecasts
    directory.mkdir(parents=True,exist_ok=True)
    canonical=json.dumps(pack,ensure_ascii=False,sort_keys=True,default=encode,allow_nan=False,separators=(",",":"))
    run_id="FC9_"+hashlib.sha256(canonical.encode()).hexdigest()[:24]
    path=directory/(run_id+".json")
    if path.exists():
        existing=load_forecast(path)
        if existing["content_sha256"]!=hashlib.sha256(canonical.encode()).hexdigest():
            raise ValueError("版本身份冲突")
        return {"run_id":run_id,"path":str(path),"reused":True}
    record={"run_id":run_id,"created_at":datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),"content_sha256":hashlib.sha256(canonical.encode()).hexdigest(),
        "base_run_id":run_id+"_base","scenario_versions":{name:{"run_id":run_id+"_"+name,"base_run_id":None if name=="base" else run_id+"_base"} for name in pack["scenarios"]},"result":deepcopy(pack)}
    temporary=None
    try:
        with tempfile.NamedTemporaryFile(mode="w",encoding="utf-8",dir=directory,prefix=".forecast_",suffix=".tmp",delete=False) as handle:
            temporary=Path(handle.name)
            json.dump(record,handle,ensure_ascii=False,indent=2,default=encode,allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        # hardlink的创建不可覆盖已有目标，同一内容的并发保存不改历史版本。
        try:
            os.link(temporary,path)
        except FileExistsError:
            existing=load_forecast(path)
            if existing["content_sha256"]!=record["content_sha256"]:
                raise ValueError("版本身份冲突")
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return {"run_id":run_id,"path":str(path),"reused":False}
