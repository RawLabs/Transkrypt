from __future__ import annotations

import os
import re
import textwrap
from pathlib import Path
from typing import List

from .transcript_service import TranscriptSummary


class TranscriptPDFBuilder:
    """Renders transcript data into a lightweight PDF."""

    def __init__(self, output_dir: str | os.PathLike[str] = "output") -> None:
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def build(self, summary: TranscriptSummary) -> Path:
        safe_name = f"{summary.video_id}-{self._slugify(summary.title or summary.video_id)}"
        filename = f"{safe_name[:120]}.pdf"
        pdf_path = self.output_dir / filename
        pdf = _SimplePDF()
        pdf.add_heading("Transkrypt Report")
        pdf.add_subheading(summary.title)
        metadata = [
            f"Video URL: {summary.url}",
            f"Duration: {summary.human_duration}",
            f"Uploader: {summary.uploader or 'unknown'}",
            f"Video ID: {summary.video_id}",
        ]
        for line in metadata:
            pdf.add_body_text(line, size=11)
        pdf.add_spacer(0.8)
        pdf.add_heading("Timestamped Transcript", level=2)
        for line in summary.timestamp_lines:
            pdf.add_body_text(line, size=10)
        pdf.add_spacer(0.8)
        pdf.add_heading("Polished Transcript", level=2)
        for idx, paragraph in enumerate(summary.polished_paragraphs, start=1):
            prefixed = f"{idx}. {paragraph}"
            pdf.add_body_text(prefixed, size=11)
            pdf.add_spacer(0.4)
        pdf.save(pdf_path)
        return pdf_path

    def _slugify(self, value: str) -> str:
        slug = re.sub(r"[^A-Za-z0-9]+", "-", value).strip("-")
        return slug or "transkrypt"


class _SimplePDF:
    """Small utility that writes basic text-only PDF documents."""

    def __init__(self, width: float = 612, height: float = 792, margin: float = 54) -> None:
        self.width = width
        self.height = height
        self.margin = margin
        self.usable_width = width - margin * 2
        self.pages: List[List[str]] = [[]]
        self.cursor_y = self.height - self.margin

    def add_heading(self, text: str, level: int = 1) -> None:
        font_size = 18 if level == 1 else 14
        self._add_wrapped_text(text, font="F2", size=font_size, extra_spacing=0.5)

    def add_subheading(self, text: str) -> None:
        self._add_wrapped_text(text, font="F1", size=13, extra_spacing=0.4)

    def add_body_text(self, text: str, size: float = 11) -> None:
        self._add_wrapped_text(text, font="F1", size=size, extra_spacing=0.0)

    def add_spacer(self, units: float) -> None:
        spacing = max(units, 0.2) * 14
        self.cursor_y -= spacing
        if self.cursor_y < self.margin:
            self._new_page()

    def _add_wrapped_text(
        self,
        text: str,
        font: str,
        size: float,
        extra_spacing: float = 0.0,
    ) -> None:
        if not text:
            return
        wrap_width = max(20, int(self.usable_width / max(size * 0.55, 1)))
        lines = textwrap.wrap(text, width=wrap_width) or [text]
        for idx, line in enumerate(lines):
            self._add_line(line.strip(), font=font, size=size)
        if extra_spacing:
            self.cursor_y -= size * extra_spacing

    def _add_line(self, text: str, font: str, size: float) -> None:
        if self.cursor_y < self.margin + size:
            self._new_page()
        y = self.cursor_y
        self.pages[-1].extend(
            [
                "BT",
                f"/{font} {size:.2f} Tf",
                f"{self.margin:.2f} {y:.2f} Td",
                f"({self._escape(text)}) Tj",
                "ET",
            ]
        )
        self.cursor_y -= size * 1.4

    def _new_page(self) -> None:
        self.pages.append([])
        self.cursor_y = self.height - self.margin

    def _escape(self, text: str) -> str:
        return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    def save(self, path: Path) -> None:
        if not any(self.pages):
            self.pages = [[]]
        content_streams = []
        for ops in self.pages:
            stream = "\n".join(ops) + "\n" if ops else ""
            content_streams.append(stream)
        num_pages = len(content_streams)
        catalog_id = 1
        pages_id = 2
        font_regular_id = 3
        font_bold_id = 4
        content_start = 5
        page_start = content_start + num_pages
        total_objects = page_start + num_pages - 1
        offsets: List[int] = [0]

        def write_obj(handle, obj_id: int, body: str) -> None:
            offsets.append(handle.tell())
            handle.write(f"{obj_id} 0 obj\n".encode("utf-8"))
            handle.write(body.encode("utf-8"))
            handle.write(b"\nendobj\n")

        with open(path, "wb") as handle:
            handle.write(b"%PDF-1.4\n")
            write_obj(handle, catalog_id, f"<< /Type /Catalog /Pages {pages_id} 0 R >>")

            kids = " ".join(f"{page_start + idx} 0 R" for idx in range(num_pages))
            write_obj(handle, pages_id, f"<< /Type /Pages /Kids [{kids}] /Count {num_pages} >>")

            write_obj(handle, font_regular_id, "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
            write_obj(handle, font_bold_id, "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>")

            for idx, stream in enumerate(content_streams):
                length = len(stream.encode("utf-8"))
                body = f"<< /Length {length} >>\nstream\n{stream}endstream"
                write_obj(handle, content_start + idx, body)

            for idx in range(num_pages):
                content_id = content_start + idx
                page_id = page_start + idx
                page_body = (
                    f"<< /Type /Page /Parent {pages_id} 0 R "
                    f"/MediaBox [0 0 {self.width:.0f} {self.height:.0f}] "
                    f"/Resources << /Font << /F1 {font_regular_id} 0 R /F2 {font_bold_id} 0 R >> >> "
                    f"/Contents {content_id} 0 R >>"
                )
                write_obj(handle, page_id, page_body)

            xref_start = handle.tell()
            handle.write(f"xref\n0 {total_objects + 1}\n".encode("utf-8"))
            handle.write(b"0000000000 65535 f \n")
            for offset in offsets[1:]:
                handle.write(f"{offset:010d} 00000 n \n".encode("utf-8"))
            trailer = f"trailer << /Size {total_objects + 1} /Root {catalog_id} 0 R >>\n"
            handle.write(trailer.encode("utf-8"))
            handle.write(f"startxref\n{xref_start}\n%%EOF".encode("utf-8"))
