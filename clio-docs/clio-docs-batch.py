"""
clio-docs-batch.py
Batch OCR processing of scanned PDF files.
Produces a searchable PDF (_OCR.pdf) and a markdown text file (_OCR.md) per book.

Usage:
    python clio-docs-batch.py <input-folder>

Example:
    python clio-docs-batch.py "C:\\Users\\fredr\\Documents\\Dropbox\\projekt\\UAP"

Output per book:
    - filename_OCR.pdf  – searchable PDF with text layer
    - filename_OCR.md   – plain text with metadata per page
    - clio-docs-batch.log – log file in script folder
"""

import sys
import re
import time
import logging
import subprocess
from pathlib import Path
from datetime import datetime

from clio_core.utils import propose_rename, sanitize_filename, has_non_ascii

# ── Configuration ─────────────────────────────────────────────────────────────

TESSERACT_CMD = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
__version__ = "2.0.1"

LANGUAGES  = "swe+eng"
OCR_SUFFIX = "_OCR"
LOG_FILE   = Path(__file__).parent / "clio-docs-batch.log"

# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)

# ── Helpers ───────────────────────────────────────────────────────────────────

def find_pdfs(folder: Path, recursive: bool = False) -> list:
    """Returns all PDFs that have not yet been OCR'd."""
    if recursive:
        all_files = list(folder.rglob("*.pdf"))
    else:
        all_files = list(folder.glob("*.pdf"))
    return sorted([p for p in all_files if OCR_SUFFIX not in p.stem])


def ocr_pdf(input_file: Path) -> tuple:
    """
    Runs OCRmyPDF with --sidecar for text extraction.
    Returns (ok, output_file, sidecar_file, message).
    """
    output_file  = input_file.parent / f"{input_file.stem}{OCR_SUFFIX}{input_file.suffix}"
    sidecar_file = input_file.parent / f"{input_file.stem}{OCR_SUFFIX}.txt"

    if output_file.exists():
        return False, None, None, f"Skipping – OCR file already exists: {output_file.name}"

    import tempfile, shutil

    # OCRmyPDF on Windows cannot handle non-ASCII paths – use temp files
    use_temp = has_non_ascii(str(input_file))
    tmp_dir = None

    if use_temp:
        tmp_dir      = Path(tempfile.mkdtemp())
        src          = tmp_dir / "input.pdf"
        dst          = tmp_dir / "output.pdf"
        sidecar_tmp  = tmp_dir / "sidecar.txt"
        shutil.copy2(input_file, src)
        ocr_in, ocr_out, ocr_sidecar = src, dst, sidecar_tmp
    else:
        ocr_in, ocr_out, ocr_sidecar = input_file, output_file, sidecar_file

    cmd = [
        sys.executable, "-m", "ocrmypdf",
        "--language",         LANGUAGES,
        "--tesseract-timeout","300",
        "--force-ocr",
        "--deskew",
        "--optimize",         "1",
        "--sidecar",          str(ocr_sidecar),
        str(ocr_in),
        str(ocr_out),
    ]

    try:
        import threading
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        stop = threading.Event()
        def heartbeat():
            elapsed = 0
            while not stop.is_set():
                stop.wait(30)
                if not stop.is_set():
                    elapsed += 30
                    print(f"    ... running ({elapsed}s)", flush=True)
        t = threading.Thread(target=heartbeat, daemon=True)
        t.start()

        _, stderr_b = proc.communicate()
        stop.set()
        stderr = stderr_b.decode("utf-8", errors="replace")

        if proc.returncode == 0:
            if use_temp:
                shutil.copy2(ocr_out, output_file)
                shutil.copy2(ocr_sidecar, sidecar_file)
                shutil.rmtree(tmp_dir, ignore_errors=True)
            size_mb = output_file.stat().st_size / 1_048_576
            return True, output_file, sidecar_file, f"OK -> {output_file.name} ({size_mb:.1f} MB)"
        else:
            if use_temp:
                shutil.rmtree(tmp_dir, ignore_errors=True)
            lines = stderr.strip().splitlines()
            error = lines[-1] if lines else "unknown error"
            return False, None, None, f"ERROR: {error}"

    except Exception as e:
        if use_temp and tmp_dir:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        return False, None, None, f"EXCEPTION: {e}"


