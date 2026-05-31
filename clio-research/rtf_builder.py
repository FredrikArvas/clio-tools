"""rtf_builder.py — Konverterar .md-rapport till RTF (inga externa beroenden).

RTF öppnas direkt i Word, LibreOffice och macOS Preview utan font-installationer.
Genererar exakt samma innehåll som pdf_builder men via RTF-formatet.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

# AIAB-färger som RTF-färgtabellindex (1-baserat)
_C_NAVY  = 1   # (42, 63, 111)
_C_BLUE  = 2   # (74, 111, 165)
_C_BROWN = 3   # (61, 46, 10)
_C_GREY  = 4   # (180, 180, 180)
_C_WHITE = 5   # (255, 255, 255)
_C_GOLD  = 6   # (200, 168, 75)

_COLOUR_TABLE = (
    r"{\colortbl;"
    r"\red42\green63\blue111;"    # 1 NAVY
    r"\red74\green111\blue165;"   # 2 BLUE
    r"\red61\green46\blue10;"     # 3 BROWN
    r"\red180\green180\blue180;"  # 4 GREY
    r"\red255\green255\blue255;"  # 5 WHITE
    r"\red200\green168\blue75;"   # 6 GOLD
    r"}"
)

_FONT_TABLE = (
    r"{\fonttbl"
    r"{\f0\froman\fcharset0 Georgia;}"
    r"{\f1\fswiss\fcharset0 Arial;}"
    r"{\f2\fmodern\fcharset0 Courier New;}"
    r"}"
)


# ---------------------------------------------------------------------------
# Publik API
# ---------------------------------------------------------------------------

def build_rtf(md_path: Path) -> Path:
    """
    Läser [run_id].md och skriver [run_id].rtf i samma katalog.
    Returnerar sökväg till RTF-filen.
    """
    text = md_path.read_text(encoding="utf-8")
    lines = text.splitlines()

    parts: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if stripped.startswith("| ") or stripped.startswith("|---"):
            # Samla ihop alla rader i tabellen
            table_lines: list[str] = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                table_lines.append(lines[i].strip())
                i += 1
            parts.append(_render_table(table_lines))
            continue

        parts.append(_render_line(stripped))
        i += 1

    today = datetime.now().strftime("%Y-%m-%d")
    basename = md_path.stem

    header_rtf = (
        r"{\header\pard\qr\f1\fs16\cf4 "
        + _esc("clio-research  |  Evidensrapport")
        + r"\par}"
    )
    footer_rtf = (
        r"{\footer\pard\f1\fs16\cf4 "
        + _esc(today)
        + r"\tab\tab\tab\tab Sida \chpgn\par}"
    )

    document = (
        r"{\rtf1\ansi\ansicpg1252\uc1\deff1"
        + "\n" + _FONT_TABLE
        + "\n" + _COLOUR_TABLE
        + r"\widowctrl\hyphauto"
        + r"\margl1440\margr1440\margt1440\margb1440"
        + "\n" + header_rtf
        + "\n" + footer_rtf
        + "\n"
        + "\n".join(parts)
        + "\n}"
    )

    out_path = md_path.with_suffix(".rtf")
    # RTF ska vara latin-1 / windows-1252; icke-kodningsbara tecken ersätts med \uN?
    out_path.write_bytes(_encode_rtf(document))
    logger.info("[rtf_builder] RTF sparad: %s (%d bytes)", out_path, out_path.stat().st_size)
    return out_path


# ---------------------------------------------------------------------------
# Intern rendering
# ---------------------------------------------------------------------------

def _render_line(stripped: str) -> str:
    if not stripped:
        return r"\par "

    if stripped == "---":
        return (
            r"\pard\sb120\sa120"
            r"{\f1\fs18\cf4 "
            + "_" * 80
            + r"}\par "
        )

    if stripped.startswith("# ") and not stripped.startswith("## "):
        title = _clean(stripped[2:])
        return (
            r"\pard\sb240\sa60"
            r"{\f1\b\fs30\cf5\highlight1 " + _esc(title) + r"}"
            r"\par "
        )

    if stripped.startswith("## "):
        title = _clean(stripped[3:])
        return (
            r"\pard\sb200\sa60\brdrb\brdrs\brdrw10\brdrcf2"
            r"{\f1\b\fs24\cf1 " + _esc(title) + r"}"
            r"\par "
        )

    if stripped.startswith("### "):
        title = _clean(stripped[4:])
        return (
            r"\pard\sb160\sa40"
            r"{\f1\b\fs21\cf2 " + _esc(title) + r"}"
            r"\par "
        )

    if stripped.startswith("- ") or stripped.startswith("* "):
        content = _inline(stripped[2:])
        return (
            r"\pard\li360\fi-180\sb40\sa40"
            r"{\f1\fs20\cf3 \bullet  " + content + r"}"
            r"\par "
        )

    if re.match(r"^\d+\.", stripped):
        content = _inline(stripped)
        return (
            r"\pard\li360\fi-180\sb20\sa20"
            r"{\f1\fs18\cf3 " + content + r"}"
            r"\par "
        )

    if stripped.startswith("**") and stripped.endswith("**"):
        content = _inline(stripped)
        return (
            r"\pard\sb60\sa20"
            r"{\f1\b\fs20\cf3 " + content + r"}"
            r"\par "
        )

    # Brödtext
    content = _inline(stripped)
    return (
        r"\pard\sb40\sa40"
        r"{\f1\fs20\cf3 " + content + r"}"
        r"\par "
    )


def _render_table(lines: list[str]) -> str:
    """Renderar en MD-tabell som RTF-tabell med enkla kanter."""
    rows = []
    for line in lines:
        if re.match(r"^\|[-| :]+\|$", line):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        cells = [c for c in cells if c != ""]
        if cells:
            rows.append(cells)

    if not rows:
        return ""

    n_cols  = max(len(r) for r in rows)
    col_w   = 8640 // n_cols           # total textbredd ~12 cm i twips
    col_pos = [(i + 1) * col_w for i in range(n_cols)]

    parts = [r"\pard\sb80\sa80 "]
    for row_idx, cells in enumerate(rows):
        is_header = row_idx == 0
        parts.append(r"\trowd\trgaph108\trleft0")
        for cp in col_pos:
            parts.append(
                r"\clbrdrt\brdrw5\brdrs\clbrdrl\brdrw5\brdrs"
                r"\clbrdrb\brdrw5\brdrs\clbrdrr\brdrw5\brdrs"
                + r"\cellx" + str(cp)
            )
        parts.append("\n")
        for cell in cells:
            text = _clean(cell)
            fmt = r"\b\cf1" if is_header else r"\cf3"
            parts.append(
                r"\pard\intbl\f1\fs18" + fmt + r" " + _esc(text) + r"\cell "
            )
        parts.append(r"\row ")

    return "\n".join(parts)


def _inline(text: str) -> str:
    """Konverterar inline MD-formattering till RTF."""
    # **bold**
    text = re.sub(
        r"\*\*(.+?)\*\*",
        lambda m: r"{\b " + _esc(m.group(1)) + r"}",
        text,
    )
    # *italic* och _italic_
    text = re.sub(
        r"\*(.+?)\*|_(.+?)_",
        lambda m: r"{\i " + _esc(m.group(1) or m.group(2)) + r"}",
        text,
    )
    # `code`
    text = re.sub(
        r"`(.+?)`",
        lambda m: r"{\f2\fs18 " + _esc(m.group(1)) + r"}",
        text,
    )
    # [link](url) — visa bara länktexten
    text = re.sub(r"\[([^\]]+)\]\([^\)]+\)", lambda m: _esc(m.group(1)), text)
    # Resten som ej redan är RTF
    return text


def _clean(text: str) -> str:
    """Tar bort all MD-formattering och returnerar ren text."""
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"\*(.+?)\*",     r"\1", text)
    text = re.sub(r"_(.+?)_",       r"\1", text)
    text = re.sub(r"`(.+?)`",       r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", text)
    return text.strip()


def _esc(text: str) -> str:
    """Escapar text för RTF: backslash, klamrar och icke-ASCII via \\uN?."""
    out = []
    for ch in text:
        if ch == "\\":
            out.append("\\\\")
        elif ch == "{":
            out.append("\\{")
        elif ch == "}":
            out.append("\\}")
        elif ord(ch) <= 127:
            out.append(ch)
        else:
            # Unicode-escape: \uN? — ? är fallback-tecken (visas om font saknar glyfen)
            out.append(f"\\u{ord(ch)}?")
    return "".join(out)


def _encode_rtf(document: str) -> bytes:
    """Kodas som ASCII — icke-ASCII är redan escaped via \\uN?."""
    return document.encode("ascii", errors="replace")
