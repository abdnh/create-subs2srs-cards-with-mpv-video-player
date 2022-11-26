from __future__ import annotations

from abc import ABC, abstractmethod

from aqt.qt import QWidget


class OnClickDictionary(ABC):
    name: str

    @classmethod
    @abstractmethod
    def is_available() -> bool:
        raise NotImplementedError(
            "Implement this method to return whether the dictionary is available"
        )

    @abstractmethod
    def get_fields(self) -> list[str]:
        raise NotImplementedError(
            "Implement this method to return a list of note fields supported by the dictionary"
        )

    @abstractmethod
    def fill_fields(self, word: str, note_fields: dict[str, str]) -> None:
        raise NotImplementedError(
            "Implement this method to fill in the fields supported by the dictionary"
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
