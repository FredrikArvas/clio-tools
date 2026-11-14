"""
reader.py — Extraherar stycken ur .docx-filer till strukturerat JSON.

Användning:
  python reader.py --en boken_en.docx --sv boken_sv.docx --chapter 1 --out testdata/chapter_01.json

Kräver att båda filerna är kapitelvist uppdelade, eller att --start-heading används
för att avgränsa kapitlet.

Om --en / --sv saknas skapas ett tomt par-JSON som kan fyllas manuellt.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


def _paragraphs_from_docx(path: Path, start_heading: str | None = None,
                           stop_heading: str | None = None) -> list[str]:
    """Läs .docx och returnera lista med stycken (icke-tomma)."""
    try:
        from docx import Document
    except ImportError:
        print("python-docx saknas — installera: pip install python-docx", file=sys.stderr)
        sys.exit(1)

    doc = Document(path)
    collecting = start_heading is None
    result = []

    for para in doc.paragraphs:
        text = para.text.strip()
        if not text:
            continue

        # Aktivera insamling vid rätt rubrik
        if start_heading and not collecting:
            if re.search(re.escape(start_heading), text, re.IGNORECASE):
                collecting = True
            continue

        # Stoppa vid nästa rubrik (om stop_heading inte angetts, stanna vid nästa Heading)
        if collecting:
            if stop_heading and re.search(re.escape(stop_heading), text, re.IGNORECASE):
                break
            if para.style and para.style.name.startswith("Heading") and start_heading:
                break
            result.append(text)

    return result


def _build_pairs(en_paras: list[str], sv_paras: list[str]) -> list[dict]:
    """Para ihop EN och SV-stycken ordningsvis. Kortare lista avgör."""
    pairs = []
    for i, (en, sv) in enumerate(zip(en_paras, sv_paras), start=1):
        pairs.append({"id": i, "en": en, "sv": sv})
    return pairs


def main() -> None:
    parser = argparse.ArgumentParser(description="clio-bookrev reader — docx → JSON")
    parser.add_argument("--en", type=Path, help="Sökväg till engelska .docx-filen")
    parser.add_argument("--sv", type=Path, help="Sökväg till svenska .docx-filen")
    parser.add_argument("--chapter", default="1", help="Kapitelnummer (för metadata)")
    parser.add_argument("--title-en", default="", help="Kapitelrubrik på engelska")
    parser.add_argument("--title-sv", default="", help="Kapitelrubrik på svenska")
    parser.add_argument("--start-en", help="Rubriktext där insamling börjar (EN)")
    parser.add_argument("--start-sv", help="Rubriktext där insamling börjar (SV)")
    parser.add_argument("--out", type=Path, required=True, help="Utdatafil (JSON)")
    args = parser.parse_args()

    en_paras: list[str] = []
    sv_paras: list[str] = []

    if args.en:
        en_paras = _paragraphs_from_docx(args.en, start_heading=args.start_en)
        print(f"EN: {len(en_paras)} stycken lästa från {args.en.name}")

    if args.sv:
        sv_paras = _paragraphs_from_docx(args.sv, start_heading=args.start_sv)
        print(f"SV: {len(sv_paras)} stycken lästa från {args.sv.name}")

    if en_paras and sv_paras and len(en_paras) != len(sv_paras):
        print(f"Varning: antal stycken skiljer sig (EN={len(en_paras)}, SV={len(sv_paras)}). "
              f"Kontrollera kapitelmatchningen.")

    pairs = _build_pairs(en_paras, sv_paras)

    output = {
        "chapter": args.chapter,
        "title_en": args.title_en,
        "title_sv": args.title_sv,
        "pairs": pairs,
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Sparad: {args.out}  ({len(pairs)} par)")


if __name__ == "__main__":
    main()