def extract_md(ocr_file: Path, original_name: str, ocr_date: str,
               sidecar_file: Path = None) -> tuple:
    """
    Builds MD file from sidecar text (scanned PDFs) or pymupdf (digital PDFs).
    Returns (ok, message).
    """
    md_file = ocr_file.parent / f"{ocr_file.stem}.md"

    if md_file.exists():
        return False, f"Skipping – MD already exists: {md_file.name}"

    # ── Method 1: Sidecar (scanned PDFs) ─────────────────────────────────────
    if sidecar_file and sidecar_file.exists():
        try:
            import fitz
            doc = fitz.open(str(ocr_file))
            page_count = len(doc)
            doc.close()

            raw = sidecar_file.read_bytes()
            try:
                text = raw.decode("utf-8")
                if "Ã" in text:
                    text = raw.decode("latin-1").encode("latin-1").decode("utf-8", errors="replace")
            except UnicodeDecodeError:
                text = raw.decode("latin-1")

            pages = text.split("\x0c")
            lines = []
            lines.append(f"# {original_name}\n")
            lines.append(f"- **Source:** {original_name}.pdf")
            lines.append(f"- **OCR date:** {ocr_date}")
            lines.append(f"- **Pages:** {page_count}")
            lines.append(f"- **Language:** {LANGUAGES}")
            lines.append(f"- **Method:** sidecar\n")
            lines.append("---\n")

            for i in range(page_count):
                page_text = pages[i].strip() if i < len(pages) else ""
                lines.append(f"## Page {i + 1}\n")
                lines.append(f"<!-- source: {original_name}.pdf | page: {i + 1} | ocr-date: {ocr_date} -->\n")
                lines.append(page_text if page_text else "*[No text extracted from this page]*")
                lines.append("\n---\n")

            md_file.write_text("\n".join(lines), encoding="utf-8")
            size_kb = md_file.stat().st_size / 1024
            return True, f"OK -> {md_file.name} ({size_kb:.0f} KB, {page_count} pages, sidecar)"

        except Exception as e:
            return False, f"EXCEPTION (sidecar): {e}"

    # ── Method 2: pymupdf (digital PDFs with text layer) ─────────────────────
    try:
        import fitz
        doc = fitz.open(str(ocr_file))
        page_count = len(doc)
        lines = []

        lines.append(f"# {original_name}\n")
        lines.append(f"- **Source:** {original_name}.pdf")
        lines.append(f"- **OCR date:** {ocr_date}")
        lines.append(f"- **Pages:** {page_count}")
        lines.append(f"- **Language:** {LANGUAGES}\n")
        lines.append("---\n")

        for i, page in enumerate(doc, start=1):
            text = page.get_text().strip()
            lines.append(f"## Page {i}\n")
            lines.append(f"<!-- source: {original_name}.pdf | page: {i} | ocr-date: {ocr_date} -->\n")
            lines.append(text if text else "*[No text extracted from this page]*")
            lines.append("\n---\n")

        doc.close()
        md_file.write_text("\n".join(lines), encoding="utf-8")
        size_kb = md_file.stat().st_size / 1024
        return True, f"OK -> {md_file.name} ({size_kb:.0f} KB, {page_count} pages, pymupdf)"

    except Exception as e:
        return False, f"EXCEPTION (pymupdf): {e}"


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    input_folder = Path(sys.argv[1])
    if not input_folder.is_dir():
        log.error(f"Folder not found: {input_folder}")
        sys.exit(1)

    # Recursive search option
    pdfs     = find_pdfs(input_folder, recursive=False)
    pdfs_sub = find_pdfs(input_folder, recursive=True)
    extra    = len(pdfs_sub) - len(pdfs)

    if extra > 0:
        print(f"\nFound {len(pdfs)} PDF(s) in folder and {extra} in subfolders.")
        answer = input("Search subfolders too? [n/J]: ").strip().lower()
        if answer == "j":
            pdfs = pdfs_sub

    if not pdfs:
        log.info("No PDFs to process.")
        return

    # Filename sanitation
    to_rename = [(f, sanitize_filename(f.name)) for f in pdfs
                     if f.name != sanitize_filename(f.name)]
    if to_rename:
        print(f"\n{len(to_rename)} file(s) have names that should be sanitized:")
        for original, new_name in to_rename:
            print(f"  {original.name}")
            print(f"→ {new_name}")
        answer = input("\nRename according to suggestion? [n/J]: ").strip().lower()
        if answer == "j":
            for original, new_name in to_rename:
                new_path = original.parent / new_name
                try:
                    original.rename(new_path)
                    log.info(f"Renamed: {original.name} → {new_name}")
                except PermissionError:
                    log.warning(f"Cannot rename {original.name} – file is locked (Dropbox?). Continuing with original name.")
            pdfs = find_pdfs(input_folder, recursive=False)
            if extra > 0 and len(find_pdfs(input_folder, recursive=True)) > len(pdfs):
                pdfs = find_pdfs(input_folder, recursive=True)
        else:
            print("Filenames unchanged. Note: files with special characters may cause errors.")

    ocr_date    = datetime.now().strftime("%Y-%m-%d")
    log.info(f"clio-docs-batch v{__version__}")
    log.info(f"Starting batch – {len(pdfs)} file(s)")
    log.info(f"Folder: {input_folder}")
    log.info("-" * 60)

    succeeded = failed = skipped = 0
    total_start = time.time()

    for pdf in pdfs:
        log.info(f"Processing: {pdf.name}")
        start = time.time()

        ok, ocr_file, sidecar_file, message = ocr_pdf(pdf)
        elapsed = time.time() - start

        if ok:
            log.info(f"  PDF  {message} ({elapsed:.0f}s)")
            succeeded += 1
            md_ok, md_msg = extract_md(ocr_file, pdf.stem, ocr_date, sidecar_file)
            log.info(f"  MD   {md_msg}") if md_ok else log.warning(f"  MD   {md_msg}")

        elif "already exists" in message or "Skipping" in message:
            log.info(f"  {message}")
            skipped += 1
            ocr_path = pdf.parent / f"{pdf.stem}{OCR_SUFFIX}{pdf.suffix}"
            if ocr_path.exists():
                md_ok, md_msg = extract_md(ocr_path, pdf.stem, ocr_date)
                if md_ok:
                    log.info(f"  MD   {md_msg}")
        else:
            log.error(f"  {message}")
            failed += 1

    total = time.time() - total_start
    log.info("-" * 60)
    log.info(f"Done in {total:.0f}s – Succeeded: {succeeded} | Skipped: {skipped} | Failed: {failed}")


if __name__ == "__main__":
    try:
        import pypdf
    except ImportError:
        log.info("Installing pypdf...")
        subprocess.run([sys.executable, "-m", "pip", "install", "pypdf"], check=True)
        import pypdf
    main()
