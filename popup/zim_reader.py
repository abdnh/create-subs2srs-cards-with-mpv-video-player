from __future__ import annotations

from pathlib import Path
import struct
from typing import Any

from aqt.qt import *


from .dictionary import PopupDictionary
from .intersubs_handler import InterSubsHandler
from intersubs.popup import Popup
from ..utils import find_addon_by_names


class ZIMDIctInterSubsHandler(InterSubsHandler):
    def __init__(self, mpv: MPVInterSubs, dictionary: PopupDictionary | None):
        super().__init__(mpv, dictionary)
        self.server: Any | None = None

    def on_popup_created(self, popup: Popup) -> None:
        if self.server:
            return
        self.server = self.dictionary.mod.server.create_server(self.dictionary.file)
        self.server.start()
        # FIXME: we should shut down the server after mpv is closed

    def on_popup_will_show(self, popup: Popup, text: str) -> bool:
        redirected = text
        try:
            redirected = self.dictionary.parser.follow_redirects(
                text, self.server.dictionary
            )
        except struct.error:
            # FIXME: swallow random unpacking errors for now until we find a fix for https://github.com/abdnh/anki-zim-reader/issues/3
            pass
        popup.load(QUrl(f"{self.server.url}/{redirected}"))
        return True


class ZIMReaderPopupDict(PopupDictionary):
    """Pop-up dictionary for ZIM Reader (https://github.com/abdnh/anki-zim-reader)"""

    name = "ZIM Reader"
    package_name = "zim_reader"
    intersubs_handler_class = ZIMDIctInterSubsHandler

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

    @property
    def widget(self) -> ZIMReaderWidget:
        if self._widget:
            return self._widget
        self._widget = ZIMReaderWidget(self)
        return self._widget

    def collect_widget_settings(self) -> None:
        self.file = self.widget.selected_file
        self.parser = self.widget.selected_parser


# Copied from onclick/zim_reader.py with modifications
# TODO: DRY
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
