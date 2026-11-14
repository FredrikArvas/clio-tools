# U.RND Binary Format — Larry Hatch *U* Database

Reverse-engineered 2026-09 via brute-force correlation against PDF ground-truth.

## File Structure

```
Offset 0     : 10-byte file header (version/counts, not decoded)
Offset 10    : 112-byte "virtual record 0" (same layout as data records)
  → offset 10+102 = 112 : year[record_0] as int16s LE = -593 (CHALDEA)
Offset 122   : 18,122 × 112-byte data records
```

**Total file size:** 122 + 18122 × 112 = 2,029,786 bytes

## Record Layout (112 bytes each)

| Offset | Bytes | Type       | Field         | Notes |
|--------|-------|------------|---------------|-------|
| 0      | 1     | uint8      | **UNKNOWN**   | Correlates with lon_d but formula unclear |
| 1–2    | 2     | int16s LE  | **LAT**       | arcsec/20; N=positive, S=negative. **100% confirmed** |
| 3–4    | 2     | int16s LE? | UNKNOWN       | Possibly elevation (meters), -99 = null |
| 5–6    | 2     | int16s LE? | UNKNOWN       | Possibly rel_alt, 0x03E7=999 seen as frequent null |
| 7–8    | 2     | ?          | UNKNOWN       | Byte 7 is often 0x00 |
| 9–11   | 3     | ASCII      | **STATE**     | 3-char region/state code. **96% confirmed** |
| 12     | 1     | null       | STATE null    | String terminator |
| 13–20  | 8     | ?          | UNKNOWN       | Possibly LON + prec + continent/country indices |
| 21–98  | 78    | ASCII      | **SUMMARY**   | Fixed-width null-padded text string. **100% confirmed** |
| 99     | 1     | uint8      | **REF_NO**    | Reference number. **Confirmed** |
| 100    | 1     | uint8      | **PAGE_NO**   | Page number. **Confirmed** |
| 101    | 1     | uint8      | **(S<<4)\|C** | High nibble=strangeness (0–9), low=credibility (0–9). **100% confirmed** |
| 102–103| 2     | int16s LE  | **YEAR[i+1]** | Year of *next* record (off-by-1 design). For record 0: see header[112:114]. **100% confirmed** |
| 104    | 1     | ?          | UNKNOWN       | |
| 105    | 1     | uint8      | **MONTH[i+1]**| Month of next record. **99.6% confirmed** |
| 106    | 1     | uint8      | **DAY[i+1]**  | Day of next record. **67.1% — partial** |
| 107–108| 2     | ?          | UNKNOWN       | Possibly hour/minute |
| 109    | 1     | uint8      | **DUR[i+1]**  | Duration (minutes, 0–255) of next record. **100% confirmed** |
| 110–111| 2     | ?          | UNKNOWN       | |

## Off-by-1 Pattern

Records store date/time metadata of the *next* record at their own offsets 102–109.  
To read record[i]'s year: use `header[112:114]` for i=0, else `binary[i-1][102:104]`.  
For the importer: **use PDF-parsed values** (year/month/day/hour/minute/duration) — 
they are 100% reliable from the text export and avoid the off-by-1 complexity.

## Signed Latitude Encoding

```python
lat_raw = int.from_bytes(record[1:3], 'little', signed=True)
lat_deg = lat_raw * 20 / 3600   # positive=North, negative=South
```

Example: lat=31°0'N → 31*3600/20 = 5580 = 0x15CC → bytes: CC 15 ✓

## Fields Sourced from PDF (not binary)

The following fields are parsed from the ASCII text export (PDF):
- **Year, month, day, hour, minute** — from "YYYY/MM/DD HH:MM" format
- **Duration** — from integer field after timestamp
- **LON** (d:m:s:dir) — binary encoding undetermined; PDF is authoritative
- **PREC** (4-char accuracy code) — not found in binary as ASCII or int
- **CONTINENT** (3-char code) — not found as ASCII in bytes 0–20
- **COUNTRY** (3-char code) — not found as ASCII
- **TERRAIN** — from "Ref# N ... Page No. N : TERRAIN_CODE" line
- **STRANGENESS, CREDIBILITY** — also derivable from binary byte 101

## Record Count

18,122 records (year=3000 marks deleted records, kept for ID stability).

## Import Strategy

1. Parse PDF for all fields (primary source)
2. Read binary for: strangeness/credibility (byte 101), state (bytes 9–11)  
   as cross-validation and for records where PDF parse is uncertain
3. Use content hash (year+lat+lon_d+summary prefix) as stable record ID
4. Attribute block (64 booleans) — not yet decoded; import as NULL
