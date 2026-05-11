Kör en Definition of Done-kontroll mot aktuella ändringar i repot innan push.

## Steg 1 — Hämta ändringar

Kör dessa kommandon och ta med resultaten i analysen:
- `git diff HEAD` — ostagade ändringar
- `git diff --cached` — stagade ändringar
- `git status` — övergripande status
- `git stash list` — kontrollera att inget glömts i stash

## Steg 2 — Kontrollera varje DoD-punkt

Gå igenom punkterna nedan mot de faktiska ändringarna. Markera varje punkt
som ✅ (uppfylld), ❌ (ej uppfylld) eller ➖ (ej tillämplig för denna ändring).

Motivera kortfattat varje ❌.

### 11.1 Kod och säkerhet
- [ ] Alla pytest-tester är gröna (`python clio_qc.py` eller `pytest`)
- [ ] Inga hårdkodade API-nycklar, lösenord eller tokens i ändrade filer
- [ ] Inga nya .env-filer eller hemligheter inkluderade i git
- [ ] Externa API-anrop hanterar fel explicit (try/except med loggning)
- [ ] Inga tysta undantag (`except: pass` utan loggning)

### 11.2 Tester
- [ ] Nya funktioner täcks av minst ett automatiserat test
- [ ] Tester bevisar BÅDE lyckad och misslyckad väg för ny logik
- [ ] Befintliga tester bryter inte

### 11.3 Dokumentation
- [ ] NCC uppdaterad med beslut från denna session (kontrollera Notion #clio)
- [ ] CLAUDE.md uppdaterad i berörd modul om install/usage ändrats
- [ ] Arkitekturbeslut dokumenterade som ADR om ett sådant fattats

### 11.4 AI-integrationer (hoppa över om ändringen inte berör Claude API)
- [ ] Modellnamn definierade som konstanter (MODEL_SONNET, MODEL_HAIKU)
- [ ] Prompts separerade från anropslogik
- [ ] Claude API-felhantering täcker rate limits och timeouts

### 11.5 Drift (hoppa över om ändringen inte berör schemaläggning)
- [ ] Systemd timers uppdaterade om nya jobb lagts till
- [ ] Loggning på plats för nya automatiserade körningar
- [ ] Rollback-steg dokumenterade för komplexa infrastrukturändringar

### 11.6 Namnstandard
- [ ] PEP 8 följs i alla ändrade filer
- [ ] Inga förkortningar (auth, cfg, ctx, perm) i nya identifierare
- [ ] Inga synonymer för samma koncept introducerade

## Steg 3 — Sammanfattning

Presentera resultatet i detta format:

```
DoD-kontroll [datum]
────────────────────────────────────
✅  11.1 Kod och säkerhet       (5/5)
✅  11.2 Tester                 (3/3)
❌  11.3 Dokumentation          (1/3)  ← NCC ej uppdaterad
➖  11.4 AI-integrationer       (ej tillämplig)
➖  11.5 Drift                  (ej tillämplig)
✅  11.6 Namnstandard           (3/3)
────────────────────────────────────
RESULTAT: ❌ Pusha inte ännu.
```

Om alla tillämpliga punkter är ✅:
→ "RESULTAT: ✅ Redo att pusha. Kör git push."

Om en eller flera är ❌:
→ "RESULTAT: ❌ Pusha inte ännu." + lista vad som behöver åtgärdas.

## Steg 4 — Åtgärdsplan (vid ❌)

Lista konkreta nästa steg för varje ❌-punkt. Erbjud att hjälpa till med
de som kan åtgärdas direkt i denna session.
