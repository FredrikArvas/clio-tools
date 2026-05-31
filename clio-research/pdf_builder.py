"""pdf_builder.py — Konverterar .md-rapport till PDF med fpdf2."""

from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

MARGIN = 20
MARGIN_TOP = 22   # Toppmarginal — header tar ~8mm, resten är luft
LINE_HEIGHT = 6
FOOTER_URL = "https://fredrik.arvas.se/clio-research/"

# DejaVu Sans — Unicode-font med stöd för svenska tecken
FONT_DIR = "/usr/share/fonts/truetype/dejavu"
FONT_REGULAR = f"{FONT_DIR}/DejaVuSans.ttf"
FONT_BOLD    = f"{FONT_DIR}/DejaVuSans-Bold.ttf"

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

    # Samla rubriker för innehållsförteckning (enbart ## nivå)
    toc_entries = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## ") and not stripped.startswith("### "):
            toc_entries.append(_clean(stripped[3:]))

    pdf = _ClioReport()

    # Sida 1: innehållsförteckning
    if toc_entries:
        pdf.add_page()
        _render_toc(pdf, toc_entries)
        pdf.ln(4)

    # Innehållssidor
    pdf.add_page()
    for line in lines:
        _render_line(pdf, line)

    out_path = md_path.with_suffix(".pdf")
    pdf.output(str(out_path))
    logger.info("[pdf_builder] PDF sparad: %s", out_path)
    return out_path


def _render_toc(pdf, entries: list) -> None:
    """Renderar en innehållsförteckningssida med enbart ## rubriker."""
    w = pdf.w - 2 * MARGIN

    # Rubrik med navy-bakgrund
    pdf.set_fill_color(*NAVY)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("DejaVu", "B", 15)
    pdf.set_x(MARGIN)
    pdf.multi_cell(w, 10, "Innehållsförteckning", fill=True, align="L")
    pdf.ln(6)

    for title in entries:
        # Trunkera om nödvändigt
        display = title[:85] + ("..." if len(title) > 85 else "")
        pdf.set_font("DejaVu", "B", 10)
        pdf.set_text_color(*NAVY)
        pdf.set_x(MARGIN)
        pdf.multi_cell(w, LINE_HEIGHT + 1, display, align="L")
        pdf.ln(1)

    pdf.set_text_color(*BROWN)


class _ClioReport:
    """
    Wrapper runt en FPDF-subklass med korrekt header() och footer().
    header()/footer() anropas automatiskt av fpdf2 vid varje add_page() och output().
    """

    def __init__(self):
        from fpdf import FPDF

        today = datetime.now().strftime("%Y-%m-%d")
        font_regular = FONT_REGULAR
        font_bold    = FONT_BOLD

        class _PDF(FPDF):
            def header(self):
                self.set_font("DejaVu", "", 7)
                self.set_text_color(*GREY)
                w = self.w - 2 * MARGIN
                self.set_xy(MARGIN, 8)
                self.cell(w, 4, "clio-research  |  Evidensrapport", align="L")
                # Tunn linje under header
                self.set_draw_color(*GREY)
                self.line(MARGIN, 13, self.w - MARGIN, 13)
                self.set_draw_color(0, 0, 0)

            def footer(self):
                self.set_y(-12)
                self.set_font("DejaVu", "", 7)
                self.set_text_color(*GREY)
                w = self.w - 2 * MARGIN
                self.set_x(MARGIN)
                self.cell(w / 2, 5, today, align="L")
                self.cell(w / 2, 5, f"Sida {self.page_no()}/{{nb}}", align="R")

        pdf = _PDF()
        pdf.alias_nb_pages()          # aktiverar {nb}-platshållaren för totalt sidantal
        pdf.add_font("DejaVu", "", font_regular, uni=True)
        pdf.add_font("DejaVu", "B", font_bold, uni=True)
        pdf.set_margins(MARGIN, MARGIN_TOP, MARGIN)
        pdf.set_auto_page_break(auto=True, margin=16)
        pdf.set_font("DejaVu", size=10)
        self._pdf = pdf

    def add_page(self):
        self._pdf.add_page()

    def output(self, path: str):
        self._pdf.output(path)

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
        pdf.set_font("DejaVu", "B", 15)
        pdf.set_x(MARGIN)
        pdf.multi_cell(w, 10, _clean(stripped[2:]), fill=True, align="L")
        pdf.set_text_color(*BROWN)
        pdf.ln(3)

    elif stripped.startswith("## "):
        pdf.ln(3)
        pdf.set_text_color(*NAVY)
        pdf.set_font("DejaVu", "B", 12)
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
        pdf.set_font("DejaVu", "B", 10)
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
        pdf.set_font("DejaVu", size=8)
        pdf.set_text_color(*BROWN)
        pdf.set_x(MARGIN)
        pdf.multi_cell(w, LINE_HEIGHT, _clean(stripped), align="L")

    elif stripped.startswith("- ") or stripped.startswith("* "):
        pdf.set_font("DejaVu", size=10)
        pdf.set_text_color(*BROWN)
        pdf.set_x(MARGIN)
        pdf.multi_cell(w, LINE_HEIGHT, "  - " + _clean(stripped[2:]), align="L")

    elif stripped.startswith("**") and stripped.endswith("**"):
        pdf.set_font("DejaVu", "B", 10)
        pdf.set_text_color(*BROWN)
        pdf.set_x(MARGIN)
        pdf.multi_cell(w, LINE_HEIGHT, _clean(stripped), align="L")

    else:
        pdf.set_font("DejaVu", size=10)
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
    pdf.set_font("DejaVu", "B" if is_header else "", 8)
    pdf.set_text_color(*NAVY if is_header else BROWN)
    if is_header:
        pdf.set_fill_color(*CREAM)

    row_text = " | ".join(_clean(c)[:40] for c in cells if c)
    if w > 0:
        pdf.set_x(MARGIN)
        pdf.multi_cell(w, LINE_HEIGHT, row_text, fill=is_header, align="L")
    pdf.set_text_color(*BROWN)


def _clean(text: str) -> str:
    """Ta bort Markdown-formattering."""
    text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)   # **bold**
    text = re.sub(r"\*(.*?)\*",     r"\1", text)   # *italic*
    text = re.sub(r"__(.*?)__",     r"\1", text)   # __bold__
    text = re.sub(r"_(.*?)_",       r"\1", text)   # _italic_
    text = re.sub(r"`(.*?)`",       r"\1", text)   # `code`
    text = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", text)  # [text](url)
    return text.strip()
