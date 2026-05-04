"""pdf_builder.py — Konverterar .md-rapport till enkel PDF med fpdf2."""

from __future__ import annotations

import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

FONT_FAMILY = "Helvetica"
MARGIN = 20
LINE_HEIGHT = 6


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
    pdf = _create_pdf()

    for line in text.splitlines():
        _render_line(pdf, line)

    out_path = md_path.with_suffix(".pdf")
    pdf.output(str(out_path))
    logger.info("[pdf_builder] PDF sparad: %s", out_path)
    return out_path


def _create_pdf():
    from fpdf import FPDF

    pdf = FPDF()
    pdf.set_margins(MARGIN, MARGIN, MARGIN)
    pdf.set_auto_page_break(auto=True, margin=MARGIN)
    pdf.add_page()
    pdf.set_font(FONT_FAMILY, size=10)
    return pdf


def _render_line(pdf, line: str) -> None:
    stripped = line.strip()
    # Återställ alltid x till vänstermarginalen innan varje rad
    pdf.set_x(MARGIN)
    w = pdf.w - 2 * MARGIN

    if stripped.startswith("# ") and not stripped.startswith("## "):
        pdf.set_font(FONT_FAMILY, "B", 16)
        pdf.multi_cell(w, 9, _clean(stripped[2:]))
        pdf.ln(3)

    elif stripped.startswith("## "):
        pdf.set_font(FONT_FAMILY, "B", 13)
        pdf.multi_cell(w, 8, _clean(stripped[3:]))
        pdf.ln(2)

    elif stripped.startswith("### "):
        pdf.set_font(FONT_FAMILY, "B", 11)
        pdf.multi_cell(w, 7, _clean(stripped[4:]))
        pdf.ln(1)

    elif stripped == "---":
        pdf.ln(3)
        pdf.set_draw_color(180, 180, 180)
        pdf.line(MARGIN, pdf.get_y(), pdf.w - MARGIN, pdf.get_y())
        pdf.ln(3)

    elif stripped == "":
        pdf.ln(LINE_HEIGHT / 2)

    elif stripped.startswith("|"):
        _render_table_row(pdf, stripped, w)

    elif re.match(r"^\d+\.", stripped):
        pdf.set_font(FONT_FAMILY, size=9)
        pdf.multi_cell(w, LINE_HEIGHT, _clean(stripped))

    elif stripped.startswith("- ") or stripped.startswith("* "):
        pdf.set_font(FONT_FAMILY, size=10)
        pdf.multi_cell(w, LINE_HEIGHT, "  - " + _clean(stripped[2:]))

    else:
        pdf.set_font(FONT_FAMILY, size=10)
        pdf.multi_cell(w, LINE_HEIGHT, _clean(stripped))


def _render_table_row(pdf, line: str, w: float) -> None:
    if re.match(r"^\|[-| :]+\|$", line):
        return
    cells = [c.strip() for c in line.strip("|").split("|")]
    if not any(cells):
        return

    pdf.set_font(FONT_FAMILY, size=8)
    row_text = " | ".join(_clean(c)[:35] for c in cells if c)
    if w > 0:
        pdf.multi_cell(w, LINE_HEIGHT, row_text)


def _clean(text: str) -> str:
    """Ta bort Markdown-formattering och emoji som fpdf inte kan rendera."""
    text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
    text = re.sub(r"\*(.*?)\*", r"\1", text)
    text = re.sub(r"`(.*?)`", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", text)
    # Ta bort emoji och tecken utanför latin-1
    text = text.encode("latin-1", errors="ignore").decode("latin-1")
    return text.strip()
