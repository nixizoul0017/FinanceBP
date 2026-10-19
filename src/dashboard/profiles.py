"""网页来源选择和文件更新身份；不储存凭据。"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from etl.common import ROOT, digest, project_path, read_json
from etl.sources import validate_profile

PRESETS = {
    "完整模拟数据": "configs/demo_files.json",
    "多维模拟数据": "configs/multidimensional_files.json",
    "异名模拟数据": "configs/demo_renamed_files.json",
    "小样本核对": "configs/sample_files.json",
    "本机MySQL小样本": "configs/sample_mysql.example.json",
    "本机MySQL完整数据": "configs/demo_mysql.example.json",
}


def selected_profile(label, uploaded=None):
    if label == "自定义配置":
        if uploaded is None:
            return None
        profile = json.loads(uploaded.getvalue().decode("utf-8-sig"))
    else:
        profile = read_json(ROOT / PRESETS[label])
    validate_profile(profile)
    return profile


def file_identity(profile):
    identity = {"profile": profile, "files": []}
    if profile["source"]["kind"] == "files":
        for name, setting in profile["tables"].items():
            for path_value in setting["files"]:
                path = project_path(path_value)
                identity["files"].append((name, str(path), digest(path)))
    return hashlib.sha256(json.dumps(identity, sort_keys=True, default=str).encode()).hexdigest()
