from __future__ import annotations

import hashlib
import json
import os
from datetime import date, datetime
from decimal import Decimal
from getpass import getpass
from pathlib import Path

from sqlalchemy import URL, create_engine

from desktop.paths import AppPaths
ROOT = AppPaths.current().resources
ZERO = Decimal("0")
CENT = Decimal("0.01")


def encode(value):
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    raise TypeError(type(value).__name__)


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"), parse_float=Decimal)


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=encode) + "\n", encoding="utf-8")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def project_path(value):
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def db_engine(connection, password=None):
    # URL.create负责处理密码中的@、:、/等字符；密码不写进配置与日志。
    if password is None:
        password = os.environ.get(connection.get("password_env", "FINANCE_DB_PASSWORD"))
    if password is None:
        password = getpass("MySQL密码（仅本地输入，不保存）: ")
    url = URL.create("mysql+pymysql", username=connection["user"], password=password,
                     host=connection.get("host", "127.0.0.1"),
                     port=int(connection.get("port", 3306)), database=connection["database"],
                     query={"charset": "utf8mb4"})
    return create_engine(url, pool_pre_ping=True, hide_parameters=True,
                         connect_args={"connect_timeout": 5})
