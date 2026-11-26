"""Read the original table with explicitly replaced months overlaid from staged files."""
import json
from collections import defaultdict

from .common import project_path
from .dates import parse_business_date
from .file_tables import read_table

DAYS = {'sales': 'revenue_date', 'refunds': 'refund_date', 'expenses': 'expense_date',
        'sales_budget': 'month', 'expense_budget': 'month'}


def business_day(role, setting, row):
    field = DAYS[role]
    return parse_business_date(row.get(setting['mapping'][field]), field=field, allow_month=field == 'month')


def source_paths(setting):
    paths = list(setting['files'])
    for ref in setting.get('month_files', {}).values():
        if ref and ref['path'] not in paths:
            paths.append(ref['path'])
    return paths


def read_replacement(ref):
    table = read_table(project_path(ref['path']), sheet_name=ref.get('sheet_name'), header_row=ref['header_row'])
    aliases = ref.get('aliases', {})
    if set(aliases.values()) - set(table.columns):
        raise ValueError('更新文件的列名已变化，请重新选择字段。')
    return [{**row, **{old: row[new] for old, new in aliases.items()}} for row in table.rows]


def overlay_months(role, setting, base_rows):
    replacements = setting['month_files']
    rows = [row for row in base_rows if business_day(role, setting, row).isoformat()[:7] not in replacements]
    grouped = defaultdict(set)
    for month, ref in replacements.items():
        if ref:
            grouped[json.dumps(ref, sort_keys=True)].add(month)
    for serialized, months in grouped.items():
        rows.extend(row for row in read_replacement(json.loads(serialized))
                    if business_day(role, setting, row).isoformat()[:7] in months)
    return rows

