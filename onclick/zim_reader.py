from __future__ import annotations

from pathlib import Path
import struct
from typing import Any

from aqt.qt import *

from .dictionary import OnClickDictionary
from ..utils import find_addon_by_names


class ZIMReaderDict(OnClickDictionary):
    """ZIM Reader integration (https://github.com/abdnh/anki-zim-reader)"""

    name = "ZIM Reader"
    package_name = "zim_reader"

    def __init__(self) -> None:
        self.mod: Any | None = None
        self._widget: QWidget | None = None
        self.file: Path | None = None
        self.parser: Any | None = None
        self._init_dict()

    @classmethod
    def is_available(cls) -> bool:
        return bool(find_addon_by_names([cls.package_name, cls.name]))

    def _init_dict(self) -> None:
        self.mod = find_addon_by_names([self.package_name, self.name])

    def get_fields(self) -> list[str]:
        fields = [
            "Definitions",
            "Examples",
            "Gender",
            "Part of speech",
            "Inflection",
            "Translation",
        ]
        return fields

    def fill_fields(self, word: str, note_fields: dict[str, str]) -> None:
        file = self.file
        parser = self.parser
        if not (file or parser):
            return
        zimdict = self.mod.dictionaries.dictionary.ZIMDict(file, parser)
        try:
            wikientry = zimdict.lookup(word, parser)
        except:
            # FIXME: swallow random unpacking errors for now until we find a fix for https://github.com/abdnh/anki-zim-reader/issues/3
            return
        if wikientry:
            # TODO: Use the same formatting used by the ZIM Reader add-on - maybe the add-on should provide a function for that
            note_fields["Definitions"] = "<br>".join(wikientry.definitions)
            note_fields["Examples"] = "<br>".join(wikientry.examples)
            note_fields["Gender"] = wikientry.gender
            note_fields["Part of speech"] = wikientry.pos
            note_fields["Inflection"] = wikientry.inflections
            note_fields["Definition"] = wikientry.translations

    @property
    def widget(self) -> ZIMReaderWidget:
        if self._widget:
            return self._widget
        self._widget = ZIMReaderWidget(self)
        return self._widget


class ZIMReaderWidget(QWidget):
    def __init__(self, zim_reader: ZIMReaderDict) -> None:
        super().__init__()
        self.zim_reader = zim_reader
        grid = QGridLayout()
        grid.addWidget(QLabel("File"), 0, 0)
        self.fileComboBox = QComboBox()
        grid.addWidget(self.fileComboBox, 0, 1)
        grid.addWidget(QLabel("Parser"), 1, 0)
        self.parserComboBox = QComboBox()
        grid.addWidget(self.parserComboBox, 1, 1)
        self.files = zim_reader.mod.dictionaries.get_files()
        self.fileComboBox.addItems([file.name for file in self.files])
        self.parsers = zim_reader.mod.dictionaries.PARSER_CLASSES
        self.parserComboBox.addItems([parser.name for parser in self.parsers])
        self.setLayout(grid)

    @property
    def selected_file(self) -> Path | None:
        idx = self.fileComboBox.currentIndex()
        if idx >= 0:
            return self.files[idx]
        return None

    @property
    def selected_parser(self) -> Any | None:
        idx = self.parserComboBox.currentIndex()
        if idx >= 0:
            return self.parsers[idx]()
        return None

    def closeEvent(self, event: QCloseEvent) -> None:
        self.zim_reader.file = self.selected_file
        self.zim_reader.parser = self.selected_parser
        return super().closeEvent(event)
