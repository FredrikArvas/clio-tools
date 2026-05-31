"""pdf_builder.py — Konverterar .md-rapport till PDF med fpdf2."""

from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

MARGIN = 20
MARGIN_TOP = 28  # Extra luft till sidhuvudet
LINE_HEIGHT = 6
FOOTER_URL = "https://fredrik.arvas.se/clio-research/"

# AIAB-färgpalett
NAVY   = (42, 63, 111)
BLUE   = (74, 111, 165)
GOLD   = (200, 168, 75)
BROWN  = (61, 46, 10)
CREAM  = (247, 242, 232)
GREY   = (180, 180, 180)
BLACK  = (0, 0, 0)


def build_pdf(md_path: Path) -> Path:
    """
    Läser [run_id].md och skriver [run_id].pdf i samma katalog.
    Returnerar sökväg till PDF:en.
    """
    try:
        from fpdf import FPDF
    except ImportError:
        logger.warning("[pdf_builder] fpdf2 ej installerat — PDF hoppas över")
        raise

    text = md_path.read_text(encoding="utf-8")
    lines = text.splitlines()

    # Samla rubriker för innehållsförteckning (## och ### nivåer)
    toc_entries = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## "):
            toc_entries.append(("##", _clean(stripped[3:])))
        elif stripped.startswith("### "):
            toc_entries.append(("###", _clean(stripped[4:])))

    pdf = _ClioReport()

    # Sida 1+: innehållsförteckning
    if toc_entries:
        pdf.add_page()
        _render_toc(pdf, toc_entries)

    # Innehållssidor
    pdf.add_page()
    for line in lines:
        _render_line(pdf, line)

    out_path = md_path.with_suffix(".pdf")
    pdf.output(str(out_path))
    logger.info("[pdf_builder] PDF sparad: %s", out_path)
    return out_path


def _render_toc(pdf, entries: list) -> None:
    """Renderar en innehållsförteckningssida."""
    w = pdf.w - 2 * MARGIN
    pdf.set_x(MARGIN)

    # Rubrik
    pdf.set_fill_color(*NAVY)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 15)
    pdf.set_x(MARGIN)
    pdf.multi_cell(w, 10, "Innehållsförteckning", fill=True, align="L")
    pdf.ln(6)

    for level, title in entries:
        indent = MARGIN if level == "##" else MARGIN + 6
        size = 10 if level == "##" else 9
        style = "B" if level == "##" else ""
        color = NAVY if level == "##" else BLUE
        pdf.set_font("Helvetica", style, size)
        pdf.set_text_color(*color)
        pdf.set_x(indent)
        # Trunkera långa titlar
        display = title[:80] + ("..." if len(title) > 80 else "")
        pdf.cell(w - (indent - MARGIN), LINE_HEIGHT + 1, display, align="L", ln=True)

    pdf.set_text_color(*BROWN)


class _ClioReport:
    """Tunn wrapper runt FPDF med sidnummer och footer."""

    def __init__(self):
        from fpdf import FPDF
        self._pdf = FPDF()
        self._pdf.set_margins(MARGIN, MARGIN_TOP, MARGIN)
        self._pdf.set_auto_page_break(auto=True, margin=18)
        self._pdf.set_font("Helvetica", size=10)

    def add_page(self):
        self._pdf.add_page()

    def output(self, path: str):
        self._add_footers()
        self._pdf.output(path)

    def _add_footers(self):
        total = len(self._pdf.pages)
        today = datetime.now().strftime("%Y-%m-%d")
        for page_num in range(1, total + 1):
            self._pdf.page = page_num
            self._pdf.set_y(-14)
            self._pdf.set_font("Helvetica", "I", 7)
            self._pdf.set_text_color(*GREY)
            left = f"clio-research  |  {FOOTER_URL}"
            right = f"{today}  |  Sida {page_num}/{total}"
            w = self._pdf.w - 2 * MARGIN
            self._pdf.set_x(MARGIN)
            self._pdf.cell(w / 2, 5, left, align="L")
            self._pdf.cell(w / 2, 5, right, align="R")

    # Delegera egenskaper FPDF behöver
    @property
    def w(self):
        return self._pdf.w

    def get_y(self):
        return self._pdf.get_y()

    def set_x(self, x):
        self._pdf.set_x(x)

    def set_y(self, y):
        self._pdf.set_y(y)

    def set_font(self, *args, **kwargs):
        self._pdf.set_font(*args, **kwargs)

    def set_text_color(self, *args):
        self._pdf.set_text_color(*args)

    def set_fill_color(self, *args):
        self._pdf.set_fill_color(*args)

    def set_draw_color(self, *args):
        self._pdf.set_draw_color(*args)

    def multi_cell(self, *args, **kwargs):
        self._pdf.multi_cell(*args, **kwargs)

    def cell(self, *args, **kwargs):
        self._pdf.cell(*args, **kwargs)

    def ln(self, h=None):
        self._pdf.ln(h)

    def line(self, *args):
        self._pdf.line(*args)

    def rect(self, *args, **kwargs):
        self._pdf.rect(*args, **kwargs)


