"""Prepare an immutable monthly candidate. The saved profile is the only commit pointer."""
from copy import deepcopy
from decimal import Decimal

from analysis.metrics import month_range
from .file_import import coverage
from .month_files import DAYS, business_day, read_replacement
from .sources import FACT_KEYS, load_facts


def months_between(start, end):
    coverage(start, end)
    return [day.isoformat()[:7] for day in month_range(start, end)]


def inspect_input(role, setting, ref, months):
    rows = read_replacement(ref)
    dates = [business_day(role, setting, row).isoformat() for row in rows]
    observed = {day[:7] for day in dates}
    outside = observed - set(months)
    if outside:
        raise ValueError('文件含所选范围以外的月份：' + '、'.join(sorted(outside)))
    amount_field = {'sales':'sales_amount_before_refund','refunds':'refund_amount','expenses':'amount',
                    'expense_budget':'amount'}.get(role)
    def amount(row):
        mapping = setting['mapping']
        if amount_field:
            return Decimal(str(row[mapping[amount_field]]))
        return Decimal(str(row[mapping['quantity']])) * Decimal(str(row[mapping['net_unit_price']]))
    return {'months': observed, 'rows': len(rows), 'start': min(dates, default=''), 'end': max(dates, default=''),
            'amount': sum((amount(row) for row in rows), Decimal(0))}


def indexed(facts, role, months):
    result = {month: {} for month in months}
    for row in facts.tables[role].to_dict('records'):
        month = str(row[DAYS[role]])[:7]
        if month in result:
            fields = FACT_KEYS[role][1:]
            if role == 'sales_budget':
                fields = ['budget_version', 'month', *facts.metadata['budget_dimensions'][row['budget_version']]]
            result[month][tuple(row[key] for key in fields)] = row
    return result


def total(role, rows):
    fields = {'sales':'sales_amount_before_refund', 'refunds':'refund_amount',
              'expenses':'amount', 'expense_budget':'amount'}
    if role == 'sales_budget':
        return sum((r['quantity'] * r['net_unit_price'] for r in rows), Decimal(0))
    return sum((r[fields[role]] for r in rows), Decimal(0))


def prepare_update(profile, updates, start, end):
    """updates maps configured roles to ref, missing-month decisions and optional first mapping."""
    months = months_between(start, end)
    if not updates or start[:4] != end[:4]:
        raise ValueError('请选择同一年度内的月份和业务表。')
    candidate = deepcopy(profile)
    old = profile['coverage']
    actual_roles = set(profile['tables']) & {'sales','refunds','expenses'}
    prior_range = set(months_between(old['complete_start'][:7], old['complete_end'][:7]))
    original = prior_range.copy()
    original -= {month[:7] for month in old.get('incomplete_months', [])}
    covered = {role: set(profile.get('role_months', {}).get(role, original)) for role in actual_roles}
    applied = {}
    for role, update in updates.items():
        setting = candidate['tables'][role]
        if not setting.get('mapping') and update.get('mapping'):
            setting.update(mapping=update['mapping'], defaults=update['defaults'])
        ref = update.get('ref')
        if ref and ref.get('aliases'):
            setting.setdefault('header_aliases', {}).update(ref['aliases'])
        present = inspect_input(role, setting, ref, months)['months'] if ref else set()
        applied[role] = set()
        for month in months:
            choice = 'replace' if month in present else update.get('missing', {}).get(month)
            if choice == 'keep':
                continue
            if choice not in ('empty','replace') or (choice == 'replace' and month not in present):
                raise ValueError('请逐月选择保留旧数据或确认该月无记录。')
            setting.setdefault('month_files', {})[month] = ref if choice == 'replace' else None
            applied[role].add(month)
        if role in covered:
            covered[role].update(applied[role])
    all_actual = sorted(set().union(*covered.values(), {old['complete_start'][:7], old['complete_end'][:7]}))
    bounds = coverage(all_actual[0], all_actual[-1])
    incomplete = [m+'-01' for m in months_between(all_actual[0], all_actual[-1])
                  if not all(m in known for known in covered.values())]
    candidate['coverage'] = {**old, **bounds}
    pending = {}
    for month in months_between(all_actual[0], all_actual[-1]):
        required = actual_roles if month not in prior_range else old.get('pending_sources', {}).get(month, [])
        missing = sorted(role for role in required if month not in covered[role])
        if missing:
            pending[month] = missing
    if pending or 'pending_sources' in old:
        candidate['coverage']['pending_sources'] = pending
    if incomplete or 'incomplete_months' in old:
        candidate['coverage']['incomplete_months'] = incomplete
    candidate['role_months'] = {role: sorted(values) for role, values in covered.items()}
    before = load_facts(profile)
    after = load_facts(candidate)
    summaries, details = [], []
    changed = False
    for role, selected in applied.items():
        left, right = indexed(before, role, months), indexed(after, role, months)
        for month in months:
            old_rows, new_rows = left[month], right[month]
            counts = {'新增':0, '修改':0, '移除':0}
            for key in sorted(old_rows.keys() | new_rows.keys()):
                previous, current = old_rows.get(key), new_rows.get(key)
                if previous == current:
                    continue
                kind = '新增' if previous is None else '移除' if current is None else '修改'
                counts[kind] += 1
                details.append({'月份':month,'业务表':role,'业务编号':' / '.join(map(str,key)), '变化':kind,
                                '原记录':previous,'新记录':current})
            prior_known = set(profile.get('role_months', {}).get(role, original))
            previous_ref = profile['tables'][role].get('month_files', {}).get(month) or {}
            ref = updates[role].get('ref') or {}
            mapping_change = (month in selected and bool(ref) and
                              (previous_ref.get('aliases', {}) != ref.get('aliases', {}) or
                               candidate['tables'][role].get('mapping') != profile['tables'][role].get('mapping')))
            modified = bool(sum(counts.values()) or mapping_change or
                            (role in covered and month in selected and month not in prior_known))
            changed |= modified
            if modified:
                candidate.setdefault('month_batches', {}).setdefault(role, {})[month] = ref.get('sha256','empty') if month in selected and candidate['tables'][role]['month_files'][month] else 'empty'
            elif month in selected:
                refs = candidate['tables'][role]['month_files']
                if month in profile['tables'][role].get('month_files', {}):
                    refs[month] = profile['tables'][role]['month_files'][month]
                else:
                    refs.pop(month)
            summaries.append({'月份':month,'业务表':role,'有变化':modified,**counts,
                              '原金额':total(role,old_rows.values()),'新金额':total(role,new_rows.values())})
    summaries.sort(key=lambda row: (not row['有变化'], row['月份'], row['业务表']))
    if changed:
        # Validate the exact pointer that will be published after pruning identical slices.
        after = load_facts(candidate)
    return {'profile': candidate if changed else profile, 'facts':after if changed else before,
            'changed':changed,'summary':summaries,'details':details}

