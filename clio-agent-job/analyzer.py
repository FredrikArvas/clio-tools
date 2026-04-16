"""
analyzer.py
Signalanalytiker — anropar Claude API med artikel + kandidatprofil.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

_BASE_DIR = Path(__file__).parent
_SOURCES_DIR = _BASE_DIR / "sources"
if str(_SOURCES_DIR) not in sys.path:
    sys.path.insert(0, str(_SOURCES_DIR))

from source_base import Article  # noqa: E402

try:
    import anthropic
    _HAS_ANTHROPIC = True
except ImportError:
    _HAS_ANTHROPIC = False

# Jobbsökarläge — prompt-mall
_PROMPT_TEMPLATE = """\
DU ÄR: Strategisk arbetsmarknadsanalytiker och karriärcoach.

KANDIDATPROFIL:
{profil_text}

ARTIKEL:
Titel: {title}
Källa: {source}
Datum: {published}
Innehåll: {body_snippet}

UPPDRAG:
1. Identifiera om artikeln innehåller förändringssignaler (tillväxt,
   förvärv, ny ledning, digitalisering, omorganisation, investering,
   upphandling). Ange signalstyrka: svag / medel / stark.
2. Bedöm om signalen är relevant för kandidatprofilen (0–100).
3. Om match >= 50: föreslå 1–3 konkreta roller som logiskt kan uppstå.
4. Rekommendera åtgärd: ansök_nu / nätverka / bevaka / avstå.
5. Ge ett kort kontakttips (vem, vilken vinkel).

Om artikeln inte innehåller relevanta signaler: svara INGEN_SIGNAL.

Svara ALLTID på svenska. Svara ALLTID i JSON enligt schema:
{{
  "signal_type": "ny_ledning | förvärv | digitalisering | upphandling | investering | omorganisation | tillväxt | övrigt",
  "signal_strength": "svag|medel|stark",
  "match_score": int,
  "match_reason": str,
  "potential_roles": [str],
  "recommended_action": "ansök_nu|nätverka|bevaka|avstå",
  "contact_hint": str
}}
Om INGEN_SIGNAL: {{"signal_type": "ingen", "match_score": 0}}
"""


def _profile_to_text(profile: dict) -> str:
    """Jobbsökarläge — profil som text."""
    lines = [
        f"Namn: {profile.get('name', '')}",
        f"Roll: {profile.get('role', '')}",
        f"Senioritet: {profile.get('seniority', '')}",
        f"Geografi: {profile.get('geography', '')}",
        "",
        "Bakgrund:",
    ]
    for b in profile.get("background", []):
        lines.append(f"  - {b}")
    lines.append("")
    lines.append("Målroller:")
    for r in profile.get("target_roles", []):
        lines.append(f"  - {r}")
    return "\n".join(lines)


@dataclass
class AnalysisResult:
    article_id: str
    signal_type: str = "ingen"
    signal_strength: str = "svag"
    match_score: int = 0
    match_reason: str = ""
    potential_roles: list = field(default_factory=list)
    recommended_action: str = "avstå"
    contact_hint: str = ""
    error: Optional[str] = None

    @property
    def is_relevant(self) -> bool:
        return self.match_score > 0 and self.signal_type != "ingen"


def analyze(
    article: Article,
    profile: dict,
    model: str = "claude-haiku-4-5-20251001",
    api_key: Optional[str] = None,
) -> AnalysisResult:
    """Analyserar en artikel mot kandidatprofilen med Claude API."""
    if not _HAS_ANTHROPIC:
        raise ImportError("anthropic-paketet saknas — kör: pip install anthropic")

    key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        raise ValueError("ANTHROPIC_API_KEY saknas i miljövariablerna")

    profil_text = _profile_to_text(profile)
    prompt = _PROMPT_TEMPLATE.format(
        profil_text=profil_text,
        title=article.title,
        source=article.source,
        published=article.published_str(),
        body_snippet=article.body_snippet or "(ingen snippet tillgänglig)",
    )

    client = anthropic.Anthropic(api_key=key)

    try:
        max_tok = 512
        message = client.messages.create(
            model=model,
            max_tokens=max_tok,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = message.content[0].text.strip()
    except Exception as e:
        return AnalysisResult(article_id=article.article_id, error=str(e))

    try:
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start == -1 or end == 0:
            raise ValueError("Inget JSON-objekt hittades i svaret")
        data = json.loads(raw[start:end])
    except (json.JSONDecodeError, ValueError) as e:
        return AnalysisResult(
            article_id=article.article_id,
            error=f"JSON-parsningsfel: {e} — råsvar: {raw[:200]}",
        )

    return AnalysisResult(
        article_id=article.article_id,
        signal_type=data.get("signal_type", "ingen"),
        signal_strength=data.get("signal_strength", "svag"),
        match_score=int(data.get("match_score", 0)),
        match_reason=data.get("match_reason", ""),
        potential_roles=data.get("potential_roles", []),
        recommended_action=data.get("recommended_action", "avstå"),
        contact_hint=data.get("contact_hint", ""),
    )