def _render_line(pdf, line: str) -> None:
    stripped = line.strip()
    pdf.set_x(MARGIN)
    w = pdf.w - 2 * MARGIN

    if stripped.startswith("# ") and not stripped.startswith("## "):
        pdf.ln(4)
        # Färgad bakgrundsruta för H1
        pdf.set_fill_color(*NAVY)
        pdf.set_text_color(255, 255, 255)
        pdf.set_font("Helvetica", "B", 15)
        pdf.set_x(MARGIN)
        pdf.multi_cell(w, 10, _clean(stripped[2:]), fill=True, align="L")
        pdf.set_text_color(*BROWN)
        pdf.ln(3)

    elif stripped.startswith("## "):
        pdf.ln(3)
        pdf.set_text_color(*NAVY)
        pdf.set_font("Helvetica", "B", 12)
        pdf.set_x(MARGIN)
        pdf.multi_cell(w, 8, _clean(stripped[3:]), align="L")
        # Understrykning
        y = pdf.get_y()
        pdf.set_draw_color(*BLUE)
        pdf.line(MARGIN, y, MARGIN + w, y)
        pdf.set_draw_color(*GREY)
        pdf.set_text_color(*BROWN)
        pdf.ln(2)

    elif stripped.startswith("### "):
        pdf.ln(2)
        pdf.set_text_color(*BLUE)
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_x(MARGIN)
        pdf.multi_cell(w, 7, _clean(stripped[4:]), align="L")
        pdf.set_text_color(*BROWN)
        pdf.ln(1)

    elif stripped == "---":
        pdf.ln(3)
        pdf.set_draw_color(*GREY)
        pdf.line(MARGIN, pdf.get_y(), MARGIN + w, pdf.get_y())
        pdf.ln(3)

    elif stripped == "":
        pdf.ln(LINE_HEIGHT / 2)

    elif stripped.startswith("|"):
        _render_table_row(pdf, stripped, w, getattr(pdf, "_last_was_separator", False))
        pdf._last_was_separator = bool(re.match(r"^\|[-| :]+\|$", stripped))

    elif re.match(r"^\d+\.", stripped):
        pdf.set_font("Helvetica", size=8)
        pdf.set_text_color(*BROWN)
        pdf.set_x(MARGIN)
        pdf.multi_cell(w, LINE_HEIGHT, _clean(stripped), align="L")

    elif stripped.startswith("- ") or stripped.startswith("* "):
        pdf.set_font("Helvetica", size=10)
        pdf.set_text_color(*BROWN)
        pdf.set_x(MARGIN)
        pdf.multi_cell(w, LINE_HEIGHT, "  - " + _clean(stripped[2:]), align="L")

    elif stripped.startswith("**") and stripped.endswith("**"):
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_text_color(*BROWN)
        pdf.set_x(MARGIN)
        pdf.multi_cell(w, LINE_HEIGHT, _clean(stripped), align="L")

    else:
        pdf.set_font("Helvetica", size=10)
        pdf.set_text_color(*BROWN)
        pdf.set_x(MARGIN)
        pdf.multi_cell(w, LINE_HEIGHT, _clean(stripped), align="L")


def _render_table_row(pdf, line: str, w: float, prev_was_separator: bool = False) -> None:
    if re.match(r"^\|[-| :]+\|$", line):
        return
    cells = [c.strip() for c in line.strip("|").split("|")]
    if not any(cells):
        return

    # Rubrikrad = raden direkt före separator-raden (|---|)
    is_header = not prev_was_separator and any(
        c in ("#", "Titel", "Källa", "Författare", "Ställningstagande") for c in cells
    )
    pdf.set_font("Helvetica", "B" if is_header else "", 8)
    pdf.set_text_color(*NAVY if is_header else BROWN)
    if is_header:
        pdf.set_fill_color(*CREAM)

    row_text = " | ".join(_clean(c)[:40] for c in cells if c)
    if w > 0:
        pdf.set_x(MARGIN)
        pdf.multi_cell(w, LINE_HEIGHT, row_text, fill=is_header, align="L")
    pdf.set_text_color(*BROWN)


def _clean(text: str) -> str:
    """Ta bort Markdown-formattering och tecken utanför latin-1."""
    text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
    text = re.sub(r"\*(.*?)\*", r"\1", text)
    text = re.sub(r"`(.*?)`", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", text)
    text = text.encode("latin-1", errors="ignore").decode("latin-1")
    return text.strip()
