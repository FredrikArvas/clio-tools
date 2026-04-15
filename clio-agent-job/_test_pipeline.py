"""Snabbtest: 5 Di-artiklar genom hela pipeline."""
import sys, os
from pathlib import Path

BASE = Path(__file__).parent
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE / "sources"))

from dotenv import load_dotenv
load_dotenv(BASE.parent / ".env", override=True)

from sources.registry import load_sources
from profiles.profile_loader import load_profile, profile_summary
from analyzer import analyze
from reporter import build_report, MatchedArticle

profile = load_profile()
sources = load_sources()
print(f"Profil: {profile_summary(profile)}")
print(f"Källor: {len(sources)} aktiva")

articles = sources[0].fetch()[:5]
print(f"Testar 5 Di-artiklar...\n")

matched = []
for i, a in enumerate(articles, 1):
    r = analyze(a, profile)
    flag = " MATCH!" if r.match_score >= 50 else ""
    print(f"  [{i}] {a.title[:55]}")
    if r.error:
        print(f"       FEL: {r.error[:80]}")
    else:
        print(f"       -> {r.signal_type} ({r.signal_strength}) score={r.match_score}{flag}")
    if r.match_score >= 50 and r.is_relevant:
        matched.append(MatchedArticle(article=a, result=r))

print(f"\nMatchade: {len(matched)}")
if matched:
    subject, body_text, _ = build_report(matched, profile, 5, 5)
    print(f"Amne: {subject}\n")
    print("\n".join(body_text.split("\n")[:25]))
else:
    print("Inga matchande -- korrekt tyst korning.")
