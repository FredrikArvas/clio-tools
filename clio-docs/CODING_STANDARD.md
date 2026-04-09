# Clio Tools – Kodningsstandard

Baserad på mönster som faktiskt finns i koden per 2026-04-02.
Gäller batch-verktygen (clio-docs, clio-vision, clio-transcribe, clio-narrate).
Avvikelser från denna standard är dokumenterade i RAPPORT-avsnittet nedan.

---

## 1. Filnamngivning

| Typ | Mönster | Exempel |
|-----|---------|---------|
| Batch-verktyg | `clio-{tool}-batch.py` | `clio-docs-batch.py` |
| Delad infrastruktur | `clio_{name}.py` | `clio_utils.py`, `clio_check.py` |
| Standalone/fetch | `clio_{name}.py` | `clio_fetch.py` |
| Logfil | `clio-{tool}-batch.log` i skriptets mapp | `clio-docs-batch.log` |

Batch-verktyg ligger i en underkatalog med samma namn som verktyget:
`clio-docs/clio-docs-batch.py`, `clio-vision/clio-vision-batch.py` etc.

---

## 2. Modulens header

Varje skript inleds med en docstring i detta format:

```python
"""
clio-{tool}-batch.py
En-menings beskrivning av vad skriptet gör.
Eventuell ytterligare rad om vad som produceras.

Supported formats: ...   (om relevant)

Usage:
    python clio-{tool}-batch.py <input-folder>

Example:
    python clio-{tool}-batch.py "C:\\Users\\fredr\\..."

Output per file:
    - filename_{SUFFIX}.ext  – beskrivning
    - clio-{tool}-batch.log  – log file in script folder

Environment:
    API_KEY_NAME  – beskrivning av när den behövs
"""
```

Ingen shebang-rad i batch-verktygen. (Library-skripten har `#!/usr/bin/env python3`.)

---

## 3. Imports

### Ordning
1. Stdlib (alfabetisk)
2. Blank rad
3. Lokala imports (clio_utils-blocket)
4. Blank rad
5. Tredjepartsbibliotek importeras **inuti** funktioner (fördröjd import)

### clio_utils-importblocket

Alla batch-verktyg använder detta exakta boilerplate för att hitta config/:

```python
import sys as _sys
_config_path = str(Path(__file__).parent.parent / "config")
if _config_path not in _sys.path:
    _sys.path.insert(0, _config_path)
try:
    from clio_utils import sanitize_filename, has_non_ascii, t
    _UTILS_AVAILABLE = True
except ImportError:
    _UTILS_AVAILABLE = False
    def sanitize_filename(s): return s
    def has_non_ascii(s): return bool(re.search(r'[^\x00-\x7F]', s))
    def t(key, **kwargs): return key
```

Fallback-definitioner krävs för alla importerade funktioner så att skriptet
fungerar även utan config/-mappen.

### Fördröjd import av tunga beroenden

Tunga paket (fitz, docx, faster_whisper, edge_tts m.fl.) importeras inuti
den funktion som använder dem, inte på toppnivå. Undantag: om ett paket
saknas vid körning sker en auto-install via subprocess.

---

## 4. Versionskonstant

Varje skript deklarerar `__version__` direkt efter imports:

```python
__version__ = "2.0.1"
```

Format: `MAJOR.MINOR.PATCH` (SemVer).

---

## 5. Konfigurationsblocket

Direkt efter imports och `__version__`, markerat med sektionsrubrik:

```python
# ── Configuration ─────────────────────────────────────────────────────────────

__version__ = "2.0.1"

OUTPUT_SUFFIX    = "_SUFFIX"
SUPPORTED_FORMATS = {".ext1", ".ext2"}
LOG_FILE         = Path(__file__).parent / "clio-{tool}-batch.log"
API_URL          = "https://..."
MODEL_NAME       = "model-id"
MAX_TOKENS       = 1500
```

Konstanter skrivs med VERSALER. Flera värden justeras med mellanslag för
att kolumnerna ska flukta samman.

---

## 6. Sektionsrubriker

Konsekvent format med `# ──` och lång streck-linje till kolumn ~80:

```python
# ── Section name ──────────────────────────────────────────────────────────────
```

Används för: Configuration, Logging, Helpers, File discovery, Main,
och funktionsspecifika grupperingar.

---

## 7. Logging

```python
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
```

Loggern heter alltid `log` (inte `logger`).
Loggas till fil i skriptmappen **och** stdout simultaneously.
Formatet har **två mellanslag** mellan timestamp och level.

Användning i koden:
- `log.info(...)` – normalt flöde
- `log.warning(...)` – mjuka fel / varningar
- `log.error(...)` – hårda fel som avbryter ett enskilt objekt

