#!/bin/bash
# AFU Import Script — kör alla Databases-importer
# Katalog: ~/19.0/clio-tools/clio-afu/
# Logg:    /tmp/afu_import_<namn>.log

set -e
cd ~/19.0/clio-tools/clio-afu

echo '=== AFU Import-pipeline ==='
echo 'Datum: 'Sat Sep 26 08:16:50     2026
echo ''

# --- Larry Hatch (*U* database, ~9225 fall) ---
echo '[1/4] Larry Hatch...'
python3 afu_import.py --parser larry_hatch 2>&1 | tee /tmp/afu_import_larry.log
echo ''

# --- Robert Moore PrimeBase (Primebaserf.mdb + primrbase.xls) ---
echo '[2/4] Robert Moore PrimeBase...'
python3 afu_import.py --parser generic   --source 'data/downloads/Databases/Robert Moore PrimeBase'   2>&1 | tee /tmp/afu_import_primebase.log
echo ''

# --- Marco Bianchini USOcat ---
echo '[3/4] Marco Bianchini USOcat...'
python3 afu_import.py --parser generic   --source 'data/downloads/Databases/Marco Bianchini USOcat'   2>&1 | tee /tmp/afu_import_usocat.log
echo ''

# --- Jan Aldrich NavCAT (USOs) ---
echo '[4/4] Jan Aldrich NavCAT...'
python3 afu_import.py --parser generic   --source 'data/downloads/Databases/Jan Aldrich NavCAT (USOs)'   2>&1 | tee /tmp/afu_import_navcat.log
echo ''

echo '=== Klart ==='
