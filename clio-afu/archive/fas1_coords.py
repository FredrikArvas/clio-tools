#!/usr/bin/env python3
"""
Fas 1 koordinattest: Testar QB SINGLE (float32) och INTEGER-kodningar
Korrekt sign-konvention per manualen: 'Negative Longitudes are East of Greenwich'
dvs. lon_E lagras som negativ float, lat_S lagras som negativ float.
"""
import struct, math
from pathlib import Path

BASE = Path('/home/clioadmin/19.0/clio-tools/clio-afu')
RND_PATH = BASE / 'data/downloads/Databases/Larry Hatch/original/U.RND'
rnd_data = RND_PATH.read_bytes()

HEADER_SIZE = 122
RECORD_SIZE = 112

def get_record(i):
    return rnd_data[HEADER_SIZE + i*RECORD_SIZE : HEADER_SIZE + (i+1)*RECORD_SIZE]

# Kända poster: (idx, lon_d, lon_m, lon_s, lon_dir, lat_d, lat_m, lat_s, lat_dir)
# lon_dir E → lon stored negative; lon_dir W → positive
# lat_dir N → lat stored positive; lat_dir S → negative
known = [
    (0,  46, 10,  0, 'E',  31,  0,  0, 'N'),  # CHALDEA -593
    (1,  35, 13,  0, 'E',  33, 16,  0, 'N'),  # TYRE -322
    (2,  11, 15, 40, 'E',  43, 59,  0, 'N'),  # ROME -213
    (3,  12, 38, 40, 'E',  41, 44, 20, 'N'),  # ROME -170
    (4,  35, 14,  0, 'E',  31, 46,  0, 'N'),  # JUDEA 70
    (5,   4, 52,  0, 'E',  45, 45,  0, 'N'),  # FRANCE 177
    (6,   8, 34,  0, 'E',  47, 23,  0, 'N'),  # SWITZERLAND 199
    (7, 139, 50,  0, 'E',  35, 40,  0, 'N'),  # JAPAN 989
    (8, 139, 48,  0, 'E',  35, 38,  0, 'N'),  # JAPAN 1015
    (9,  -8, 40,  0, 'W',  42, 15,  0, 'N'),  # SPAIN 1130 — lon dir W!
]

def lon_decimal(d, m, s, direction):
    v = d + m/60 + s/3600
    # Manualens konvention: E=negativ (reversed!), W=positiv
    return -v if direction == 'E' else v

def lat_decimal(d, m, s, direction):
    v = d + m/60 + s/3600
    # Manualens konvention: N=positiv, S=negativ (standard)
    return v if direction == 'N' else -v

print('=== FLOAT32 TEST (QB SINGLE) ===')
print('sign-konvention: lon E=neg, W=pos; lat N=pos, S=neg')
for idx, ld, lm, ls, ldir, ald, alm, als, adir in known:
    raw = get_record(idx)
    lon = lon_decimal(ld, lm, ls, ldir)
    lat = lat_decimal(ald, alm, als, adir)
    print(f'\nPost {idx}: expected lon={lon:.4f}, lat={lat:.4f}')
    for off in range(20):
        for fmt, name in [('<f', 'LE'), ('>f', 'BE')]:
            if off+4 <= RECORD_SIZE:
                v = struct.unpack(fmt, raw[off:off+4])[0]
                if abs(v - lon) < 0.01:
                    print(f'  LON off={off} {name}: {v:.4f} ✓')
                if abs(v - lat) < 0.01:
                    print(f'  LAT off={off} {name}: {v:.4f} ✓')

print('\n=== ARCSECOND INT16s TEST (lon_arcsec, lat_arcsec, sign-rev E) ===')
for idx, ld, lm, ls, ldir, ald, alm, als, adir in known:
    raw = get_record(idx)
    lon_sec_val = ld*3600 + lm*60 + ls
    lat_sec_val = ald*3600 + alm*60 + als
    lon_sec = -lon_sec_val if ldir == 'E' else lon_sec_val   # E=neg
    lat_sec = lat_sec_val if adir == 'N' else -lat_sec_val
    print(f'\nPost {idx}: lon_sec={lon_sec}, lat_sec={lat_sec}')
    for off in range(20):
        for w in [2, 4]:
            if off+w <= 21:
                for le in [True, False]:
                    for sg in [True, False]:
                        v = int.from_bytes(raw[off:off+w], 'little' if le else 'big', signed=sg)
                        if v == lon_sec:
                            print(f'  LON_SEC off={off} w={w} {"LE" if le else "BE"} signed={sg}: {v} ✓')
                        if v == lat_sec:
                            print(f'  LAT_SEC off={off} w={w} {"LE" if le else "BE"} signed={sg}: {v} ✓')

print('\n=== DEGREE * 1000 INT TEST ===')
for idx, ld, lm, ls, ldir, ald, alm, als, adir in known:
    raw = get_record(idx)
    lon_milli = round(lon_decimal(ld, lm, ls, ldir) * 1000)
    lat_milli = round(lat_decimal(ald, alm, als, adir) * 1000)
    print(f'\nPost {idx}: lon*1000={lon_milli}, lat*1000={lat_milli}')
    for off in range(20):
        for w in [2, 4]:
            if off+w <= 21:
                for le in [True, False]:
                    for sg in [True, False]:
                        v = int.from_bytes(raw[off:off+w], 'little' if le else 'big', signed=sg)
                        if v == lon_milli:
                            print(f'  LON*1000 off={off} w={w} {"LE" if le else "BE"} signed={sg}: {v} ✓')
                        if v == lat_milli:
                            print(f'  LAT*1000 off={off} w={w} {"LE" if le else "BE"} signed={sg}: {v} ✓')

print('\n=== RAW HEX BYTES 0-20 (post 0-9) + FLOAT32 ALLA POSITIONER ===')
for idx in range(10):
    raw = get_record(idx)
    print(f'\nPost {idx} bytes 0-20: {raw[:21].hex()}')
    # Visa alla float32-värden i bytes 0-20
    for off in range(18):
        le_f = struct.unpack('<f', raw[off:off+4])[0]
        be_f = struct.unpack('>f', raw[off:off+4])[0]
        if -200 < le_f < 200:  # Rimligt koordinatintervall
            print(f'  float32 LE off={off}: {le_f:.4f}')
        if -200 < be_f < 200:
            print(f'  float32 BE off={off}: {be_f:.4f}')

print('\nKLAR')