Aldrig `print()` för processresultat – det ska gå via `log`. Interaktiva
frågor till användaren görs med `input()` + `print()`.

---

## 8. Funktionssignaturer och returvärden

### Processfunktioner returnerar alltid en tupel

```python
def process_something(file: Path, ...) -> tuple:
    """Docstring."""
    ...
    return True, result, "OK -> filename (size)"   # lyckat
    return False, None, "ERROR: beskrivning"        # misslyckat
    return False, None, "Skipping – already exists: filename"  # hoppar
```

`(ok: bool, result_or_None, message: str)` – detta mönster används
genomgående i docs, vision, transcribe, narrate.

### Filupptäcktsfunktioner

```python
def find_X(folder: Path, recursive: bool = False) -> list:
    if recursive:
        all_files = [p for p in folder.rglob("*") if p.suffix.lower() in SUPPORTED_FORMATS]
    else:
        all_files = [p for p in folder.iterdir() if p.suffix.lower() in SUPPORTED_FORMATS]
    return sorted([p for p in all_files if OUTPUT_SUFFIX not in p.stem])
```

Filtrerar alltid bort redan-processerade filer (de som har OUTPUT_SUFFIX
i stemmet).

---

## 9. main()-funktionens struktur

Alltid samma ordning:

1. Kontrollera `sys.argv` – printa `__doc__` och `sys.exit(1)` om mapp saknas
2. Validera att mappen finns (`is_dir()`)
3. Hitta filer (flat + rekursivt), fråga om undermappar om `extra > 0`
4. Interaktiva val (motor, språk, röst etc.)
5. Logga batchstart: version, antal filer, mapp, `"-" * 60`
6. Loop med tidtagning per fil
7. Sammanfattningsrad

```python
# Submapp-fråga – exakt detta mönster:
files     = find_X(input_folder, recursive=False)
files_sub = find_X(input_folder, recursive=True)
extra     = len(files_sub) - len(files)

if extra > 0:
    print(f"\nFound {len(files)} X(s) in folder and {extra} in subfolders.")
    answer = input("Search subfolders too? [n/J]: ").strip().lower()
    if answer == "j":
        files = files_sub

# Loopens sammanfattningsvariabel – alltid dessa tre:
succeeded = failed = skipped = 0

# Sammanfattningsrad – exakt detta format:
log.info(f"Done in {total:.0f}s – Succeeded: {succeeded} | Skipped: {skipped} | Failed: {failed}")
```

---

## 10. Skip-mönstret

Befintliga outputfiler hoppas alltid över, utan att räknas som fel:

```python
output_file = input_file.parent / f"{input_file.stem}{OUTPUT_SUFFIX}.ext"
if output_file.exists():
    return False, None, f"Skipping – already exists: {output_file.name}"
```

"Skipping" i meddelandet är det token som `main()` testar för att avgöra om
det ska räknas som `skipped` (inte `failed`).

---

## 11. Felhantering

**Processfunktioner** fångar undantag och returnerar ett fel-tuple:

```python
try:
    ...
    return True, result, "OK -> ..."
except Exception as e:
    return False, None, f"EXCEPTION: {e}"
```

**Infrastrukturkod** (state-läsning, loggkonfiguration) använder `except: pass`
eller `except Exception: pass` för tyst fallback.

**Aldrig** `sys.exit()` inuti processfunktioner – bara i `main()`.

---

## 12. Storleks- och tidsformatering

```python
size_mb = file.stat().st_size / 1_048_576   # MB (1024^2)
size_kb = file.stat().st_size / 1024        # KB
elapsed = time.time() - start               # sekunder, float
# Formatering i loggmeddelanden:
f"({size_mb:.1f} MB)"
f"({size_kb:.0f} KB)"
f"({elapsed:.0f}s)"
```

---

## 13. Internationalisation (i18n)

UI-strängar hämtas via `t(key, **kwargs)` från `clio_utils`. Alla nycklar
definieras i `config/locales/sv.json` och `config/locales/en.json`.

Batch-verktygen importerar `t` som en del av clio_utils-blocket (se §3)
och har alltid en fallback `def t(key, **kwargs): return key`.

---

## 14. Paths

Alltid `pathlib.Path`, inte `os.path`. Undantag: `clio-emailfetch` som
predaterar standarden.

```python
from pathlib import Path
LOG_FILE  = Path(__file__).parent / "clio-{tool}-batch.log"
STATE_FILE = Path(__file__).parent.parent / "config" / "clio_state.json"
```

---

## 15. Entry point

```python
if __name__ == "__main__":
    # Auto-install om kritiskt paket saknas (valfritt):
    try:
        import critical_package
    except ImportError:
        subprocess.run([sys.executable, "-m", "pip", "install", "critical_package"], check=True)
    main()
```
