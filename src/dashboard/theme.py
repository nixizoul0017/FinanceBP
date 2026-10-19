"""Approved cockpit palettes and local display preferences, separate from facts."""
from dataclasses import dataclass
import json
import os
from pathlib import Path
import tempfile


@dataclass(frozen=True)
class Palette:
    key: str
    name: str
    primary: str
    sidebar: str
    selected: str
    nav_muted: str
    background: str
    soft: str
    text: str
    muted: str
    border: str
    surface: str = '#FFFFFF'
    success: str = '#227754'
    danger: str = '#BC4945'
    secondary: str = '#B0803F'
    tertiary: str = '#6F8098'


PALETTES = {
    'navy': Palette('navy','深海蓝','#234F7B','#172F4B','#345879','#B7C8DC',
                    '#F3F6FA','#EDF3F9','#192E45','#64758A','#DEE6EF'),
    'teal': Palette('teal','松石青','#167B7C','#163E43','#2C6268','#B0CDD0',
                    '#F2F7F6','#EAF5F3','#203B3E','#5C7579','#DFE9E7'),
    'plum': Palette('plum','石墨紫','#62507A','#302B40','#5D506F','#C3B6D2',
                    '#F6F4F8','#F0EDF5','#332D40','#756B81','#E7E1ED'),
}
from desktop.paths import AppPaths
PREFERENCE_PATH = AppPaths.current().runtime/'ui_preferences.json'


def palette(key):
    return PALETTES.get(key, PALETTES['navy'])


def load_preference(path=None):
    try:
        value = json.loads(Path(path or PREFERENCE_PATH).read_text(encoding='utf-8'))
        key = value.get('theme') if isinstance(value, dict) else None
        return key if isinstance(key, str) and key in PALETTES else 'navy'
    except (OSError, ValueError):
        return 'navy'


def save_preference(key, path=None):
    """A read-only project can still change color for the current session."""
    if not isinstance(key, str) or key not in PALETTES:
        return False
    destination = Path(path or PREFERENCE_PATH)
    temporary = None
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=destination.parent,
                                         prefix='.ui-preference-', suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
            json.dump({'version':1,'theme':key}, stream, ensure_ascii=False)
            stream.write('\n')
        os.replace(temporary, destination)
        return True
    except OSError:
        return False
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


def theme_css(theme):
    styles = Path(__file__).with_name('cockpit.css').read_text(encoding='utf-8')
    tokens = {name: getattr(theme,name) for name in ('primary','sidebar','selected','nav_muted',
              'background','soft','text','muted','border','surface','success','danger')}
    variables = ';'.join(f'--fb-{name.replace("_","-")}:{value}' for name,value in tokens.items())
    return f'<style data-finance-theme="{theme.key}">:root{{{variables}}}\n{styles}\n</style>'
