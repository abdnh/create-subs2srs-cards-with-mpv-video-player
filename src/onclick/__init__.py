from __future__ import annotations

from typing import Type

from .dictionary import OnClickDictionary
from .zim_reader import ZIMReaderOnclickDict

dictionaries: list[Type[OnClickDictionary]] = [ZIMReaderOnclickDict]
