# -*- coding: utf-8 -*-

"""
Anki Add-on: mpv2anki

Add new option ("Open Video...") in the Tools menu to open video with MPV (https://mpv.io)
and create subs2srs-like cards.

Default Fields:
   Id            | Back_to_the_Future_(1985)_00.28.16.762 | Back_to_the_Future_(1985)_00.28.15.512-00.28.24.727
   Source        | Back to the Future (1985)
   Time          | 00:28:16.762
   Subtitle      | I, Dr. Emmett Brown, am about to embark on an historic journey.
   Image         | <img src="Back_to_the_Future_(1985)_00.28.16.762.jpg" />
   Audio         | [sound:Back_to_the_Future_(1985)_00.28.15.512-00.28.24.727.mp3]
   Video         | [sound:Back_to_the_Future_(1985)_00.28.15.512-00.28.24.727.webm]
   Video (HTML5) | Back_to_the_Future_(1985)_00.28.15.512-00.28.24.727.webm

The "{{Video (HTML5)}}" can be used to embed a video clip into an Anki card. It works with Anki 2.1 and on AnkiMobile or AnkiDroid.

External SRT subtitles are optional but they're required to populate the "{{Audio}}", "{{Video}}" and "{{Video (HTML5)}}" fields.

If some of the fields aren't necessary, they can be removed from the note type.

Usage Notes:
    - Open a video file via "Open Video..." option (Ctrl+O) in the Tools menu.
    - Press "b" to create an Anki card.

Nickolay <kelciour@gmail.com>
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, Tuple, cast

__version__ = "1.0.0-alpha3"


import glob
import os
import re
import subprocess
import sys
from distutils.spawn import find_executable
from hashlib import sha1
from os.path import expanduser

from anki.hooks import addHook
from anki.lang import langs
from anki.utils import is_lin, is_mac, is_win
from aqt import mw
from aqt.qt import *
from aqt.studydeck import StudyDeck
from aqt.utils import getOnlyText, showText, showWarning

sys.path.append(os.path.join(os.path.dirname(__file__), "vendor"))

import pysubs2
from intersubs.main import run as intersubs_run
from intersubs.mpv import MPVCommandError
from intersubs.mpv_intersubs import MPVInterSubs

from . import onclick, popup
from .onclick import OnClickDictionary
from .popup import PopupDictionary
from .popup.intersubs_handler import InterSubsHandler

SubId = Union[int, Literal["auto", "no"]]

if is_mac and "/usr/local/bin" not in os.environ["PATH"]:
    # https://docs.brew.sh/FAQ#my-mac-apps-dont-find-usrlocalbin-utilities
    os.environ["PATH"] = "/usr/local/bin:" + os.environ["PATH"]

ffmpeg_executable = find_executable("ffmpeg")

langs = [(lang, lc) for lang, lc in langs if not lang.startswith("English")]
langs = sorted(langs + [("English", "en")])


def getTimeParts(seconds: float) -> Tuple[float, float, float, float]:
    mins, secs = divmod(seconds, 60)
    hours, mins = divmod(mins, 60)
    millisecs = int(seconds * 1000) % 1000
    return (hours, mins, secs, millisecs)


def secondsToTimestamp(seconds: float) -> str:
    return "%02d:%02d:%02d.%03d" % getTimeParts(seconds)


def secondsToFilename(seconds: float) -> str:
    return secondsToTimestamp(seconds).replace(":", ".")


def getVideoFile() -> List[QUrl]:
    key = "Media (*.avi *.mkv *.mp4 *.mov *.mpg *.mpeg *.webm *.m4a *.mp3 *.wav);;All Files (*.*)"
    dirkey = "1213145732" + "Directory"
    dirname = mw.pm.profile.get(dirkey, expanduser("~"))
    if qtmajor == 5 and qtminor == 12:
        directory = dirname
    else:
        directory = QUrl.fromLocalFile(dirname)
    urls = QFileDialog.getOpenFileUrls(
        None, "Open Video File or URL", directory=directory, filter=key
    )[0]
    if urls and urls[0].isLocalFile():
        filePath = urls[0].toLocalFile()
        dirname = os.path.dirname(filePath)
        mw.pm.profile[dirkey] = dirname
    return urls


def srt_time_to_seconds(time: str) -> float:
    split_time = time.split(",")
    major, minor = (split_time[0].split(":"), split_time[1])
    return (
        int(major[0]) * 3600 + int(major[1]) * 60 + int(major[2]) + float(minor) / 1000
    )


def seconds_to_srt_time(time: float) -> str:
    return "%02d:%02d:%02d,%03d" % getTimeParts(time)


srt_encodings = ["utf-8", "cp1251"]


def fix_glob_square_brackets(glob_pattern: str) -> str:
    # replace the left square bracket with [[]
    glob_pattern = re.sub(r"\[", "[[]", glob_pattern)
    # replace the right square bracket with []] but be careful not to replace
    # the right square brackets in the left square bracket's 'escape' sequence.
    glob_pattern = re.sub(r"(?<!\[)\]", "[]]", glob_pattern)

    return glob_pattern


class SubtitlesHelper:
    def __init__(self, configManager: "ConfigManager"):
        self.settings = configManager.getSettings()
        self.sub_delay = 0.0

    sub_exts = [".srt", ".ass", ".vtt"]

    def init(self, filePath: str) -> None:
        self.filePath = filePath
        self.subsPath = None
        self.translationsPath = None
        self.status_code = "success"

        self.subs = []
        self.translations = []

        subs_base_path = os.path.splitext(self.filePath)[0]
        if self.settings["subs_target_language_code"]:
            subs_list = self.find_subtitles(
                subs_base_path, self.settings["subs_target_language_code"]
            )
            if len(subs_list) > 0:
                self.subsPath = subs_list[0]
                self.subs = self.read_subtitles(self.subsPath)

        if not self.subs:
            for ext in self.sub_exts:
                if os.path.isfile(subs_base_path + ext):
                    self.subsPath = subs_base_path + ext
                    self.subs = self.read_subtitles(self.subsPath)
                    break

        if self.settings["subs_native_language_code"]:
            subs_list = self.find_subtitles(
                subs_base_path, self.settings["subs_native_language_code"]
            )
            if len(subs_list) > 0:
                self.translationsPath = subs_list[0]
                self.translations = self.read_subtitles(self.translationsPath)

        if len(self.subs) != 0 and self.settings["subs_target_language_code"] == "en":
            self.convert_into_sentences()

        if len(self.translations) != 0:
            self.sync_subtitles()

    def find_subtitles(self, subs_base_path: str, lang: str = "") -> List[str]:
        subs_list = []
        for ext in self.sub_exts:
            subs_filepattern = subs_base_path + "*" + lang + "*" + ext
            subs_filepattern = fix_glob_square_brackets(subs_filepattern)
            subs_list.extend(glob.glob(subs_filepattern))
        return subs_list

    def guess_encoding(self, file_content: bytes) -> Tuple[bool, str]:
        for enc in srt_encodings:
            try:
                content = file_content.decode(enc)
                return (True, enc)
            except UnicodeDecodeError:
                pass
        return (False, None)

    def read_subtitles(self, subsPath: str) -> List[Tuple[float, float, str]]:
        with open(subsPath, "rb") as file:
            content = file.read()
            if content[:3] == b"\xef\xbb\xbf":  # with bom
                content = content[3:]

            ret_code, enc = self.guess_encoding(content)
            if not ret_code:
                showWarning(
                    "Can't decode subtitles. Please convert subtitles to UTF-8 encoding."
                )

        try:
            subs = pysubs2.load(subsPath, encoding=enc)
        except Exception as e:
            showWarning(
                "An error occurred while parsing the subtitle file:\n'%s'.\n\n%s"
                % (os.path.basename(subsPath), e),
                parent=mw,
            )
            self.status_code = "error"
            return []

        subs2 = []
        for line in subs:
            subs2.append((line.start / 1000, line.end / 1000, line.text))

        subs = []
        for sub_start, sub_end, sub_text in subs2:
            sub_chunks = sub_text.split("\\N")
            sub_content = "\n".join(sub_chunks).replace("\t", " ")
            sub_content = re.sub(r"<[^>]+>", "", sub_content)
            sub_content = re.sub(r"^-", r"- ", sub_content)
            sub_content = re.sub(
                r"(\W)-([^\W])", r"\1 - \2", sub_content, flags=re.UNICODE
            )
            sub_content = re.sub(r"  +", " ", sub_content)
            sub_content = sub_content.replace("\n", " ").strip()
            if len(sub_content) > 0:
                subs.append((sub_start, sub_end, sub_content))

        return subs

    def remove_tags(self, sub: str) -> str:
        sub = re.sub(r"<[^>]+>", "", sub)
        sub = re.sub(r"  +", " ", sub)
        sub = sub.strip()

        return sub

    def convert_into_sentences(self) -> None:
        subs: List[Tuple[float, float, str]] = []

        for sub in self.subs:
            sub_start = sub[0]
            sub_end = sub[1]
            sub_content = sub[2]

            if len(subs) > 0:
                prev_sub_start = subs[-1][0]
                prev_sub_end = subs[-1][1]
                prev_sub_content = subs[-1][2]

                if (
                    (sub_start - prev_sub_end) <= 2
                    and (sub_end - prev_sub_start) < 15
                    and sub_content[0] not in ['"', "'", "(", "[", "-", "“", "♪"]
                    and (
                        prev_sub_content[-1] not in [".", "!", "?", ")", "]", "”", '"']
                        or (
                            prev_sub_content[-3:] == "..."
                            and (
                                sub_content[:3] == "..."
                                or sub_content[0].islower()
                                or re.match(r"^I\b", sub_content)
                            )
                        )
                    )
                ):
                    subs[-1] = (
                        prev_sub_start,
                        sub_end,
                        prev_sub_content + " " + sub_content,
                    )
                else:
                    subs.append((sub_start, sub_end, sub_content))
            else:
                subs.append((sub_start, sub_end, sub_content))

        self.subs = subs

    def sync_subtitles(self) -> None:
        en_subs = self.subs
        ru_subs = self.translations

        subs: List[Tuple[List, List, List]] = [
            ([], [], []) for i in range(len(en_subs))
        ]
        for ru_sub in ru_subs:
            ru_sub_start = ru_sub[0]
            ru_sub_end = ru_sub[1]

            for idx, en_sub in enumerate(en_subs):
                en_sub_start = en_sub[0]
                en_sub_end = en_sub[1]

                if en_sub_start < ru_sub_end and en_sub_end > ru_sub_start:
                    sub_start = (
                        en_sub_start if en_sub_start > ru_sub_start else ru_sub_start
                    )
                    sub_end = en_sub_end if ru_sub_end > en_sub_end else ru_sub_end

                    if (sub_end - sub_start) / (ru_sub_end - ru_sub_start) > 0.25:
                        subs[idx][0].append(ru_sub[0])
                        subs[idx][1].append(ru_sub[1])
                        subs[idx][2].append(ru_sub[2])
                        break

        self.translations = []
        for idx, sub in enumerate(subs):
            if len(sub[2]) == 0:
                self.translations.append((self.subs[idx][0], self.subs[idx][1], ""))
            else:
                self.translations.append((sub[0][0], sub[1][-1], " ".join(sub[2])))

        idx = 0
        while idx < len(self.subs) and len(self.subs) > 1:
            if self.translations[idx][2] == "":
                en_sub_start = self.subs[idx][0]
                en_sub_end = self.subs[idx][1]

                ru_prev_sub_start = 0.0
                ru_prev_sub_end = 0.0
                ru_next_sub_start = 0.0
                ru_next_sub_end = 0.0

                if idx > 0:
                    ru_prev_sub_start = self.translations[idx - 1][0]
                    ru_prev_sub_end = self.translations[idx - 1][1]

                if idx < len(self.subs) - 1:
                    ru_next_sub_start = self.translations[idx + 1][0]
                    ru_next_sub_end = self.translations[idx + 1][1]

                if idx == len(self.subs) - 1:
                    self.subs[idx - 1] = (
                        self.subs[idx - 1][0],
                        self.subs[idx][1],
                        self.subs[idx - 1][2] + " " + self.subs[idx][2],
                    )
                elif en_sub_end <= ru_next_sub_start and idx > 0:
                    self.subs[idx - 1] = (
                        self.subs[idx - 1][0],
                        self.subs[idx][1],
                        self.subs[idx - 1][2] + " " + self.subs[idx][2],
                    )
                elif (
                    en_sub_start >= ru_next_sub_start or en_sub_start >= ru_prev_sub_end
                ):
                    self.subs[idx + 1] = (
                        self.subs[idx][0],
                        self.subs[idx + 1][1],
                        self.subs[idx][2] + " " + self.subs[idx + 1][2],
                    )
                elif (ru_prev_sub_end - en_sub_start) > (
                    en_sub_end - ru_next_sub_start
                ) and idx > 0:
                    self.subs[idx - 1] = (
                        self.subs[idx - 1][0],
                        self.subs[idx][1],
                        self.subs[idx - 1][2] + " " + self.subs[idx][2],
                    )
                else:
                    self.subs[idx + 1] = (
                        self.subs[idx][0],
                        self.subs[idx + 1][1],
                        self.subs[idx][2] + " " + self.subs[idx + 1][2],
                    )

                del self.subs[idx]
                del self.translations[idx]
            else:
                idx += 1

    def filter_subtitles(
        self, clip_start: float, clip_end: float, pad_start: float, pad_end: float
    ) -> List[Tuple[float, float, str]]:
        subs_filtered = []

        for sub_start, sub_end, sub_content in self.subs:
            if sub_end > (clip_start + pad_start) and sub_start < (clip_end - pad_end):
                subs_filtered.append(
                    (sub_start - clip_start, sub_end - clip_start, sub_content)
                )

            if sub_start > clip_end:
                break

        return subs_filtered

    def write_subtitles(
        self,
        clip_start: float,
        clip_end: float,
        pad_start: float,
        pad_end: float,
        filename: str,
    ) -> None:
        subs = self.filter_subtitles(
            clip_start - self.sub_delay, clip_end - self.sub_delay, pad_start, pad_end
        )

        with open(filename, "w", encoding="utf-8") as file:
            for idx, sub in enumerate(subs):
                file.write(str(idx + 1) + "\n")
                file.write(
                    seconds_to_srt_time(sub[0])
                    + " --> "
                    + seconds_to_srt_time(sub[1])
                    + "\n"
                )
                file.write(sub[2] + "\n")
                file.write("\n")

    def get_subtitle_id(self, time_pos: float) -> Optional[int]:
        time_pos = time_pos - self.sub_delay
        for sub_id, (sub_start, sub_end, sub_content) in enumerate(self.subs):
            if sub_start <= time_pos <= sub_end:
                return sub_id
        return None

    def get_subtitle(
        self, sub_id: int, translation: bool = False
    ) -> Tuple[Optional[float], Optional[float], str]:
        if (
            sub_id < 0
            or sub_id > len(self.subs) - 1
            or (translation is True and len(self.translations) == 0)
        ):
            return (None, None, "")
        if not translation:
            return self.subs[sub_id]
        return self.translations[sub_id]

    def get_prev_subtitle(
        self, sub_id: int, translation: bool = False
    ) -> Tuple[float, float, str]:
        if sub_id <= 0 or (translation is True and len(self.translations) == 0):
            return (self.subs[0][0], self.subs[0][1], "")
        sub_start, sub_end, sub_text = self.subs[sub_id]
        prev_sub_start, prev_sub_end, prev_sub_text = self.subs[sub_id - 1]
        if sub_start - prev_sub_end > 5:
            return (sub_start, sub_end, "")
        if not translation:
            return self.subs[sub_id - 1]
        return self.translations[sub_id - 1]

    def get_next_subtitle(
        self, sub_id: int, translation: bool = False
    ) -> Tuple[float, float, str]:
        if sub_id >= len(self.subs) - 1 or (
            translation is True and len(self.translations) == 0
        ):
            return (self.subs[-1][0], self.subs[-1][1], "")
        sub_start, sub_end, sub_text = self.subs[sub_id]
        next_sub_start, next_sub_end, next_sub_text = self.subs[sub_id + 1]
        if next_sub_start - sub_end > 5:
            return (sub_start, sub_end, "")
        if not translation:
            return self.subs[sub_id + 1]
        return self.translations[sub_id + 1]


class ConfigManager:
    def __init__(self) -> None:
        self.onClickDict: Optional[OnClickDictionary] = None
        self.popupDict: Optional[PopupDictionary] = None
        self.config = mw.addonManager.getConfig(__name__)
        self.defaults = mw.addonManager.addonConfigDefaults(
            mw.addonManager.addonFromModule(__name__)
        )

    def save(self, preset: str) -> None:
        self.config["default_preset"] = preset
        mw.addonManager.writeConfig(__name__, self.config)

    def setConfiguredPreset(self, preset: str) -> None:
        self.config["default_preset"] = preset

    def getConfiguredPreset(self) -> str:
        return self.config["default_preset"]

    def getPresetNames(self) -> list[str]:
        return list(self.config["presets"].keys())

    def addNewPreset(self, preset: str) -> None:
        self.config["presets"][preset] = self.defaults["presets"]["Default"]

    def getSettings(self) -> Dict[str, Any]:
        return self.config["presets"][self.getConfiguredPreset()]

    def getFields(self, forDisplay: bool = False) -> List[str]:
        fields = [
            "<ignored>",
            "Id",
            "Word",
            "Source",
            "Path",
            "Time",
            "Image",
            "Image (with subtitles)",
            "Line",
            "Line: before",
            "Line: after",
            "Meaning: line",
            "Meaning: line before",
            "Meaning: line after",
            "Audio",
            "Audio (with context)",
            "Video",
            "Video (with context)",
            "Video (HTML5)",
            "Video (HTML5 with context)",
            "Video Subtitles",
            "[webm] Video",
            "[webm] Video (with context)",
            "[webm] Video (HTML5)",
            "[webm] Video (HTML5 with context)",
        ]
        if self.onClickDict:
            onclick_fields = self.onClickDict.get_fields()
            if forDisplay:
                # Append the dictionary name to the fields
                for i, field in enumerate(onclick_fields):
                    onclick_fields[i] = f"{self.onClickDict.name} {field}"
            fields += onclick_fields
        return fields

    def updateMapping(self, model: str, data: Dict) -> None:
        self.getSettings()["mapping"][model] = data

    def getFieldsMapping(self, model: str) -> Dict:
        return self.getSettings()["mapping"].get(model, {})


# Fix for ... cannot be converted to PyQt5.QtCore.QObject in this context
class MessageHandler(QObject):
    create_anki_card = pyqtSignal(str, float, float, float, str)
    update_file_path = pyqtSignal(str)


class MPVMonitor(MPVInterSubs):
    def __init__(
        self,
        executable: str,
        popenEnv: Dict[str, str],
        fileUrls: List[str],
        mpvConf: str,
        msgHandler: MessageHandler,
        subsManager: SubtitlesHelper,
        popupDict: Optional[PopupDictionary] = None,
    ):
        self.executable = executable
        self.popenEnv = popenEnv
        self.subsManager = subsManager
        self.mpvConf = mpvConf
        self.msgHandler = msgHandler

        ytdl_opts = '--ytdl-raw-options=write-sub=,write-auto-sub=,sub-format="ass/srt/vtt/best"'
        if any("youtube.com" in l for l in fileUrls):
            # Download only native and target languages' auto-generated subs for YouTube
            sub_langs = list(
                filter(
                    None,
                    [
                        self.subsManager.settings["subs_native_language_code"],
                        self.subsManager.settings["subs_target_language_code"],
                    ],
                )
            )
            ytdl_opts += ',sub-lang="%s"' % ",".join(sub_langs)
        self.default_argv += [ytdl_opts]

        super().__init__()
        # super().__init__(window_id=None, debug=False)

        self.audio_id = "auto"
        self.audio_ffmpeg_id = 0
        self.sub_id: SubId = "auto"
        self.audio_delay = 0.0

        self.set_property("include", self.mpvConf)

        self.command(
            "load-script",
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "mpv2anki.lua"),
        )

        if popupDict:
            handler = popupDict.intersubs_handler_class(self, popupDict)
        else:
            handler = InterSubsHandler(self, None)
        intersubs_settings = {
            "alternative_triggers": self.subsManager.settings["alt_dict_keys"]
        }
        intersubs_run(
            fileUrls, app=mw.app, mpv=self, handler=handler, settings=intersubs_settings
        )

    def on_property_term_status_msg(self, statusMsg: str = "") -> None:
        m = re.match(
            r"^\[mpv2anki\] ([^#]+) # ([^#]+) # ([^#]+) # (.*?) # (.*)$",
            statusMsg,
            re.DOTALL,
        )
        if m:
            timePos, timeStart, timeEnd, word, subText = m.groups()
            self.msgHandler.create_anki_card.emit(
                word, float(timePos), float(timeStart), float(timeEnd), subText
            )

    def on_property_aid(self, audio_id: Any = None) -> None:
        self.audio_id = audio_id
        if audio_id is None:
            self.audio_ffmpeg_id = 0
        elif audio_id == "auto":
            track_count = int(self.get_property("track-list/count"))
            for i in range(0, track_count):
                track_type = self.get_property("track-list/%d/type" % i)
                track_index = int(self.get_property("track-list/%d/ff-index" % i))
                track_selected = self.get_property("track-list/%d/selected" % i)

                if track_type == "audio" and track_selected == "yes":
                    self.audio_ffmpeg_id = track_index
                    break
        else:
            self.audio_ffmpeg_id = int(self.audio_id) - 1

    def on_property_sid(self, sub_id: SubId = None) -> None:
        self.sub_id = sub_id if sub_id is not False else "no"

    def on_property_sub_delay(self, val: Any) -> None:
        self.subsManager.sub_delay = round(float(val), 3)

    def on_property_audio_delay(self, val: Any) -> None:
        self.audio_delay = round(float(val), 3)

    def on_start_file(self, msg: Any) -> None:
        self.filePath = self.get_property("path")
        self.subsManager.init(self.filePath)
        if self.subsManager.subsPath:
            self.command("sub-add", self.subsManager.subsPath)
        if self.subsManager.translationsPath:
            self.command("sub-add", self.subsManager.translationsPath)
        self.msgHandler.update_file_path.emit(self.filePath)
        if not self.get_property("vo-configured"):
            self.set_property("force-window", "yes")

        audio_delay = self.subsManager.settings["av_delay"]
        if audio_delay:
            self.set_property("audio-delay", audio_delay)

    def on_shutdown(self, msg: Any = None) -> None:
        try:
            self.close()
        except Exception:
            # Ignore pywintypes.error: (232, 'WriteFile', 'The pipe is being closed.')
            pass


class AnkiHelper(QObject):
    def __init__(
        self,
        executable: str,
        popenEnv: Dict[str, str],
        fileUrls: List[str],
        configManager: ConfigManager,
    ):
        QObject.__init__(self, mw)
        self.configManager = configManager
        self.subsManager = SubtitlesHelper(configManager)

        self.msgHandler = MessageHandler()
        qconnect(self.msgHandler.create_anki_card, self.createAnkiCard)
        qconnect(self.msgHandler.update_file_path, self.updateFilePath)

        self.mpvConf = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "user_files", "mpv.conf"
        )
        self.mpvExecutable = executable
        self.mpvManager = MPVMonitor(
            executable,
            popenEnv,
            fileUrls,
            self.mpvConf,
            self.msgHandler,
            self.subsManager,
            self.configManager.popupDict,
        )

        self.settings = self.configManager.getSettings()
        self.popenEnv = popenEnv

        self.initFieldsMapping()

        addHook("unloadProfile", self.mpvManager.on_shutdown)

    def initFieldsMapping(self) -> None:
        self.fieldsMap = {}

        fieldsMapDefault: Dict[str, Any] = {}
        for k, v in self.configManager.getFieldsMapping(self.settings["model"]).items():
            if v not in fieldsMapDefault:
                fieldsMapDefault[v] = []
            fieldsMapDefault[v].append(k)
        self.fieldsMap["model"] = fieldsMapDefault

    def updateFilePath(self, filePath: str) -> None:
        self.filePath = filePath
        if "://" not in self.filePath:
            self.is_local_file = True
        else:
            self.is_local_file = False

    def createAnkiCard(
        self, word: str, timePos: float, timeStart: float, timeEnd: float, subText: str
    ) -> None:
        self.addNewCard(word, timePos, timeStart, timeEnd, subText)

    def format_filename(self, filename: str) -> str:
        if not self.is_local_file or re.search(r'[\\/:"*?<>|]+', filename):
            filename = sha1(filename.encode("utf-8")).hexdigest()
        else:
            filename = filename.replace("[", "").replace("]", "").replace(" ", "_")
            filename = re.sub(r"^[_-]+", "", filename)
            filename = filename.strip()
        return filename

    def subprocess_image(
        self,
        source: str,
        timePos: float,
        subprocess_calls: List[list[str]],
        sub: SubId = "no",
        suffix: str = "",
    ) -> str:
        image = "%s_%s%s.jpg" % (
            self.format_filename(source),
            secondsToFilename(timePos),
            suffix,
        )
        imagePath = os.path.join(mw.col.media.dir(), image)
        if not self.settings["use_mpv"] and ffmpeg_executable and sub is None:
            argv = ["ffmpeg", "-y"]
            argv += ["-ss", secondsToTimestamp(timePos)]
            argv += ["-i", self.filePath]
            argv += ["-vframes", "1"]
            argv += [imagePath]
        else:
            argv = [self.mpvExecutable, self.filePath]
            argv += ["--include=%s" % self.mpvConf]
            argv += ["--start=%s" % secondsToTimestamp(timePos)]
            argv += ["--audio=no"]
            argv += ["--sub=%s" % sub]
            argv += ["--sub-visibility=yes"]
            argv += ["--sub-delay=%f" % self.subsManager.sub_delay]
            argv += ["--audio-delay=%f" % self.mpvManager.audio_delay]
            argv += ["--frames=1"]
            argv += [
                "--vf-add=lavfi-scale=%s:%s"
                % (self.settings["image_width"], self.settings["image_height"])
            ]
            argv += ["--vf-add=format=fmt=yuvj422p"]
            argv += ["--ovc=mjpeg"]
            argv += ["--o=%s" % imagePath]
        subprocess_calls.append(argv)
        return image

    def subprocess_audio(
        self,
        source: str,
        sub_start: float,
        sub_end: float,
        aid: int,
        aid_ff: int,
        subprocess_calls: List[List[str]],
    ) -> str:
        audio = "%s_%s-%s.%s" % (
            self.format_filename(source),
            secondsToFilename(sub_start),
            secondsToFilename(sub_end),
            self.settings["audio_ext"],
        )
        audioPath = os.path.join(mw.col.media.dir(), audio)
        if not self.settings["use_mpv"] and ffmpeg_executable:
            argv = ["ffmpeg", "-y"]
            argv += ["-ss", secondsToTimestamp(sub_start)]
            argv += ["-i", self.filePath]
            argv += ["-t", secondsToTimestamp(sub_end - sub_start)]
            argv += ["-map", "0:a:%d" % aid_ff]
            argv += [
                "-af",
                "afade=t=in:st={:.3f}:d={:.3f},afade=t=out:st={:.3f}:d={:.3f}".format(
                    0, 0.25, sub_end - sub_start - 0.25, 0.25
                ),
            ]
            argv += ["-vn"]
            argv += [audioPath]
        else:
            argv = [self.mpvExecutable, self.filePath]
            argv += ["--include=%s" % self.mpvConf]
            audio_delay = self.mpvManager.audio_delay
            sub_start -= audio_delay
            sub_end -= audio_delay
            argv += [
                "--start=%s" % secondsToTimestamp(sub_start),
                "--end=%s" % secondsToTimestamp(sub_end),
            ]
            argv += ["--aid=%d" % aid]
            argv += ["--video=no"]
            argv += [
                "--af=afade=t=in:st=%s:d=%s,afade=t=out:st=%s:d=%s"
                % (sub_start, 0.25, sub_end - 0.25, 0.25)
            ]
            argv += ["--o=%s" % audioPath]
        subprocess_calls.append(argv)
        return audio

    def get_video_filename(
        self, source: str, sub_start: float, sub_end: float, video_format: str
    ) -> str:
        video = "%s_%s-%s.%s" % (
            self.format_filename(source),
            secondsToFilename(sub_start),
            secondsToFilename(sub_end),
            video_format,
        )
        return video

    def subprocess_video(
        self,
        source: str,
        sub_start: float,
        sub_end: float,
        aid: int,
        aid_ff: int,
        video_format: str,
        subprocess_calls: List[List[str]],
    ) -> str:
        video = self.get_video_filename(source, sub_start, sub_end, video_format)
        videoPath = os.path.join(mw.col.media.dir(), video)
        if not self.settings["use_mpv"] and ffmpeg_executable:
            argv = ["ffmpeg", "-y"]
            argv += ["-ss", secondsToTimestamp(sub_start)]
            argv += ["-i", self.filePath]
            argv += ["-t", secondsToTimestamp(sub_end - sub_start)]
            argv += ["-map", "0:v:0"]
            argv += ["-map", "0:a:%d" % aid_ff]
            argv += [
                "-af",
                "afade=t=in:st={:.3f}:d={:.3f},afade=t=out:st={:.3f}:d={:.3f}".format(
                    0, 0.25, sub_end - sub_start - 0.25, 0.25
                ),
            ]
            argv += [
                "-vf",
                "scale=%d:%d"
                % (self.settings["video_width"], self.settings["video_height"]),
            ]
            if video_format == "webm":
                argv += ["-c:v", "libvpx-vp9"]
                argv += ["-b:v", "1400K", "-threads", "8", "-speed", "2", "-crf", "23"]
            argv += [videoPath]
        else:
            argv = [self.mpvExecutable, self.filePath]
            argv += ["--include=%s" % self.mpvConf]
            argv += [
                "--start=%s" % secondsToTimestamp(sub_start),
                "--end=%s" % secondsToTimestamp(sub_end),
            ]
            argv += ["--sub=no"]
            argv += ["--aid=%d" % aid]
            # FIXME: audio-delay can cause muteness for the duration of the vido, especially in output mode
            argv += ["--audio-delay=%s" % self.mpvManager.audio_delay]
            argv += [
                "--af-add=afade=t=in:st=%s:d=%s,afade=t=out:st=%s:d=%s"
                % (sub_start, 0.25, sub_end - 0.25, 0.25)
            ]
            argv += [
                "--vf-add=lavfi-scale=%s:%s"
                % (self.settings["video_width"], self.settings["video_height"])
            ]
            if video_format == "webm":
                argv += ["--ovc=libvpx-vp9"]
                argv += ["--ovcopts=b=1400K,threads=4,crf=23,qmin=0,qmax=36,speed=2"]
            argv += ["--o=%s" % videoPath]
        subprocess_calls.append(argv)
        return video

    # anki.utils.call() with bundle libs if mpv is packaged
    def call(self, argv: List[str]) -> None:
        if is_win:
            si = subprocess.STARTUPINFO()  # type: ignore[attr-defined, unused-ignore]
            try:
                si.dwFlags |= subprocess.STARTF_USESHOWWINDOW  # type: ignore[attr-defined, unused-ignore]
            except:
                # pylint: disable=no-member
                si.dwFlags |= subprocess._subprocess.STARTF_USESHOWWINDOW  # type: ignore[attr-defined, unused-ignore]
        else:
            si = None

        subprocess.Popen(argv, startupinfo=si, env=self.popenEnv)

    def addNewCard(
        self, word: str, timePos: float, timeStart: float, timeEnd: float, subText: str
    ) -> None:
        noteFields = {k: "" for k in self.configManager.getFields()}

        model = mw.col.models.by_name(self.settings["model"])
        mw.col.models.set_current(model)

        noteFields["Word"] = word
        if self.configManager.onClickDict:
            self.configManager.onClickDict.fill_fields(word, noteFields)

        source = os.path.basename(self.filePath)
        source = os.path.splitext(source)[0]
        noteFields["Source"] = source

        path = os.path.basename(self.filePath)
        noteFields["Path"] = self.filePath

        note = mw.col.newNote(forDeck=False)

        subTranslation = ""

        subText_before = ""
        subText_after = ""

        subTranslation_before = ""
        subTranslation_after = ""

        sub_start = -1.0
        sub_end = -1.0

        sub_pad_start = self.settings["pad_start"] / 1000.0
        sub_pad_end = self.settings["pad_end"] / 1000.0

        if timeStart >= 0 and timeEnd == -1:
            if timePos - timeStart > 60:
                self.mpvManager.command(
                    "show-text", "Error: Card duration > 60 seconds."
                )
                return
            timeEnd = timePos

        if timeStart >= 0:
            subTime = timeStart + (timeEnd - timeStart) / 2
            sub_id = self.subsManager.get_subtitle_id(subTime)
        else:
            sub_id = self.subsManager.get_subtitle_id(timePos)

        if timeStart == -1 and timeEnd == -1:  # mpv >= v0.30.0
            try:
                sub_start = float(self.mpvManager.get_property("sub-start"))
                sub_end = float(self.mpvManager.get_property("sub-end"))

                sub_start += -sub_pad_start + self.subsManager.sub_delay
                sub_end += sub_pad_end + self.subsManager.sub_delay
            except MPVCommandError:
                pass

        if sub_id is not None:
            sub_start, sub_end, subText = self.subsManager.get_subtitle(sub_id)
            subTranslation = self.subsManager.get_subtitle(sub_id, translation=True)[2]

            (
                prev_sub_start,
                prev_sub_end,
                subText_before,
            ) = self.subsManager.get_prev_subtitle(sub_id)
            (
                next_sub_start,
                next_sub_end,
                subText_after,
            ) = self.subsManager.get_next_subtitle(sub_id)

            subTranslation_before = self.subsManager.get_prev_subtitle(
                sub_id, translation=True
            )[2]
            subTranslation_after = self.subsManager.get_next_subtitle(
                sub_id, translation=True
            )[2]

            sub_start += -sub_pad_start + self.subsManager.sub_delay
            sub_end += sub_pad_end + self.subsManager.sub_delay

            prev_sub_start += -sub_pad_start + self.subsManager.sub_delay
            next_sub_end += sub_pad_end + self.subsManager.sub_delay

        if timeStart >= 0 and timeEnd >= 0:
            sub_start = timeStart
            sub_end = timeEnd

            sub_pad_start = 0
            sub_pad_end = 0

        if sub_start >= 0 and sub_end >= 0:
            noteId = "%s_%s-%s" % (
                self.format_filename(source),
                secondsToFilename(sub_start),
                secondsToFilename(sub_end),
            )
        else:
            noteId = "%s_%s" % (
                self.format_filename(source),
                secondsToFilename(timePos),
            )

        noteFields["Id"] = noteId
        noteFields["Line"] = subText
        noteFields["Line: before"] = subText_before
        noteFields["Line: after"] = subText_after
        noteFields["Meaning: line"] = subTranslation
        noteFields["Meaning: line before"] = subTranslation_before
        noteFields["Meaning: line after"] = subTranslation_after

        noteFields["Time"] = secondsToTimestamp(timePos)

        subprocess_calls: List[List[str]] = []

        aid = cast(int, self.mpvManager.audio_id)
        aid_ff = self.mpvManager.audio_ffmpeg_id
        sid = cast(Optional[int], self.mpvManager.sub_id)

        fieldsMap = self.fieldsMap["model"]

        video = None

        if "Image" in fieldsMap:
            image = self.subprocess_image(source, timePos, subprocess_calls)
            noteFields["Image"] = '<img src="%s" />' % image

        if "Image (with subtitles)" in fieldsMap:
            image_with_subtitles = self.subprocess_image(
                source, timePos, subprocess_calls, sub=sid, suffix="_S"
            )
            noteFields["Image (with subtitles)"] = (
                '<img src="%s" />' % image_with_subtitles
            )

        if sub_start >= 0 and sub_end >= 0:
            if "Audio" in fieldsMap:
                audio = self.subprocess_audio(
                    source, sub_start, sub_end, aid, aid_ff, subprocess_calls
                )
                noteFields["Audio"] = "[sound:%s]" % audio

            if "Video" in fieldsMap or "Video (HTML5)" in fieldsMap:
                video = self.subprocess_video(
                    source, sub_start, sub_end, aid, aid_ff, "mp4", subprocess_calls
                )
                noteFields["Video"] = "[sound:%s]" % video
                noteFields["Video (HTML5)"] = video

            if "[webm] Video" in fieldsMap or "[webm] Video (HTML5)" in fieldsMap:
                video = self.subprocess_video(
                    source, sub_start, sub_end, aid, aid_ff, "webm", subprocess_calls
                )
                noteFields["[webm] Video"] = "[sound:%s]" % video
                noteFields["[webm] Video (HTML5)"] = video

        if sub_id is not None:
            if "Audio (with context)" in fieldsMap:
                audio = self.subprocess_audio(
                    source, prev_sub_start, next_sub_end, aid, aid_ff, subprocess_calls
                )
                noteFields["Audio (with context)"] = "[sound:%s]" % audio

            is_context = False

            if (
                "Video (with context)" in fieldsMap
                or "Video (HTML5 with context)" in fieldsMap
            ):
                video = self.subprocess_video(
                    source,
                    prev_sub_start,
                    next_sub_end,
                    aid,
                    aid_ff,
                    "mp4",
                    subprocess_calls,
                )
                noteFields["Video (with context)"] = "[sound:%s]" % video
                noteFields["Video (HTML5 with context)"] = video
                is_context = True

            if (
                "[webm] Video (with context)" in fieldsMap
                or "[webm] Video (HTML5 with context)" in fieldsMap
            ):
                video = self.subprocess_video(
                    source,
                    prev_sub_start,
                    next_sub_end,
                    aid,
                    aid_ff,
                    "webm",
                    subprocess_calls,
                )
                noteFields["[webm] Video (with context)"] = "[sound:%s]" % video
                noteFields["[webm] Video (HTML5 with context)"] = video
                is_context = True

            if "Video Subtitles" in fieldsMap:
                if video is None:
                    video = self.get_video_filename(source, sub_start, sub_end, "mp4")
                subtitles = os.path.splitext(video)[0] + ".srt"
                subtitlesPath = os.path.join(mw.col.media.dir(), subtitles)
                noteFields["Video Subtitles"] = "[sound:%s]" % subtitles

        for k, v in fieldsMap.items():
            val = noteFields.get(k, None)
            if val:
                for field in v:
                    note[field] = val

        ret = note.dupeOrEmpty()
        if ret == 2:
            self.mpvManager.command("show-text", "Error: Card already exists.")
            return

        did = mw.col.decks.id(self.settings["deck"])
        note.note_type()["did"] = did

        if mw.state == "deckBrowser":
            mw.col.decks.select(did)

        for p in subprocess_calls:
            if os.environ.get("DEBUG"):
                p_debug = p[:1] + ["-v"] + p[1:]
                print(
                    "DEBUG:",
                    " ".join(['"{}"'.format(s) if " " in s else s for s in p_debug]),
                )
            self.call(p)

        if sub_id is not None and "Video Subtitles" in fieldsMap:
            self.subsManager.write_subtitles(
                sub_start, sub_end, sub_pad_start, sub_pad_end, subtitlesPath
            )

        cards = mw.col.addNote(note)
        if cards == 0:
            self.mpvManager.command("show-text", "Error: No cards added.")
        else:
            if is_mac:
                self.mpvManager.command("expand-properties", "show-text", "Added.")
            else:
                self.mpvManager.command(
                    "expand-properties",
                    "show-text",
                    "${osd-ass-cc/0}{\\fscx150\\fscy150}✔",
                )
        mw.reset()


class FieldMapping(QDialog):
    def __init__(self, name: str, configManager: ConfigManager, parent: "MainWindow"):
        QDialog.__init__(self, parent)
        self.configManager = configManager
        # self.defaultFields = self.configManager.getFields(True)
        self.fieldsMapping = self.configManager.getFieldsMapping(name)
        self.name = name
        self.initUI()

    def initUI(self) -> None:
        self.setWindowTitle(self.name)

        vbox = QVBoxLayout()

        self.fields = []
        groupBox = QGroupBox("Field Mapping")
        m = mw.col.models.by_name(self.name)
        fields = mw.col.models.field_names(m)
        grid = QGridLayout()
        for idx, fld in enumerate(fields):
            le = QLineEdit(fld)
            le.setReadOnly(True)
            grid.addWidget(le, idx, 0)

            cb = QComboBox()
            defaultFields = self.configManager.getFields()
            displayFields = self.configManager.getFields(True)
            for i, defaultField in enumerate(defaultFields):
                cb.addItem(displayFields[i], defaultField)
            if fld in self.fieldsMapping:
                cb.setCurrentIndex(
                    cb.findData(self.fieldsMapping[fld], Qt.ItemDataRole.UserRole)
                )
            else:
                cb.setCurrentIndex(0)
            grid.addWidget(cb, idx, 1)

            self.fields.append((fld, cb))
        groupBox.setLayout(grid)
        vbox.addWidget(groupBox)

        self.buttonBox = QDialogButtonBox(self)
        self.buttonBox.setStandardButtons(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttonBox.setOrientation(Qt.Orientation.Horizontal)
        qconnect(self.buttonBox.accepted, self.accept)
        qconnect(self.buttonBox.rejected, self.reject)
        vbox.addWidget(self.buttonBox)

        self.setLayout(vbox)

    def accept(self) -> None:
        m = {}
        for fld, cb in self.fields:
            if cb.currentText() != "<ignored>":
                m[fld] = cb.currentData()
        self.configManager.updateMapping(self.name, m)
        self.close()


class MainWindow(QDialog):
    def __init__(self, configManager: ConfigManager, parent: Optional[QWidget] = None):
        QDialog.__init__(self, parent, Qt.WindowType.Window)
        self.configManager = configManager
        self.current_preset = self.configManager.getConfiguredPreset()
        self.settings: Dict[str, Any] = {}
        self.subsLC = {lang: lc.lower()[:2] for lang, lc in langs}
        self.isURL = False
        self.initUI()

    def getTwoSpeenBoxesOptionsGroup(
        self, name: str, labels: List[str], values: List[int], options: List[int]
    ) -> Tuple[QGroupBox, QSpinBox, QSpinBox]:
        groupBox = QGroupBox(name)
        spinBoxFirst = QSpinBox()
        spinBoxSecond = QSpinBox()

        grid = QGridLayout()

        label = QLabel(labels[0])
        label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        grid.addWidget(label, 0, 0)
        grid.addWidget(spinBoxFirst, 0, 1)
        grid.addWidget(QLabel(labels[2]), 0, 2)

        label = QLabel(labels[1])
        label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        grid.addWidget(label, 1, 0)
        grid.addWidget(spinBoxSecond, 1, 1)
        grid.addWidget(QLabel(labels[2]), 1, 2)

        spinBoxFirst.setRange(options[0], options[1])
        spinBoxFirst.setSingleStep(options[2])
        spinBoxFirst.setValue(values[0])

        spinBoxSecond.setRange(options[0], options[1])
        spinBoxSecond.setSingleStep(options[2])
        spinBoxSecond.setValue(values[1])

        groupBox.setLayout(grid)

        return groupBox, spinBoxFirst, spinBoxSecond

    def chooseModel(self, name: str) -> None:
        def onEdit() -> None:
            import aqt.models

            aqt.models.Models(mw, self)

        edit = QPushButton("Manage")
        qconnect(edit.clicked, onEdit)

        def nameFunc() -> List[str]:
            return sorted(mw.col.models.all_names())

        ret = StudyDeck(
            mw,
            names=nameFunc,
            buttons=[edit],
            accept="Choose",
            title="Choose Note Type",
            parent=self,
        )
        if ret.name is None:
            return
        self.modelButton.setText(ret.name)

    def chooseDeck(self, name: str) -> None:
        ret = StudyDeck(mw, accept="Choose", title="Choose Deck", parent=self)
        if ret.name is None:
            return
        self.deckButton.setText(ret.name)

    def mapFields(self, model: str) -> None:
        fm = FieldMapping(model, self.configManager, parent=self)
        fm.exec()

    def initUI(self) -> None:
        self.setWindowTitle("mpv2anki")

        vbox = QVBoxLayout()

        # Presets
        presetsGroup = QGroupBox("Presets")

        self.newPresetButton = QPushButton("New")
        qconnect(self.newPresetButton.clicked, self.onNewPreset)
        self.presetCombo = QComboBox()
        for preset in self.configManager.getPresetNames():
            self.presetCombo.addItem(preset)
            if preset == self.current_preset:
                self.presetCombo.setCurrentText(preset)
        qconnect(self.presetCombo.currentIndexChanged, self.onPresetChanged)
        self.settings = self.configManager.getSettings()
        grid = QGridLayout()
        grid.addWidget(QLabel("Preset:"), 0, 0)
        grid.addWidget(self.presetCombo, 0, 1)
        grid.addWidget(self.newPresetButton, 0, 2)

        presetsGroup.setLayout(grid)
        vbox.addWidget(presetsGroup)

        # Import Options

        importGroup = QGroupBox("Import Options")
        self.modelButton = QPushButton()
        if mw.col.models.by_name(self.settings["model"]):
            self.modelButton.setText(self.settings["model"])
        else:
            self.modelButton.setText(mw.col.models.current()["name"])
        self.modelButton.setAutoDefault(False)
        qconnect(self.modelButton.clicked, lambda: self.chooseModel("model"))
        self.modelFieldsButton = QPushButton()
        qconnect(
            self.modelFieldsButton.clicked,
            lambda: self.mapFields(self.modelButton.text()),
        )
        self.deckButton = QPushButton(self.settings["deck"])
        qconnect(self.deckButton.clicked, lambda: self.chooseDeck("deck"))
        self.useMPV = QCheckBox("Use MPV?")
        self.useMPV.setChecked(self.settings["use_mpv"])

        self.audio_ext = QLineEdit(self.settings["audio_ext"])

        icon = QIcon(os.path.join(os.path.dirname(__file__), "icons", "gears.png"))

        self.modelFieldsButton.setIcon(icon)

        grid = QGridLayout()
        grid.addWidget(QLabel("Type:"), 0, 0)
        grid.addWidget(self.modelButton, 0, 1)
        grid.setColumnStretch(1, 1)
        grid.addWidget(self.modelFieldsButton, 0, 2)
        grid.addWidget(QLabel("Deck:"), 0, 3)
        grid.addWidget(self.deckButton, 0, 4)
        grid.addWidget(self.useMPV, 1, 4)
        grid.addWidget(QLabel("File ext:"), 1, 0)
        grid.addWidget(self.audio_ext, 1, 1)
        grid.setColumnStretch(4, 1)

        importGroup.setLayout(grid)
        vbox.addWidget(importGroup)

        hbox = QHBoxLayout()

        (
            imageGroup,
            self.imageWidth,
            self.imageHeight,
        ) = self.getTwoSpeenBoxesOptionsGroup(
            "Screenshot",
            ["Width:", "Height:", "px"],
            [self.settings["image_width"], self.settings["image_height"]],
            [-2, 10000, 2],
        )
        (
            videoGroup,
            self.videoWidth,
            self.videoHeight,
        ) = self.getTwoSpeenBoxesOptionsGroup(
            "Video",
            ["Width:", "Height:", "px"],
            [self.settings["video_width"], self.settings["video_height"]],
            [-2, 10000, 2],
        )

        self.avDelay = avDelay = QDoubleSpinBox()
        avDelayLabel = QLabel("A/V delay")
        avDelayLabel.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        video_grid_layout = cast(QGridLayout, videoGroup.layout())
        video_grid_layout.addWidget(avDelayLabel, 2, 0)
        video_grid_layout.addWidget(avDelay, 2, 1)
        video_grid_layout.addWidget(QLabel("seconds"), 2, 2)
        avDelay.setRange(-2147483648, 2147483647)
        avDelay.setSingleStep(1)
        avDelay.setValue(self.settings["av_delay"])

        padGroup, self.padStart, self.padEnd = self.getTwoSpeenBoxesOptionsGroup(
            "Pad Timings",
            ["Start:", "End:", "ms"],
            [self.settings["pad_start"], self.settings["pad_end"]],
            [-2147483648, 2147483647, 1],
        )
        hbox.addWidget(imageGroup)
        hbox.addWidget(videoGroup)
        hbox.addWidget(padGroup)

        grid.addLayout(hbox, 2, 0, 1, 5)

        subsGroup = QGroupBox("Subtitles")
        grid3 = QGridLayout()
        grid3.addWidget(QLabel("In your target language:"), 0, 0)
        grid3.addWidget(QLabel("In your native language:"), 1, 0)
        self.subsTargetLang = QComboBox()
        self.subsNativeLang = QComboBox()
        self.subsTargetLang.addItem("")
        self.subsNativeLang.addItem("")
        for lang, lc in langs:
            self.subsTargetLang.addItem(lang)
            self.subsNativeLang.addItem(lang)
        self.subsTargetLang.setCurrentIndex(
            self.subsTargetLang.findText(self.settings["subs_target_language"])
        )
        self.subsNativeLang.setCurrentIndex(
            self.subsNativeLang.findText(self.settings["subs_native_language"])
        )
        grid3.addWidget(self.subsTargetLang, 0, 1)
        grid3.addWidget(self.subsNativeLang, 1, 1)
        self.subsTargetLC = QLineEdit(self.settings["subs_target_language_code"])
        self.subsNativeLC = QLineEdit(self.settings["subs_native_language_code"])
        self.subsTargetLC.setFixedWidth(24)
        self.subsNativeLC.setFixedWidth(24)
        self.subsTargetLC.setReadOnly(True)
        self.subsNativeLC.setReadOnly(True)
        self.subsTargetLC.setStyleSheet("QLineEdit{background: #f4f3f4;}")
        self.subsNativeLC.setStyleSheet("QLineEdit{background: #f4f3f4;}")
        self.subsTargetLC.setAlignment(
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter
        )
        self.subsNativeLC.setAlignment(
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter
        )
        qconnect(
            self.subsTargetLang.currentIndexChanged,
            lambda: self.chooseSubs(self.subsTargetLang, self.subsTargetLC),
        )
        qconnect(
            self.subsNativeLang.currentIndexChanged,
            lambda: self.chooseSubs(self.subsNativeLang, self.subsNativeLC),
        )
        grid3.addWidget(self.subsTargetLC, 0, 3)
        grid3.addWidget(self.subsNativeLC, 1, 3)
        grid3.addWidget(QLabel(" (optional)"), 1, 4)
        grid3.addItem(
            QSpacerItem(40, 20, QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Minimum),
            0,
            4,
            1,
            2,
        )
        subsGroup.setLayout(grid3)
        grid.addWidget(subsGroup, 3, 0, 1, 5)

        dictGroup = QGroupBox("Dictionary")
        grid4 = QGridLayout()
        self.altDictKeys = QCheckBox("Alternative dictionary hotkeys")
        self.altDictKeys.setChecked(self.settings["alt_dict_keys"])
        self.altDictKeys.setToolTip(
            "If checked, the pop-up dictionary will be triggered on click, while the on-click one will be triggered on a double click"
        )
        grid4.addWidget(self.altDictKeys)
        dictGroup.setLayout(grid4)
        grid.addWidget(dictGroup, 4, 0, 1, 5)

        onClickDictGroup = QGroupBox("On-click Dictionary")
        grid5 = QGridLayout()
        grid5.addWidget(QLabel("Dictionary"), 0, 0)
        self.onClickDict = QComboBox()
        qconnect(self.onClickDict.currentIndexChanged, self.onClickDictChanged)
        grid5.addWidget(self.onClickDict, 0, 1, 1, 4)
        self.onClickDictSpecificGroup = QGroupBox("Settings")
        self.onClickDictSpecificGroup.setLayout(QVBoxLayout())
        self.onClickDictSpecificGroup.layout().addWidget(QWidget())
        grid5.addWidget(self.onClickDictSpecificGroup, 1, 0, 1, 5)
        onClickDictGroup.setLayout(grid5)
        grid.addWidget(onClickDictGroup, 5, 0, 1, 5)
        self.onclick_dicts = [
            onclick_dict
            for onclick_dict in onclick.dictionaries
            if onclick_dict.is_available()
        ]
        self.onClickDict.addItems(
            [onclick_dict.name for onclick_dict in self.onclick_dicts]
        )
        for i, onclick_dict in enumerate(self.onclick_dicts):
            if onclick_dict.name == self.settings.get("onclick_dict"):
                self.onClickDict.setCurrentIndex(i)

        popupDictGroup = QGroupBox("Pop-up Dictionary")
        grid6 = QGridLayout()
        grid6.addWidget(QLabel("Dictionary"), 0, 0)
        self.popupDict = QComboBox()
        qconnect(self.popupDict.currentIndexChanged, self.onPopupDictChanged)
        grid6.addWidget(self.popupDict, 0, 1, 1, 4)
        self.popupDictSpecificGroup = QGroupBox("Settings")
        self.popupDictSpecificGroup.setLayout(QVBoxLayout())
        self.popupDictSpecificGroup.layout().addWidget(QWidget())
        grid6.addWidget(self.popupDictSpecificGroup, 1, 0, 1, 5)
        popupDictGroup.setLayout(grid6)
        grid.addWidget(popupDictGroup, 6, 0, 1, 5)
        self.popup_dicts = [
            popup_dict for popup_dict in popup.dictionaries if popup_dict.is_available()
        ]
        self.popupDict.addItems([popup_dict.name for popup_dict in self.popup_dicts])
        for i, popup_dict in enumerate(self.popup_dicts):
            if popup_dict.name == self.settings.get("popup_dict"):
                self.popupDict.setCurrentIndex(i)

        # Go!

        self.openURLButton = QPushButton("Open URL")
        qconnect(self.openURLButton.clicked, self.openURL)

        self.openFileButton = QPushButton("Open File")
        self.openFileButton.setDefault(True)
        qconnect(self.openFileButton.clicked, self.start)

        hbox = QHBoxLayout()
        hbox.addStretch(1)
        hbox.addWidget(self.openURLButton)
        hbox.addWidget(self.openFileButton)
        vbox.addLayout(hbox)

        viewport = QWidget(self)
        viewport.setLayout(vbox)
        scrollArea = QScrollArea(self)
        scrollArea.setWidget(viewport)
        scrollArea.setWidgetResizable(True)
        mainLayout = QVBoxLayout()
        mainLayout.addWidget(scrollArea)
        self.setLayout(mainLayout)

        self.setWindowState(Qt.WindowState.WindowMaximized)

    def onPresetChanged(self) -> None:
        if not self.presetCombo.currentText():
            return
        self.configManager.save(self.current_preset)
        if self.presetCombo.currentText() == self.current_preset:
            return
        self.current_preset = self.presetCombo.currentText()
        self.configManager.setConfiguredPreset(self.current_preset)
        self.settings = self.configManager.getSettings()
        if mw.col.models.by_name(self.settings["model"]):
            self.modelButton.setText(self.settings["model"])
        else:
            self.modelButton.setText(mw.col.models.current()["name"])
        self.deckButton.setText(self.settings["deck"])
        self.useMPV.setChecked(self.settings["use_mpv"])
        self.audio_ext.setText(self.settings["audio_ext"])
        self.imageWidth.setValue(self.settings["image_width"])
        self.imageHeight.setValue(self.settings["image_height"])
        self.videoWidth.setValue(self.settings["video_width"])
        self.videoHeight.setValue(self.settings["video_height"])
        self.avDelay.setValue(self.settings["av_delay"])
        self.padStart.setValue(self.settings["pad_start"])
        self.padEnd.setValue(self.settings["pad_end"])
        self.subsTargetLang.setCurrentIndex(
            self.subsTargetLang.findText(self.settings["subs_target_language"])
        )
        self.subsNativeLang.setCurrentIndex(
            self.subsNativeLang.findText(self.settings["subs_native_language"])
        )
        self.subsTargetLC.setText(self.settings["subs_target_language_code"])
        self.subsNativeLC.setText(self.settings["subs_native_language_code"])
        for i, onclick_dict in enumerate(self.onclick_dicts):
            if onclick_dict.name == self.settings.get("onclick_dict", None):
                self.onClickDict.setCurrentIndex(i)
        if self.configManager.onClickDict:
            self.configManager.onClickDict.widget.update_options(
                self.settings["onclick_options"]
            )
        for i, popup_dict in enumerate(self.popup_dicts):
            if popup_dict.name == self.settings.get("popup_dict"):
                self.popupDict.setCurrentIndex(i)
        if self.configManager.popupDict:
            self.configManager.popupDict.widget.update_options(
                self.settings["popup_options"]
            )

    def onNewPreset(self) -> None:
        preset = getOnlyText("Preset name:")
        if not preset:
            return

        self.configManager.addNewPreset(preset)
        self.blockSignals(True)
        self.presetCombo.clear()
        for name in self.configManager.getPresetNames():
            self.presetCombo.addItem(name)
        self.blockSignals(False)
        self.presetCombo.setCurrentText(preset)

    def onClickDictChanged(self, index: int) -> None:
        dictionary = self.onclick_dicts[index](self.settings.get("onclick_options", {}))
        layout = self.onClickDictSpecificGroup.layout()
        layout.replaceWidget(layout.itemAt(0).widget(), dictionary.widget)
        self.configManager.onClickDict = dictionary

    def onPopupDictChanged(self, index: int) -> None:
        dictionary = self.popup_dicts[index](self.settings.get("popup_options", {}))
        layout = self.popupDictSpecificGroup.layout()
        layout.replaceWidget(layout.itemAt(0).widget(), dictionary.widget)
        # FIXME: pop-up dict has nothing to do with the config manager - store it somewhere else!
        self.configManager.popupDict = dictionary

    def chooseSubs(self, cb: QComboBox, cblc: QLineEdit) -> None:
        if cb.currentText() == "":
            cblc.setText("")
        else:
            cblc.setText(self.subsLC[cb.currentText()])

    def saveSettings(self) -> None:
        self.settings["model"] = self.modelButton.text()
        self.settings["deck"] = self.deckButton.text()
        self.settings["use_mpv"] = self.useMPV.isChecked()
        self.settings["image_width"] = self.imageWidth.value()
        self.settings["image_height"] = self.imageHeight.value()
        self.settings["video_width"] = self.videoWidth.value()
        self.settings["video_height"] = self.videoHeight.value()
        self.settings["av_delay"] = self.avDelay.value()
        self.settings["pad_start"] = self.padStart.value()
        self.settings["pad_end"] = self.padEnd.value()
        self.settings["audio_ext"] = self.audio_ext.text()

        self.settings["subs_target_language"] = self.subsTargetLang.currentText()
        self.settings["subs_target_language_code"] = self.subsTargetLC.text()
        self.settings["subs_native_language"] = self.subsNativeLang.currentText()
        self.settings["subs_native_language_code"] = self.subsNativeLC.text()
        self.settings["alt_dict_keys"] = self.altDictKeys.isChecked()

        self.configManager.save(self.presetCombo.currentText())

    def reject(self) -> None:
        self.saveSettings()
        self.done(0)

    def validate(self) -> Tuple[bool, str]:
        name = self.settings["model"]

        fm = self.configManager.getFieldsMapping(name)
        if not fm:
            return (
                False,
                "No fields were mapped. Please click on the gear icon and map some fields.",
            )

        model = mw.col.models.by_name(name)
        fields = mw.col.models.field_names(model)

        m = {}
        renamed_or_deleted = []
        for k, v in fm.items():
            if k not in fields:
                renamed_or_deleted.append(k)
                continue
            m[k] = v

        if renamed_or_deleted:
            msg = "The following fields no longer can be found in the note type:"
            msg += "\n\n"
            msg += "\n".join(renamed_or_deleted)
            msg += "\n\n"
            msg += "Please click on the gear icon and double check the mapping."
            self.configManager.updateMapping(name, m)

            return False, msg

        return True, None

    def openURL(self) -> None:
        self.isURL = True
        self.start()

    def start(self) -> None:
        if self.configManager.popupDict:
            popup_options = self.configManager.popupDict.collect_widget_settings()
            self.settings["popup_dict"] = self.configManager.popupDict.name
            if popup_options:
                self.settings["popup_options"] = popup_options
            else:
                self.configManager.popupDict = None
        if self.configManager.onClickDict:
            onclick_options = self.configManager.onClickDict.collect_widget_settings()
            self.settings["onclick_dict"] = self.configManager.onClickDict.name
            if onclick_options:
                self.settings["onclick_options"] = onclick_options
            else:
                self.configManager.onClickDict = None
        self.saveSettings()
        ret, msg = self.validate()
        if ret:
            self.accept()
        else:
            showWarning(msg)


def openVideoWithMPV() -> None:
    env = os.environ.copy()

    if is_win:
        path = os.environ["PATH"].split(os.pathsep)
        os.environ["PATH"] = os.pathsep.join(path[1:])

    executable = None
    popenEnv = os.environ.copy()

    if "LD_LIBRARY_PATH" in popenEnv:
        del popenEnv["LD_LIBRARY_PATH"]

    if is_mac and os.path.exists("/Applications/mpv.app/Contents/MacOS/mpv"):
        executable = "/Applications/mpv.app/Contents/MacOS/mpv"

    if executable is None:
        executable = find_executable("mpv")

    os.environ["PATH"] = env["PATH"]
    if executable is None:
        if is_lin:
            showWarning(
                "Please install <a href='https://mpv.io'>mpv</a> and try again.",
                parent=mw,
            )
            return
        if is_mac:
            msg = """The add-on can't find mpv. Please install it from <a href='https://mpv.io'>https://mpv.io</a> and try again.
