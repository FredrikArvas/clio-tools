"""
run.py
Huvudingång för clio-agent-job — jobbsökar- och förändringssignalagent.
Orchestrerar: hämta → dedup → analysera → rapportera → skicka.

Användning:
    python run.py --dry-run                        # Kör utan att skicka mail
    python run.py --once                           # Kör en gång (default)
    python run.py --profile profiles/richard.yaml  # Välj profil explicit
    python run.py --last-run                       # Visa senaste körningssummering
    python run.py --dry-run --verbose              # Visa detaljer om varje artikel
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Säkerställ UTF-8-utskrift på Windows-terminaler med cp1252
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if sys.stderr.encoding and sys.stderr.encoding.lower() != "utf-8":
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

_BASE_DIR = Path(__file__).parent
_ROOT_DIR = _BASE_DIR.parent
_SOURCES_DIR = _BASE_DIR / "sources"

# sys.path — lägg till modulens egna dir + clio-core
for _p in [str(_BASE_DIR), str(_SOURCES_DIR), str(_ROOT_DIR), str(_ROOT_DIR / "clio-core")]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

# Ladda .env
try:
    from dotenv import load_dotenv
    load_dotenv(_ROOT_DIR / ".env", override=True)
    load_dotenv(_BASE_DIR / ".env", override=True)
except ImportError:
    pass


def _load_cfg() -> dict:
    try:
        import yaml
        p = _BASE_DIR / "config.yaml"
        if p.exists():
            with open(p, encoding="utf-8") as fh:
                return yaml.safe_load(fh) or {}
    except ImportError:
        pass
    return {}


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="clio-agent-job — förändringssignalagent")
    p.add_argument("--dry-run", action="store_true",
                   help="Kör pipeline men skicka inget mail")
    p.add_argument("--once", action="store_true",
                   help="Kör en gång och avsluta (default-beteende)")
    p.add_argument("--profile", type=Path, default=None,
                   help="Sökväg till YAML-profil (default: profiles/richard.yaml)")
    p.add_argument("--last-run", action="store_true",
                   help="Visa senaste körningssummering och avsluta")
    p.add_argument("--verbose", "-v", action="store_true",
                   help="Visa detaljer om varje artikel (även icke-matchande)")
    p.add_argument("--onboard", action="store_true",
                   help="Skicka onboarding-mail och avsluta (hoppar över analys)")
    return p.parse_args(argv)


def run(
    dry_run: bool = False,
    profile_path: Path | None = None,
    verbose: bool = False,
    force_onboard: bool = False,
) -> int:
    """
    Kör en komplett bevakningscykel.
    Returnerar antal matchade artiklar (≥ 0), eller -1 vid konfigurationsfel.
    """
    from sources.registry import load_sources
    from source_base import SourceError  # samma modul som source_rss.py använder
    from profiles.profile_loader import load_profile, profile_summary
    from state import is_seen, mark_seen, log_run, last_run_summary, is_onboarded, mark_onboarded
    from analyzer import analyze
    from reporter import build_report, MatchedArticle
    from notifier import send_report, send_onboarding
    from onboarding import build_onboarding_mail

    cfg = _load_cfg()
    threshold: int = int(cfg.get("threshold", 50))
    model: str = cfg.get("model", "claude-haiku-4-5-20251001")

    # Ladda profil
    try:
        profile = load_profile(profile_path)
    except (ValueError, ImportError, FileNotFoundError) as e:
        print(f"[FEL] Profil: {e}", file=sys.stderr)
        return -1

    candidate_email = profile.get("email", "")
    if not candidate_email and not dry_run:
        print("[FEL] Kandidatens e-postadress saknas i profilen (fält: email).", file=sys.stderr)
        return -1

    # Onboarding — skicka välkomstmail vid första körningen (eller --onboard)
    is_recruiter = profile.get("profile_type") == "recruiter"
    if not is_recruiter and (force_onboard or not is_onboarded(candidate_email)):
        print(f"[clio-job] Skickar onboarding-mail till {candidate_email}...")
        ob_subject, ob_text, ob_html = build_onboarding_mail(profile)
        try:
            send_onboarding(ob_subject, ob_text, ob_html, candidate_email, dry_run=dry_run)
            if not dry_run:
                mark_onboarded(candidate_email)
                print(f"[clio-job] Onboarding skickat och markerat.")
        except Exception as e:
            print(f"[VARNING] Onboarding-mail misslyckades: {e}", file=sys.stderr)
        if force_onboard:
            return 0

    print(f"[clio-job] Profil: {profile_summary(profile)}")
    print(f"[clio-job] Tröskel: {threshold}  |  Modell: {model}")
    if dry_run:
        print("[clio-job] DRY-RUN — inget mail skickas")
    print()

    # Ladda källor
    try:
        sources = load_sources()
    except ImportError as e:
        print(f"[FEL] {e}", file=sys.stderr)
        return -1

    if not sources:
        print("[VARNING] Inga aktiva källor i sources.yaml")
        return 0

    # Hämta artiklar
    all_articles = []
    for source in sources:
        try:
            articles = source.fetch()
            print(f"  {source.name}: {len(articles)} artiklar")
            all_articles.extend(articles)
        except SourceError as e:
            print(f"  [FEL] {source.name}: {e}")

    total_fetched = len(all_articles)
    print(f"\n[clio-job] Totalt hämtade: {total_fetched} artiklar")

    # Filtrera redan-sedda
    new_articles = [a for a in all_articles if not is_seen(a.article_id)]
    total_new = len(new_articles)
    print(f"[clio-job] Nya (ej tidigare sedda): {total_new}")

    if not new_articles:
        print("[clio-job] Inga nya artiklar — tyst körning.")
        log_run(total_fetched, 0, 0, 0, dry_run)
        return 0

    # Analysera mot profil
    print(f"\n[clio-job] Analyserar {total_new} artiklar mot profil...")
    matched = []

    for i, article in enumerate(new_articles, 1):
        if verbose:
            print(f"  [{i}/{total_new}] {article.title[:70]}…")

        result = analyze(article, profile, model=model)

        mark_seen(
            article.article_id,
            url=article.url,
            title=article.title,
            source=article.source,
            match_score=result.match_score,
        )

        if result.error:
            if verbose:
                print(f"    [FEL] {result.error}")
            continue

        if verbose:
            print(f"    -> {result.signal_type} ({result.signal_strength}) score={result.match_score}")

        if result.match_score >= threshold and result.is_relevant:
            matched.append(MatchedArticle(article=article, result=result))

    total_matched = len(matched)
    print(f"[clio-job] Matchade (score >= {threshold}): {total_matched}")

    # Skicka rapport vid fynd
    mail_sent = 0
    if matched:
        subject, body_text, body_html = build_report(
            matched, profile, total_fetched, total_new
        )
        to_addr = candidate_email if candidate_email else "test@example.com"
        try:
            sent = send_report(subject, body_text, body_html, to_addr, dry_run=dry_run)
            if sent and not dry_run:
                mail_sent = 1
                print(f"[clio-job] Rapport skickad till {to_addr}")
        except (RuntimeError, ValueError, FileNotFoundError) as e:
            print(f"[FEL] Kunde inte skicka mail: {e}", file=sys.stderr)
    else:
        print("[clio-job] Inga matchande artiklar — tyst körning.")

    log_run(total_fetched, total_new, total_matched, mail_sent, dry_run)
    return total_matched


def main(argv=None) -> None:
    args = parse_args(argv)

    if args.last_run:
        # Importera state direkt
        from state import last_run_summary
        print(last_run_summary())
        return

    result = run(
        dry_run=args.dry_run,
        profile_path=args.profile,
        verbose=args.verbose,
        force_onboard=args.onboard,
    )
    sys.exit(0 if result >= 0 else 1)


if __name__ == "__main__":
    main()
