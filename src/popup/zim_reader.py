from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, Optional, Type, cast

from aqt.qt import *
from intersubs.popup import Popup

if TYPE_CHECKING:
    from zim_reader.dictionaries.parser import Parser
    from zim_reader.server import ZIMServer

from ..utils import find_addon_by_names
from .dictionary import PopupDictionary, PopupWidget
from .intersubs_handler import InterSubsHandler, MPVInterSubs


class ZIMDIctInterSubsHandler(InterSubsHandler):
    def __init__(self, mpv: MPVInterSubs, dictionary: Optional[PopupDictionary]):
        super().__init__(mpv, dictionary)
        self.server: Optional[ZIMServer] = None

    def on_popup_created(self, popup: Popup) -> None:
        if self.server:
            return
        dictionary = cast(ZIMReaderPopupDict, self.dictionary)
        self.server = dictionary.mod.server.create_server(
            dictionary.file, dictionary.parser, follow_redirects=True
        )
        self.server.start()

    def on_popup_will_show(self, popup: Popup, text: str) -> bool:
        text = text.strip()
        popup.load(QUrl(f"{self.server.url}/{text}"))
        return True

    def on_shutdown(self) -> None:
        self.server.shutdown()


class ZIMReaderPopupDict(PopupDictionary):
    """Pop-up dictionary for ZIM Reader (https://github.com/abdnh/anki-zim-reader)"""

    name = "ZIM Reader"
    package_name = "zim_reader"
    intersubs_handler_class = ZIMDIctInterSubsHandler

    def __init__(self, options: dict) -> None:
        super().__init__(options)
        self.mod: Optional[Any] = None
        self._widget: Optional[ZIMReaderWidget] = None
        self.file: Optional[Path] = None
        self.parser: Optional[Parser] = None
        self._init_dict()

    @classmethod
    def is_available(cls) -> bool:
        return bool(find_addon_by_names([cls.package_name, cls.name]))

    def _init_dict(self) -> None:
        self.mod = find_addon_by_names([self.package_name, self.name])

    @property
    def widget(self) -> "ZIMReaderWidget":
        if self._widget:
            return self._widget
        self._widget = ZIMReaderWidget(self, self.options)
        return self._widget

    def collect_widget_settings(self) -> Optional[Dict]:
        if not self.widget.selected_file:
            return None
        self.file = self.widget.selected_file
        self.parser = self.widget.selected_parser
        return {
            "file": self.file.name,
            "parser": self.widget.selected_parser.name,
        }


# Copied from onclick/zim_reader.py with modifications
# TODO: DRY


class ZIMReaderWidget(PopupWidget):
    def __init__(self, dictionary: ZIMReaderPopupDict, options: dict) -> None:
        super().__init__(dictionary, options)
        self.dictionary = dictionary
        grid = QGridLayout()
        grid.addWidget(QLabel("File"), 0, 0)
        self.fileComboBox = QComboBox()
        grid.addWidget(self.fileComboBox, 0, 1)
        grid.addWidget(QLabel("Parser"), 1, 0)
        self.parserComboBox = QComboBox()
        grid.addWidget(self.parserComboBox, 1, 1)
        self.files = dictionary.mod.dictionaries.get_files()
        self.fileComboBox.addItems([file.name for file in self.files])
        self.parsers: list[Type[Parser]] = dictionary.mod.dictionaries.PARSER_CLASSES
        self.parserComboBox.addItems([parser.name for parser in self.parsers])
        self.update_options(options)
        self.setLayout(grid)

    def update_options(self, options: dict) -> None:
        for i, file in enumerate(self.files):
            if options.get("file", None) == file.name:
                self.fileComboBox.setCurrentIndex(i)
        for i, parser in enumerate(self.parsers):
            if options.get("parser", None) == parser.name:
                self.parserComboBox.setCurrentIndex(i)

    @property
    def selected_file(self) -> Optional[Path]:
        idx = self.fileComboBox.currentIndex()
        if idx >= 0:
            return self.files[idx]
        return None

    @property
    def selected_parser(self) -> Optional[Parser]:
        idx = self.parserComboBox.currentIndex()
        if idx >= 0:
            return self.parsers[idx]()
        return None
