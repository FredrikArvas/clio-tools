# clio-transcribe

NCC: läs ncc https://www.notion.so/35b67666d98a81498cfeecc2df238893 (#cliotools — verktygsindex)

## Syfte
Batch-transkribering av WAV-filer till Markdown med tidsstämplar.
Motor: faster-whisper. Svenska: KB-Whisper large. Andra språk: Whisper large-v3.

## Kör batch
```bash
cd ~/19.0/clio-tools && source .venv/bin/activate
python clio-transcribe/clio-transcribe-batch.py "/mnt/dropbox/Audio/iPhone-inspelningar"
```
- Enter = svenska (KB-Whisper large)
- Hoppar automatiskt över filer som redan har _TRANSKRIPT.md

## Output
`filnamn_TRANSKRIPT.md` i samma katalog som källfilen — tidsstämplar per segment.

## Modell
Satt till `large` (WHISPER_SIZE i skriptet). GPU (CUDA) används automatiskt om tillgängligt.
