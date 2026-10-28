"""
ingest_minne.py — generisk ingest för *minnet-mappar i Dropbox.

Indexerar PDF/DOCX/PPTX/TXT från en källmapp till valfri Qdrant-collection.
Läsaren väljs efter filens innehåll, inte ändelsen (en .docx kan vara PDF,
pptx eller xlsx). Checksum-baserad: hoppar över oförändrade filer.
Körs av cron eller manuellt.

Körning:
  python3 ingest_minne.py --source ~/Dropbox/ftg/AIAB/aiabminnet --collection mem_aiab
  python3 ingest_minne.py --source ~/Dropbox/ftg/GSF/gsfminnet --collection mem_gsf
  python3 ingest_minne.py --source ... --collection ... --force   # tvinga omindexering
"""
from __future__ import annotations
import argparse, hashlib, io, uuid, zipfile
from pathlib import Path
from dotenv import load_dotenv
from openai import OpenAI
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct

_here = Path(__file__).parent
load_dotenv(_here / ".env", override=True) or load_dotenv(_here.parent / ".env", override=True)

EMBED_MODEL   = "text-embedding-3-small"
EMBED_DIM     = 1536
CHUNK_WORDS   = 500
OVERLAP_WORDS = 60
SUPPORTED_EXT = {".pdf", ".docx", ".pptx", ".txt"}

# Första sökvägsdelen i en OOXML-zip avslöjar den verkliga typen
OOXML_PREFIXES = {"word/": "docx", "ppt/": "pptx", "xl/": "xlsx"}
TEMPLATE_CONTENT_TYPES = {
    b"presentationml.template.main+xml": b"presentationml.presentation.main+xml",
    b"wordprocessingml.template.main+xml": b"wordprocessingml.document.main+xml",
}

# ---------------------------------------------------------------------------
def get_client() -> QdrantClient:
    import os
    host = os.getenv("QDRANT_HOST", "localhost")
    port = int(os.getenv("QDRANT_PORT", "6333"))
    return QdrantClient(host=host, port=port)

def ensure_collection(collection: str) -> None:
    c = get_client()
    existing = {col.name for col in c.get_collections().collections}
    if collection not in existing:
        c.create_collection(
            collection_name=collection,
            vectors_config=VectorParams(size=EMBED_DIM, distance=Distance.COSINE),
        )
        print(f"[ingest_minne] Skapade collection: {collection}")
    else:
        print(f"[ingest_minne] Collection finns: {collection}")

# ---------------------------------------------------------------------------
def extract_pdf(path: Path) -> str:
    import pymupdf
    doc = pymupdf.open(str(path))
    return "\n".join(page.get_text() for page in doc)

def extract_docx(path: Path) -> str:
    from docx import Document
    from docx.oxml.ns import qn
    from docx.table import Table
    from docx.text.paragraph import Paragraph
    doc = Document(_without_template_type(path))
    parts = []
    def iter_blocks(parent):
        for child in parent.element.body.iterchildren():
            if child.tag == qn("w:p"):
                yield Paragraph(child, parent)
            elif child.tag == qn("w:tbl"):
                yield Table(child, parent)
    for block in iter_blocks(doc):
        if isinstance(block, Paragraph):
            if block.text.strip():
                parts.append(block.text.strip())
        elif isinstance(block, Table):
            for row in block.rows:
                seen, cells = set(), []
                for cell in row.cells:
                    cid = id(cell._tc)
                    if cid not in seen:
                        seen.add(cid)
                        t = cell.text.strip()
                        if t:
                            cells.append(t)
                if cells:
                    parts.append(" | ".join(cells))
    return "\n".join(parts)

def _without_template_type(path: Path) -> io.BytesIO:
    """Kopia i minnet där mallens innehållstyp (.potx/.dotx) är bytt mot vanlig
    presentation/dokument, eftersom python-pptx och python-docx nekar mallar."""
    out = io.BytesIO()
    with zipfile.ZipFile(path) as zin, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "[Content_Types].xml":
                for template_type, main_type in TEMPLATE_CONTENT_TYPES.items():
                    data = data.replace(template_type, main_type)
            zout.writestr(item, data)
    out.seek(0)
    return out

def extract_pptx(path: Path) -> str:
    from pptx import Presentation
    prs = Presentation(_without_template_type(path))
    parts = []
    for i, slide in enumerate(prs.slides, 1):
        texts = [s.text_frame.text.strip() for s in slide.shapes if s.has_text_frame]
        if texts:
            parts.append(f"[Bild {i}] " + " ".join(t for t in texts if t))
    return "\n".join(parts)

def extract_xlsx(path: Path) -> str:
    from openpyxl import load_workbook
    # Filobjekt i stället för sökväg: openpyxl nekar annars allt som inte heter .xlsx
    wb = load_workbook(io.BytesIO(path.read_bytes()), read_only=True, data_only=True)
    parts = []
    try:
        for sheet in wb.worksheets:
            parts.append(f"[Blad {sheet.title}]")
            for row in sheet.iter_rows(values_only=True):
                cells = [str(v).strip() for v in row if v is not None and str(v).strip()]
                if cells:
                    parts.append(" | ".join(cells))
    finally:
        wb.close()
    return "\n".join(parts)

