#!/usr/bin/env python3
"""
apply_dates.py — Sätter mtime + Windows ctime på lokala WAV-filer
baserat på inspelningsdatum lästa från AudioShare-skärmdumpar.

Användning:
    python apply_dates.py
    python apply_dates.py --dest "C:/Users/fredr/Dropbox/Audio/iPhone-inspelningar"
    python apply_dates.py --dry-run
"""

import argparse
import ctypes
import ctypes.wintypes
import re
import sys
import unicodedata
from datetime import datetime
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DEFAULT_DEST = r"C:\Users\fredr\Dropbox\Audio\iPhone-inspelningar"

# ── Datum extraherade från AudioShare-skärmdumpar 2026-05-04 ─────────────────
# Format: "filnamn (original från iOS)": "YYYY-MM-DD HH:MM:SS"
RAW_DATES = {
    "Bellman nr 11. Aurora ja må hon leva. .wav": "2026-04-17 19:03:19",
    "Per8.wav":                                    "2025-07-09 13:32:14",
    "Per9.wav":                                    "2025-07-09 13:34:24",
    "PerN1.wav":                                   "2025-07-09 11:03:16",
    "Recorded Audio Alice Lilja Lom Lom.wav":      "2025-06-23 22:02:06",
    "Recorded Audio.wav":                          "2023-04-14 10:00:52",
    "Recorded Audio(1).wav":                       "2023-04-14 17:33:52",
    "Recorded Audio(2).wav":                       "2023-04-14 18:16:08",
    "Recorded Audio(3).wav":                       "2023-04-14 19:07:48",
    "Recorded Audio(4).wav":                       "2023-04-14 19:19:55",
    "Recorded Audio(5).wav":                       "2023-04-14 19:35:22",
    "Recorded Audio(6).wav":                       "2023-04-14 19:46:35",
    "Recorded Audio(7).wav":                       "2023-04-14 19:54:04",
    "Recorded Audio(8).wav":                       "2023-04-14 19:54:59",
    "Recorded Audio(9).wav":                       "2023-04-14 20:04:34",
    "Recorded Audio(10).wav":                      "2023-04-14 22:53:15",
    "Recorded Audio(11).wav":                      "2023-04-14 22:56:49",
    "Recorded Audio(12).wav":                      "2023-04-14 23:12:57",
    "Recorded Audio(13).wav":                      "2023-04-15 15:48:56",
    "Recorded Audio(14).wav":                      "2023-04-15 16:54:56",
    "Recorded Audio(15).wav":                      "2023-04-15 17:07:19",
    "Recorded Audio(16).wav":                      "2023-04-15 17:23:52",
    "Recorded Audio(17).wav":                      "2023-04-15 17:49:13",
    "Recorded Audio(18).wav":                      "2023-04-15 18:11:36",
    "Recorded Audio(19).wav":                      "2023-04-15 18:49:06",
    "Recorded Audio(20).wav":                      "2023-04-15 19:14:11",
    "Recorded Audio(21).wav":                      "2023-04-15 19:34:13",
    "Recorded Audio(22).wav":                      "2023-04-15 19:57:02",
    "Recorded Audio(23).wav":                      "2023-04-15 20:16:42",
    "Recorded Audio(24).wav":                      "2023-04-15 20:31:19",
    "Recorded Audio(25).wav":                      "2023-04-15 20:35:18",
    "Recorded Audio(26).wav":                      "2023-04-15 21:04:00",
    "Recorded Audio(27).wav":                      "2023-04-15 21:12:42",
    "Recorded Audio(28).wav":                      "2023-04-15 22:33:51",
    "Recorded Audio(29).wav":                      "2023-04-15 22:56:39",
    "Recorded Audio(30).wav":                      "2023-04-15 22:59:59",
    "Recorded Audio(31).wav":                      "2023-04-15 23:00:25",
    "Recorded Audio(32).wav":                      "2023-04-15 23:36:45",
    "Recorded Audio(33).wav":                      "2023-04-15 23:58:40",
    "Recorded Audio(34).wav":                      "2023-04-16 00:06:14",
    "Recorded Audio(35).wav":                      "2023-04-16 01:13:24",
    "Recorded Audio(36).wav":                      "2023-04-16 18:20:40",
    "Recorded Audio(37).wav":                      "2023-04-16 19:30:03",
    "Recorded Audio(38).wav":                      "2023-04-16 19:47:14",
    "Recorded Audio(39).wav":                      "2023-04-16 20:15:25",
    "Recorded Audio(40).wav":                      "2023-04-16 20:31:21",
    "Recorded Audio(41).wav":                      "2023-05-15 18:34:31",
    "Recorded Audio(42).wav":                      "2023-05-15 18:49:35",
    "Recorded Audio(43).wav":                      "2023-07-19 13:22:52",
    "Recorded Audio(44).wav":                      "2023-06-16 12:26:57",
    "Recorded Audio(45).wav":                      "2023-07-22 19:12:02",
    "Recorded Audio(46).wav":                      "2023-07-26 14:58:41",
    "Recorded Audio(47).wav":                      "2023-08-23 14:08:59",
    "Recorded Audio(48).wav":                      "2024-02-13 06:07:44",
    "Recorded Audio(48)_Björn_om_släkten.wav":     "2023-12-30 17:23:19",
    "Recorded Audio(49).wav":                      "2024-03-09 13:41:56",
    "Recorded Audio(49)_Björn_om_släkten.wav":     "2023-12-30 17:42:35",
    "Recorded Audio(50).wav":                      "2024-04-17 09:52:37",
    "Recorded Audio(50)_Björn_om_släkten.wav":     "2023-12-30 17:52:33",
    "Recorded Audio(51).wav":                      "2024-04-22 21:57:49",
    "Recorded Audio(52) Björn läser Paula bok.wav":"2024-06-01 16:21:33",
    "Recorded Audio(52).wav":                      "2024-06-13 13:46:03",
    "Recorded Audio(53).wav":                      "2024-06-30 15:40:33",
    "Recorded Audio(54).wav":                      "2024-08-07 08:48:49",
    "Recorded Audio(55).wav":                      "2024-08-07 16:02:28",
    "Recorded Audio(56).wav":                      "2024-08-14 14:51:40",
    "Recorded Audio(57).wav":                      "2024-08-19 09:10:48",
    "Recorded Audio(58).wav":                      "2024-12-07 14:02:26",
    "Recorded Audio(59).wav":                      "2024-12-07 14:07:49",
    "Recorded Audio(60).wav":                      "2024-12-07 14:11:01",
    "Recorded Audio(61).wav":                      "2024-12-07 14:16:43",
    "Recorded Audio(62).wav":                      "2024-12-07 14:21:50",
    "Recorded Audio(63).wav":                      "2024-12-07 14:28:24",
    "Recorded Audio(64).wav":                      "2024-12-07 14:31:23",
    "Recorded Audio(65).wav":                      "2024-12-07 14:34:41",
    "Recorded Audio(66).wav":                      "2024-12-07 14:36:18",
    "Recorded Audio(67).wav":                      "2024-12-07 14:39:31",
    "Recorded Audio(68).wav":                      "2024-12-07 14:43:03",
    "Recorded Audio(69).wav":                      "2024-12-07 14:51:15",
    "Recorded Audio(70).wav":                      "2024-12-07 14:55:56",
    "Recorded Audio(71).wav":                      "2024-12-07 15:00:39",
    "Recorded Audio(72).wav":                      "2024-12-07 15:07:35",
    "Recorded Audio(73).wav":                      "2024-12-07 15:15:08",
    "Recorded Audio(74).wav":                      "2025-01-18 13:43:43",
    "Recorded Audio(75).wav":                      "2025-01-21 13:58:20",
    "Recorded Audio(76).wav":                      "2025-02-18 19:16:51",
    "Recorded Audio(77).wav":                      "2025-02-18 19:34:31",
    "Recorded Audio(78).wav":                      "2025-05-10 11:15:07",
    "Recorded Audio(79).wav":                      "2025-08-08 06:00:09",
    "Recorded Audio(80).wav":                      "2025-07-09 11:29:41",
    "Recorded Audio(81).wav":                      "2025-07-09 12:38:09",
    "Recorded Audio(82).wav":                      "2025-07-09 13:15:34",
    "Recorded Audio(83).wav":                      "2025-07-09 13:27:14",
    "Recorded Audio(84).wav":                      "2025-07-09 13:27:14",
    "Recorded Audio(85).wav":                      "2025-08-29 20:19:38",
    "Recorded Audio(86).wav":                      "2025-09-03 13:03:06",
    "Recorded Audio(87).wav":                      "2025-09-04 12:50:40",
    "Recorded Audio(88).wav":                      "2025-09-25 14:13:12",
    "Recorded Audio(89).wav":                      "2025-10-16 20:49:33",
    "Recorded Audio(90).wav":                      "2025-11-22 17:15:26",
    "Recorded Audio(91).wav":                      "2025-11-24 19:48:20",
    "Recorded Audio(92).wav":                      "2025-12-13 21:38:22",
    "Recorded Audio(93).wav":                      "2025-12-13 21:52:50",
    "Recorded Audio(94).wav":                      "2025-12-16 15:29:26",
    "Recorded Audio(95).wav":                      "2025-12-16 15:33:25",
    "Recorded Audio(96).wav":                      "2026-02-12 20:05:56",
    "Recorded Audio(97)-normalized.wav":           "2026-02-19 22:48:18",
    "Recorded Audio(97).wav":                      "2026-02-19 19:59:52",
    "Recorded Audio(98).wav":                      "2026-03-10 13:54:38",
    "Recorded Audio(99).wav":                      "2026-03-14 19:55:26",
    "Recorded Audio(100).wav":                     "2026-03-25 21:39:29",
    "Recorded Audio(101).wav":                     "2026-03-28 11:59:38",
    "Recorded Audio(102).wav":                     "2026-03-28 21:15:34",
    "Recorded Audio(103).wav":                     "2026-03-28 21:19:09",
    "Recorded Audio(104).wav":                     "2026-03-28 21:27:06",
    "Recorded Audio(105).wav":                     "2026-03-28 22:10:39",
    "Recorded Audio(106).wav":                     "2026-04-03 12:38:12",
    "Recorded Audio(107).wav":                     "2026-04-05 20:14:40",
    "Recorded Audio(108).wav":                     "2026-04-11 10:20:49",
    "Recorded Audio(109).wav":                     "2026-04-11 10:35:23",
    "Recorded Audio(110).wav":                     "2026-04-11 11:10:08",
    "Recorded Audio(111).wav":                     "2026-04-11 13:09:17",
    "Recorded Audio(112).wav":                     "2026-04-11 14:22:38",
    "Recorded Audio(113).wav":                     "2026-04-11 14:25:21",
    "Recorded Audio(114).wav":                     "2026-04-11 14:29:33",
    "Recorded Audio(115).wav":                     "2026-04-11 15:59:51",
    "Recorded Audio(116).wav":                     "2026-04-15 19:19:26",
    "Recorded Audio(117).wav":                     "2026-04-21 21:05:25",
    "Recorded Audio(118).wav":                     "2026-04-24 13:22:02",
    "Recorded Audio(119).wav":                     "2026-04-24 13:27:37",
    "Recorded Audio(120).wav":                     "2026-04-24 13:58:59",
    "Recorded Audio(121).wav":                     "2026-04-24 16:48:58",
    "Recorded Audio(122)-trimmed.wav":             "2026-04-28 13:05:19",
    "Recorded Audio(122).wav":                     "2026-04-28 13:04:59",
    "Recorded Audio(123).wav":                     "2026-05-01 16:28:06",
    "Recorded Audio(124).wav":                     "2026-05-01 17:32:51",
    "Recorded Audio(125).wav":                     "2026-05-02 09:46:32",
    "Recorded Audio(126)-trimmed(1).wav":          "2026-05-01 22:28:48",
    "Recorded Audio(126)-trimmed.wav":             "2026-05-01 22:28:26",
    "Recorded Audio(126).wav":                     "2026-05-01 22:09:09",
    "Recorded Audio(127).wav":                     "2026-05-02 10:29:17",
    "Recorded Audio(128).wav":                     "2026-05-02 11:13:45",
    "Recorded Audio(129).wav":                     "2026-05-02 12:56:32",
    "Recorded Audio(130).wav":                     "2026-05-02 15:20:49",
    "Recorded Audio(131).wav":                     "2026-05-02 17:04:34",
    "Recorded Audio(132).wav":                     "2026-05-02 17:59:41",
    "Recovered 2026-05-03 09:20:45.wav":           "2026-05-02 21:38:05",
}

