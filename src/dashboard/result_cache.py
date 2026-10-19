"""Session-only financial results, independent of units, slot order and appearance."""
from copy import deepcopy
import streamlit as st


def cached_result(engine,kind,conditions,compute):
    identity=(engine.entity_id,engine.metadata.get('rule_version'),
              engine.metadata.get('source_fingerprint') or id(engine))
    key=(identity,kind,conditions)
    cache=st.session_state.setdefault('_filter_results',{})
    if key not in cache:
        result=compute()  # Failed computations are never cached.
        if len(cache)>=24:
            cache.pop(next(iter(cache)))
        cache[key]=result
    # Charts and tables may format/sort their copies without changing financial results.
    return deepcopy(cache[key])
