from __future__ import annotations
from importlib import import_module
from types import ModuleType

from aqt import mw


def find_addon_by_names(names: list[str]) -> ModuleType | None:
    for name in mw.addonManager.allAddons():
        if mw.addonManager.addonName(name) in names:
            try:
                return import_module(name)
            except ModuleNotFoundError:
                pass

    return None