# ── Hjälpfunktioner ───────────────────────────────────────────────────────────

_ILLEGAL = re.compile(r'[\\/:*?"<>|]')

def _norm(name: str) -> str:
    """Samma normalisering som main.py: NFC + ersätt Windows-ogiltiga tecken."""
    return _ILLEGAL.sub("_", unicodedata.normalize("NFC", name))


def _ts_to_filetime(ts: float) -> tuple[int, int]:
    """Konverterar Unix-timestamp till Windows FILETIME (low, high)."""
    EPOCH_OFFSET = 116_444_736_000_000_000  # 100-ns ticks 1601→1970
    ft = int(ts * 10_000_000) + EPOCH_OFFSET
    return ft & 0xFFFFFFFF, ft >> 32


def set_windows_times(path: Path, ts: float) -> bool:
    """Sätter creation time, access time och modified time via kernel32."""
    GENERIC_WRITE = 0x40000000
    OPEN_EXISTING = 3
    FILE_FLAG_BACKUP_SEMANTICS = 0x02000000

    handle = ctypes.windll.kernel32.CreateFileW(
        str(path), GENERIC_WRITE, 0, None,
        OPEN_EXISTING, FILE_FLAG_BACKUP_SEMANTICS, None,
    )
    INVALID = ctypes.wintypes.HANDLE(-1).value
    if handle == INVALID:
        return False

    class FILETIME(ctypes.Structure):
        _fields_ = [("dwLowDateTime", ctypes.c_uint32),
                    ("dwHighDateTime", ctypes.c_uint32)]

    low, high = _ts_to_filetime(ts)
    ft = FILETIME(low, high)
    ok = bool(ctypes.windll.kernel32.SetFileTime(
        handle,
        ctypes.byref(ft),   # lpCreationTime
        ctypes.byref(ft),   # lpLastAccessTime
        ctypes.byref(ft),   # lpLastWriteTime
    ))
    ctypes.windll.kernel32.CloseHandle(handle)
    return ok