def detect_kind(path: Path) -> str:
    """Filens verkliga typ utifrån innehållet: pdf, docx, pptx, xlsx eller txt.
    Ändelsen används bara när innehållet inte känns igen (ändelser ljuger i *minnet-mappar)."""
    with path.open("rb") as fh:
        head = fh.read(5)
    if head == b"%PDF-":
        return "pdf"
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
        for prefix, kind in OOXML_PREFIXES.items():
            if any(n.startswith(prefix) for n in names):
                return kind
    return path.suffix.lower().lstrip(".")

def extract_text(path: Path) -> str:
    kind = detect_kind(path)
    if kind != path.suffix.lower().lstrip("."):
        print(f"  → innehållet är {kind}, inte {path.suffix.lower()}")
    if kind == "pdf":   return extract_pdf(path)
    if kind == "docx":  return extract_docx(path)
    if kind == "pptx":  return extract_pptx(path)
    if kind == "xlsx":  return extract_xlsx(path)
    if kind == "txt":   return path.read_text(errors="ignore")
    return ""

# ---------------------------------------------------------------------------
def chunk_text(text: str) -> list[str]:
    words = text.split()
    chunks, i = [], 0
    while i < len(words):
        chunks.append(" ".join(words[i : i + CHUNK_WORDS]))
        i += CHUNK_WORDS - OVERLAP_WORDS
    return [c for c in chunks if len(c.strip()) > 80]

def sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()

def existing_hashes(collection: str, source_file: str) -> set[str]:
    c = get_client()
    results, offset = [], None
    while True:
        page, offset = c.scroll(
            collection_name=collection,
            scroll_filter=None,
            limit=256,
            offset=offset,
            with_payload=True,
        )
        for pt in page:
            if pt.payload.get("source_file") == source_file:
                results.append(pt.payload.get("chunk_hash", ""))
        if offset is None:
            break
    return set(results)

# ---------------------------------------------------------------------------
def ingest_file(path: Path, collection: str, force: bool = False) -> int:
    print(f"\n[ingest_minne] {path.name}")
    text = extract_text(path)
    if not text.strip():
        print("  → ingen text, hoppar över")
        return 0

    chunks    = chunk_text(text)
    known     = set() if force else existing_hashes(collection, path.name)
    oai       = OpenAI()
    qdrant    = get_client()
    new_count = 0

    for idx, chunk in enumerate(chunks):
        h = sha256(chunk)
        if h in known:
            continue
        vec = oai.embeddings.create(input=[chunk], model=EMBED_MODEL).data[0].embedding
        qdrant.upsert(
            collection_name=collection,
            points=[PointStruct(
                id=str(uuid.uuid4()),
                vector=vec,
                payload={
                    "title":       path.stem,
                    "summary":     chunk,
                    "source_file": path.name,
                    "chunk_index": idx,
                    "chunk_hash":  h,
                    "file_type":   path.suffix.lower().lstrip("."),
                    "source":      "minnet",
                },
            )],
        )
        new_count += 1

    print(f"  → {new_count} nya chunks (av {len(chunks)} totalt)")
    return new_count

def ingest_files(files: list[Path], collection: str, force: bool = False) -> tuple[int, list[Path]]:
    """Indexerar filerna en i taget. En fil som fallerar loggas och hoppas över,
    så att resten av mappen ändå indexeras. Returnerar (nya chunks, felande filer)."""
    total, failed = 0, []
    for f in files:
        try:
            total += ingest_file(f, collection, force)
        except Exception as exc:
            print(f"  → FEL: {f}: {type(exc).__name__}: {exc}")
            failed.append(f)
    return total, failed

# ---------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(description="Indexera *minnet-mapp till Qdrant")
    parser.add_argument("--source",     required=True, type=Path, help="Källmapp (Dropbox/*minnet/)")
    parser.add_argument("--collection", required=True, help="Qdrant collection-namn (t.ex. mem_aiab)")
    parser.add_argument("--force",      action="store_true", help="Tvinga omindexering")
    args = parser.parse_args()

    source = args.source.expanduser().resolve()
    if not source.exists():
        print(f"[ingest_minne] FEL: Källmappen finns inte: {source}")
        raise SystemExit(1)

    ensure_collection(args.collection)

    files = [f for f in sorted(source.rglob("*"))
             if f.suffix.lower() in SUPPORTED_EXT and f.is_file()]
    print(f"\n[ingest_minne] {len(files)} filer i {source.name} → {args.collection}")

    total, failed = ingest_files(files, args.collection, args.force)
    print(f"\n[ingest_minne] KLAR — {total} nya chunks i '{args.collection}', {len(failed)} filer med fel")
    if failed:
        raise SystemExit(2)

if __name__ == "__main__":
    main()
