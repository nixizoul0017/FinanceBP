"""Canonical analysis requests. Draft edits never change the committed request."""
from copy import deepcopy

from analysis.metrics import Filters
from .dimension_store import clean_layout


def normalized(request):
    layout = deepcopy(request['layout'])
    while len(layout['slots']) > 3 and layout['slots'][-1] is None:
        layout['slots'].pop()
    used = {field for field in layout['slots'] if field}
    objects = {field: tuple(sorted(set(values))) for field, values in request['objects'].items()
               if field in used and values}
    return {**request, 'layout': layout, 'objects': objects}


def selection(request):
    return Filters(dimensions=normalized(request)['objects'])


def errors(request, known, candidates, months, versions):
    problems = []
    try:
        clean_layout(request['layout'], known)
    except ValueError as error:
        problems.append(str(error))
    if request['month'] not in months:
        problems.append('原分析月份已不在当前数据中')
    if request['version'] not in versions:
        problems.append('原预算版本已失效')
    for field, values in normalized(request)['objects'].items():
        if field not in known or any(value not in candidates.get(field, ()) for value in values):
            problems.append('分类或对象已失效：' + field)
    return problems


def repaired(request, known, candidates, months, versions, default_month):
    """Prepare valid controls after refresh; caller must not commit this implicitly."""
    result = deepcopy(request)
    result['layout'], _ = clean_layout(result['layout'], known, False)
    result['objects'] = {field: [value for value in values if value in candidates.get(field, ())]
                         for field, values in result['objects'].items() if field in known}
    if result['month'] not in months:
        result['month'] = default_month
    if result['version'] not in versions:
        result['version'] = versions[0]
    return result
