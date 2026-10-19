"""Separate read-only application resources from writable personal data."""
from dataclasses import dataclass
import os
from pathlib import Path
import sys


def is_desktop():
    return os.environ.get('FINANCEBP_DESKTOP') == '1'


@dataclass(frozen=True)
class AppPaths:
    resources: Path
    data: Path

    @property
    def runtime(self): return self.data/'runtime'
    @property
    def logs(self): return self.data/'logs'
    @property
    def exports(self): return self.data/'exports'
    @property
    def backups(self): return self.data/'backups'
    @property
    def profiles(self): return self.data/'profiles'
    @property
    def forecasts(self): return self.data/'forecasts/runs'

    def ensure(self):
        for path in (self.runtime,self.logs,self.exports,self.backups,self.profiles,self.forecasts):
            path.mkdir(parents=True,exist_ok=True)

    @classmethod
    def current(cls):
        resource=os.environ.get('FINANCEBP_RESOURCES_DIR')
        if resource:
            root=Path(resource).resolve()
        elif getattr(sys,'frozen',False):
            root=Path(sys._MEIPASS)/'resources'
        else:
            root=Path(__file__).resolve().parents[2]
        custom=os.environ.get('FINANCEBP_DATA_DIR')
        data=Path(custom).resolve() if custom else (Path(os.environ.get('LOCALAPPDATA',Path.home()/'AppData/Local'))/'FinanceBP' if is_desktop() else root/'outputs')
        return cls(root,data)
