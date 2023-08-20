from abc import ABC, abstractmethod
from typing import Dict, Type

from aqt.qt import QWidget

from .intersubs_handler import InterSubsHandler


class PopupWidget(QWidget):
    def __init__(self, dictionary: "PopupDictionary", options: dict) -> None:
        super().__init__()
        self.dictionary = dictionary
        self.options = options

    def update_options(self, options: Dict) -> None:
        pass


class PopupDictionary(ABC):
    name: str
    intersubs_handler_class: Type[InterSubsHandler] = InterSubsHandler

    def __init__(self, options: Dict) -> None:
        self.options = options

    @classmethod
    @abstractmethod
    def is_available(cls) -> bool:
        raise NotImplementedError(
            "Implement this method to return whether the dictionary is available"
        )

    @property
    @abstractmethod
    def widget(self) -> PopupWidget:
        raise NotImplementedError(
            "Implement this property to return the widget that will be shown to the user to configure the dictionary if needed"
        )

    def collect_widget_settings(self) -> dict:
        """Used to save and collect any settings required for the dictionary from its widget before the widget is closed"""
        return {}