<br><br>
- Download mpv from <a href='https://laboratory.stolendata.net/~djinn/mpv_osx/'>https://laboratory.stolendata.net/~djinn/mpv_osx/</a><br>
- Unpack it somewhere and drag-and-drop 'mpv.app' folder to 'Applications' folder.<br>
- Maybe it'll work.
<br><br>
or
<br><br>
- Open the Terminal app<br>
- Install <a href='https://brew.sh/'>https://brew.sh/</a><br>
- Paste the following command and press Return to install mpv.
<br><br>
<code>brew cask install mpv</code>
"""
            showText(msg, type="html", parent=mw)
            return
        assert is_win
        msg = """The add-on can't find mpv. Please install it from <a href='https://mpv.io'>https://mpv.io</a> and try again.
<br><br>
- The Windows build can be downloaded from <a href='https://sourceforge.net/projects/mpv-player-windows/files/64bit/'>https://sourceforge.net/projects/mpv-player-windows/files/64bit/</a><br>
- Unpack it with WinRar or 7-Zip - <a href='https://www.7-zip.org/'>https://www.7-zip.org/</a><br>
- Move it somewhere, e.g. C:\\Program Files\\mpv<br>
- Update the PATH environment variable - <a href='https://www.architectryan.com/2018/03/17/add-to-the-path-on-windows-10/'>https://www.architectryan.com/2018/03/17/add-to-the-path-on-windows-10/</a> or <a href='https://streamable.com/2b1l6'>https://streamable.com/2b1l6</a><br>
- Restart Anki.
"""
        showText(msg, type="html", parent=mw)
        return

    configManager = ConfigManager()
    mainWindow = MainWindow(configManager, parent=mw)

    if mainWindow.exec():
        if mainWindow.isURL:
            txt = getOnlyText("Enter URL:")
            if not txt:
                return
            fileUrls = [txt]
        else:

            def formatURL(url: QUrl) -> str:
                if url.isLocalFile():
                    return url.toLocalFile()
                return url.toString()

            fileUrls = [formatURL(f) for f in getVideoFile()]
        if not fileUrls:
            return
        AnkiHelper(executable, popenEnv, fileUrls, configManager)

    mw.reset()


action = QAction("Open Video...", mw)
action.setShortcut("Ctrl+O")
qconnect(action.triggered, openVideoWithMPV)
mw.form.menuTools.addAction(action)
