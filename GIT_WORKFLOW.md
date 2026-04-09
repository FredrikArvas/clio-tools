# Git-flöde för clio-tools

Repo: https://github.com/FredrikArvas/clio-tools

---

## Vanlig push (efter kodändringar)

```bash
cd C:/Users/fredr/git/clio-tools
git add <filer>          # eller: git add .
git commit -m "Beskriv vad du ändrat"
git push
```

Pre-commit hooken körs automatiskt vid commit och kontrollerar:
- Syntax på alla kritiska Python-filer
- Alla unit-tester (100 st, <5s)

Om hooken misslyckas fixar du felet och commitar igen.

---

## Release (ny version)

1. Kör alla tester:
   ```bash
   python tests/run_tests.py --all
   ```
2. Fyll i `tests/uat/CHECKLIST.md` manuellt
3. Uppdatera version i berört script (`__version__ = "X.Y.Z"`)
4. Uppdatera `CHANGELOG.md`
5. Tagga och pusha:
   ```bash
   git add .
   git commit -m "Release vX.Y.Z"
   git tag vX.Y.Z
   git push && git push --tags
   ```

---

## Första gången på en ny dator

```bash
git clone https://github.com/FredrikArvas/clio-tools.git
cd clio-tools
git config core.hooksPath .githooks
pip install -r requirements.txt
python config/clio_check.py
```

---

## Felsökning

| Problem | Lösning |
|---------|---------|
| Pre-commit misslyckas | Läs felmeddelandet, fixa koden, commita igen |
| Push nekad (non-fast-forward) | `git pull --rebase` sedan `git push` |
| Glömt sätta hooksPath | `git config core.hooksPath .githooks` |
