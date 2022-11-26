from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Type

from aqt.qt import QWidget

from .intersubs_handler import InterSubsHandler


class PopupDictionary(ABC):
    name: str
    intersubs_handler_class: Type[InterSubsHandler] = InterSubsHandler

    @classmethod
    @abstractmethod
    def is_available() -> bool:
        raise NotImplementedError(
            "Implement this method to return whether the dictionary is available"
        )

    @property
    @abstractmethod
    def widget(self) -> QWidget:
        raise NotImplementedError(
            "Implement this property to return the widget that will be shown to the user to configure the dictionary if needed"
        )

    def collect_widget_settings(self) -> dict:
        """Used to save and collect any settings required for the dictionary from its widget before the widget is closed"""
        return
