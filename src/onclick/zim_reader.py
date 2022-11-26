from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Type

from aqt.qt import *

if TYPE_CHECKING:
    from zim_reader.dictionaries import ZIMDict
    from zim_reader.dictionaries.parser import Parser

from ..utils import find_addon_by_names
from .dictionary import OnClickDictionary


class ZIMReaderDict(OnClickDictionary):
    """ZIM Reader integration (https://github.com/abdnh/anki-zim-reader)"""

    name = "ZIM Reader"
    package_name = "zim_reader"

    def __init__(self, options: dict) -> None:
        self.options = options
        self.mod: Any | None = None
        self._widget: QWidget | None = None
        self.file: Path | None = None
        self.parser: Parser | None = None
        self._init_dict()

    @classmethod
    def is_available(cls) -> bool:
        return bool(find_addon_by_names([cls.package_name, cls.name]))

    def _init_dict(self) -> None:
        self.mod = find_addon_by_names([self.package_name, self.name])

    def get_fields(self) -> list[str]:
        # FIXME: get those fields from ZIM Reader itself instead of hardcoding them here
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
        # FIXME: avoid re-initializing ZIMDict for each card
        zimdict: ZIMDict = self.mod.dictionaries.ZIMDict.from_basedir(file, parser)
        wikientry = zimdict.lookup(word)
        if wikientry:
            # TODO: Use the same formatting used by the ZIM Reader add-on - maybe the add-on should provide a function for that
            note_fields["Definitions"] = "<br>".join(wikientry.definitions)
            note_fields["Examples"] = "<br>".join(wikientry.examples)
            note_fields["Gender"] = wikientry.gender
            note_fields["Part of speech"] = wikientry.pos
            note_fields["Inflection"] = wikientry.inflections
            note_fields["Translation"] = wikientry.translations

    @property
    def widget(self) -> ZIMReaderWidget:
        if self._widget:
            return self._widget
        self._widget = ZIMReaderWidget(self, self.options)
        return self._widget

    def collect_widget_settings(self) -> dict:
        self.file = self.widget.selected_file
        self.parser = self.widget.selected_parser
        return {
            "file": self.file.name,
            "parser": self.widget.selected_parser.name,
        }


class ZIMReaderWidget(QWidget):
    def __init__(self, zim_reader: ZIMReaderDict, options: dict) -> None:
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
        for i, file in enumerate(self.files):
            if options.get("file", None) == file.name:
                self.fileComboBox.setCurrentIndex(i)
        self.parsers: list[Type[Parser]] = zim_reader.mod.dictionaries.PARSER_CLASSES
        self.parserComboBox.addItems([parser.name for parser in self.parsers])
        for i, parser in enumerate(self.parsers):
            if options.get("parser", None) == parser.name:
                self.parserComboBox.setCurrentIndex(i)
        self.setLayout(grid)

    @property
    def selected_file(self) -> Path | None:
        idx = self.fileComboBox.currentIndex()
        if idx >= 0:
            return self.files[idx]
        return None

    @property
    def selected_parser(self) -> Parser | None:
        idx = self.parserComboBox.currentIndex()
        if idx >= 0:
            return self.parsers[idx]()
        return None