# ── Bygg lookup-index: normaliserat namn → timestamp ─────────────────────────

def build_date_index() -> dict[str, float]:
    index = {}
    for raw_name, date_str in RAW_DATES.items():
        ts = datetime.fromisoformat(date_str).timestamp()
        # Lägg in både original-NFC och normaliserat (med _ istf :)
        index[unicodedata.normalize("NFC", raw_name)] = ts
        index[_norm(raw_name)] = ts
    return index


# ── Huvudfunktion ─────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Applicera inspelningsdatum på WAV-filer")
    parser.add_argument("--dest",    default=DEFAULT_DEST)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    dest = Path(args.dest)
    date_index = build_date_index()

    wav_files = sorted(dest.glob("*.wav"))
    print(f"Hittade {len(wav_files)} WAV-filer i {dest}\n")

    matched   = 0
    skipped   = 0
    not_found = []

    for wav in wav_files:
        # Försök matcha med normaliserat namn
        ts = date_index.get(wav.name) or date_index.get(_norm(wav.name))
        if ts is None:
            not_found.append(wav.name)
            continue

        date_str = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
        print(f"  {'[dry]' if args.dry_run else '    '} {wav.name}  →  {date_str}")

        if not args.dry_run:
            import os
            os.utime(wav, (ts, ts))           # mtime + atime (plattformsoberoende)
            if not set_windows_times(wav, ts): # ctime via kernel32
                print(f"    ⚠ kernel32 misslyckades för {wav.name}")
            matched += 1
        else:
            matched += 1

    print(f"\nResultat: {matched} uppdaterade, {len(not_found)} utan datum-data")
    if not_found:
        print("\nSaknar datum för:")
        for n in not_found:
            print(f"  {n}")


if __name__ == "__main__":
    main()
