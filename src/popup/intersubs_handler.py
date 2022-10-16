from __future__ import annotations

from typing import TYPE_CHECKING

import intersubs
import intersubs.handler
from intersubs.mpv_intersubs import MPVInterSubs

if TYPE_CHECKING:
    from .dictionary import PopupDictionary


class InterSubsHandler(intersubs.handler.InterSubsHandler):
    def __init__(self, mpv: MPVInterSubs, dictionary: PopupDictionary | None):
        super().__init__(mpv)
        self.dictionary = dictionary

    def on_sub_clicked(self, text: str, idx: int) -> None:
        word = self.lookup_word_from_index(text, idx)
        self.mpv.command("script-message", "create-anki-word-card", word)
