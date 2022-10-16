from __future__ import annotations

from typing import Type

from .dictionary import PopupDictionary
from .zim_reader import ZIMReaderPopupDict

dictionaries: list[Type[PopupDictionary]] = [ZIMReaderPopupDict]
