from __future__ import annotations

import dataclasses
import json
import logging
import re
from dataclasses import dataclass
from html import unescape
from typing import Any, List, Optional, Sequence
from urllib.error import URLError
from urllib.request import Request, urlopen
from xml.etree import ElementTree

import yt_dlp

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class TranscriptSegment:
    """Single transcript entry."""

    start: float
    end: float
    text: str


@dataclass(slots=True)
class TranscriptSummary:
    """Container describing a transcript request."""

    video_id: str
    title: str
    url: str
    duration: Optional[float]
    uploader: Optional[str]
    segments: List[TranscriptSegment]
    timestamp_lines: List[str]
    polished_paragraphs: List[str]

    @property
    def human_duration(self) -> str:
        if self.duration is None:
            return "unknown"
        total = int(self.duration)
        hours, remainder = divmod(total, 3600)
        minutes, seconds = divmod(remainder, 60)
        parts = []
        if hours:
            parts.append(f"{hours}h")
        if minutes:
            parts.append(f"{minutes}m")
        if seconds or not parts:
            parts.append(f"{seconds}s")
        return " ".join(parts)


class TranscriptError(RuntimeError):
    """Raised when a transcript cannot be produced."""


class TranscriptService:
    """Handles transcript retrieval and formatting."""

    _FORMAT_PRIORITY: Sequence[str] = ("json3", "srv3", "ttml", "vtt", "srt")

    def __init__(self, preferred_langs: Optional[Sequence[str]] = None) -> None:
        self.preferred_langs = list(preferred_langs or ("en", "en-US", "en-GB"))

    def fetch(self, url: str) -> TranscriptSummary:
        """Fetch transcript segments and formatting for a video."""
        info = self._extract_info(url)
        track = self._select_track(info)
        if not track:
            raise TranscriptError("No transcript or captions are available for that video.")
        payload = self._download_track(track["url"])
        segments = self._parse_segments(track["ext"], payload)
        segments.sort(key=lambda segment: segment.start)
        if not segments:
            raise TranscriptError("Transcript stream was empty.")
        timestamp_lines = self._build_timestamp_lines(segments)
        polished_paragraphs = self._build_paragraphs(segments)
        return TranscriptSummary(
            video_id=info.get("id", "transcript"),
            title=info.get("title") or "Untitled video",
            url=info.get("webpage_url") or url,
            duration=info.get("duration"),
            uploader=info.get("uploader"),
            segments=segments,
            timestamp_lines=timestamp_lines,
            polished_paragraphs=polished_paragraphs,
        )

    def _extract_info(self, url: str) -> dict:
        opts = {
            "skip_download": True,
            "quiet": True,
            "no_warnings": True,
            "writesubtitles": True,
            "writeautomaticsub": True,
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            return ydl.extract_info(url, download=False)

    def _select_track(self, info: dict) -> Optional[dict]:
        sources: Sequence[str] = (
            "requested_subtitles",
            "subtitles",
            "automatic_captions",
        )
        for key in sources:
            pool = info.get(key) or {}
            track = self._pick_track_from_source(pool)
            if track:
                return track
        return None

    def _pick_track_from_source(self, pool: dict) -> Optional[dict]:
        if not pool:
            return None
        for lang in self.preferred_langs:
            track = self._pick_format(pool.get(lang))
            if track:
                return track
        for lang in sorted(pool.keys()):
            track = self._pick_format(pool[lang])
            if track:
                return track
        return None

    def _pick_format(self, options: Optional[Any]) -> Optional[dict]:
        candidates = self._normalize_track_options(options)
        if not candidates:
            return None
        for ext in self._FORMAT_PRIORITY:
            for option in candidates:
                if option.get("ext") == ext:
                    return option
        return candidates[0]

    def _normalize_track_options(self, options: Optional[Any]) -> List[dict]:
        """Coerce various yt-dlp subtitle structures into a list of dicts."""

        if options is None:
            return []
        if isinstance(options, dict):
            if "url" in options:
                return [options]
            normalized: List[dict] = []
            for value in options.values():
                normalized.extend(self._normalize_track_options(value))
            return normalized
        if isinstance(options, str):
            return [{"url": options, "ext": None}]
        if isinstance(options, (list, tuple, set)):
            normalized: List[dict] = []
            for entry in options:
                normalized.extend(self._normalize_track_options(entry))
            return normalized
        return []

    def _download_track(self, url: str) -> str:
        try:
            request = Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urlopen(request, timeout=30) as response:
                return response.read().decode("utf-8", errors="ignore")
        except URLError as exc:
            raise TranscriptError("Unable to download caption file.") from exc

    def _parse_segments(self, ext: Optional[str], payload: str) -> List[TranscriptSegment]:
        ext = (ext or "").lower()
        if ext == "json3":
            return self._parse_json3(payload)
        if ext in {"srv3", "ttml"}:
            return self._parse_xml(payload)
        if ext in {"vtt", "srt"}:
            return self._parse_vtt(payload)
        logger.warning("Encountered unknown subtitle format %s. Falling back to generic parser.", ext)
        if payload.strip().startswith("{"):
            return self._parse_json3(payload)
        if payload.strip().startswith("<"):
            return self._parse_xml(payload)
        return self._parse_vtt(payload)

    def _parse_json3(self, payload: str) -> List[TranscriptSegment]:
        try:
            data = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise TranscriptError("Failed to parse json3 subtitles.") from exc
        segments: List[TranscriptSegment] = []
        events = data.get("events") or []
        for event in events:
            segs = event.get("segs")
            if not segs:
                continue
            start = event.get("tStartMs")
            duration = event.get("dDurationMs")
            if start is None:
                continue
            start_seconds = float(start) / 1000.0
            end_seconds = start_seconds + (float(duration) / 1000.0 if duration else 0.0)
            text = "".join(seg.get("utf8", "") for seg in segs)
            cleaned = self._clean_text(text)
            if cleaned:
                segments.append(TranscriptSegment(start_seconds, end_seconds or start_seconds, cleaned))
        self._fill_missing_end_times(segments)
        return segments

    def _parse_vtt(self, payload: str) -> List[TranscriptSegment]:
        pattern = re.compile(
            r"(?P<start>\d{1,2}:[0-5]\d:[0-5]\d[.,]\d{3})\s+-->\s+"
            r"(?P<end>\d{1,2}:[0-5]\d:[0-5]\d[.,]\d{3})"
        )
        blocks = re.split(r"\n{2,}", payload.strip())
        segments: List[TranscriptSegment] = []
        for block in blocks:
            lines = [line.strip() for line in block.splitlines() if line.strip()]
            if len(lines) < 2:
                continue
            if lines[0].isdigit():
                lines = lines[1:]
            if not lines:
                continue
            match = pattern.match(lines[0].replace(",", "."))
            if not match:
                continue
            start_seconds = self._parse_hms(match.group("start"))
            end_seconds = self._parse_hms(match.group("end"))
            text = self._clean_text(" ".join(lines[1:]))
            if text:
                segments.append(TranscriptSegment(start_seconds, end_seconds, text))
        return segments

    def _parse_xml(self, payload: str) -> List[TranscriptSegment]:
        try:
            root = ElementTree.fromstring(payload)
        except ElementTree.ParseError as exc:
            raise TranscriptError("Failed to parse XML captions.") from exc
        segments: List[TranscriptSegment] = []
        for node in root.iter():
            tag = node.tag.split("}")[-1].lower()
            if tag not in {"text", "p"}:
                continue
            text = self._clean_text("".join(node.itertext()))
            if not text:
                continue
            start = (
                node.attrib.get("start")
                or node.attrib.get("begin")
                or node.attrib.get("t")
            )
            end = node.attrib.get("end")
            dur = node.attrib.get("dur")
            start_seconds = self._parse_time_value(start) or 0.0
            end_seconds = (
                self._parse_time_value(end)
                or (start_seconds + (self._parse_time_value(dur) or 0.0))
            )
            segments.append(TranscriptSegment(start_seconds, end_seconds, text))
        self._fill_missing_end_times(segments)
        return segments

    def _parse_hms(self, value: str) -> float:
        parts = value.split(":")
        seconds = 0.0
        for part in parts:
            seconds = seconds * 60 + float(part)
        return seconds

    def _parse_time_value(self, value: Optional[str]) -> Optional[float]:
        if value is None:
            return None
        value = value.strip()
        if not value:
            return None
        if value.endswith("ms"):
            return float(value[:-2]) / 1000.0
        if value.endswith("s"):
            return float(value[:-1])
        if value.endswith("m"):
            return float(value[:-1]) * 60.0
        if value.endswith("h"):
            return float(value[:-1]) * 3600.0
        if ":" in value:
            return self._parse_hms(value.replace(",", "."))
        try:
            return float(value)
        except ValueError:
            return None

    def _fill_missing_end_times(self, segments: List[TranscriptSegment]) -> None:
        for idx, segment in enumerate(segments):
            if segment.end and segment.end > segment.start:
                continue
            next_start = segments[idx + 1].start if idx + 1 < len(segments) else segment.start + 3
            segment.end = max(segment.start + 0.5, next_start)

    def _clean_text(self, text: str) -> str:
        text = unescape(text or "")
        text = re.sub(r"<[^>]+>", " ", text)
        text = text.replace("\xa0", " ")
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    def _build_timestamp_lines(self, segments: Sequence[TranscriptSegment]) -> List[str]:
        lines: List[str] = []
        for idx, segment in enumerate(segments, start=1):
            start = self._format_timestamp(segment.start)
            end = self._format_timestamp(segment.end)
            header = f"{idx:04d}  {start} --> {end}"
            lines.extend([header, segment.text, ""])
        while lines and not lines[-1].strip():
            lines.pop()
        return lines

    def _format_timestamp(self, seconds: float) -> str:
        seconds = max(0.0, seconds)
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = seconds % 60
        return f"{hours:02}:{minutes:02}:{secs:06.3f}"

    def _build_paragraphs(self, segments: Sequence[TranscriptSegment]) -> List[str]:
        paragraphs: List[str] = []
        buffer: List[str] = []
        last_end: Optional[float] = None
        for segment in segments:
            text = segment.text
            if not text:
                continue
            if last_end is not None and segment.start - last_end > 8.0 and buffer:
                paragraphs.append(self._polish_paragraph(buffer))
                buffer = []
            buffer.append(text)
            last_end = segment.end
            if text[-1:] in ".!?" and self._paragraph_length(buffer) >= 220:
                paragraphs.append(self._polish_paragraph(buffer))
                buffer = []
        if buffer:
            paragraphs.append(self._polish_paragraph(buffer))
        return [p for p in paragraphs if p]

    def _paragraph_length(self, parts: Sequence[str]) -> int:
        return sum(len(part) + 1 for part in parts)

    def _polish_paragraph(self, parts: Sequence[str]) -> str:
        joined = " ".join(parts)
        joined = re.sub(r"\s+", " ", joined)
        joined = joined.replace(" ,", ",").replace(" .", ".")
        joined = joined.replace(" !", "!").replace(" ?", "?")
        joined = re.sub(r"\s+([;:])", r"\1", joined)
        joined = re.sub(r"([\[\]\(\)])\s+", r"\1 ", joined)
        return joined.strip()
