"""quadrant_builder.py — Fyrfältsdiagram över artiklar per trovärdighet och relevans."""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Färger per ställningstagande (hex-värden ur AIAB-paletten)
_VERDICT_COLORS = {
    "stöd":     "#27622A",
    "neutral":  "#C8A84B",
    "avvisar":  "#B83232",
}
_DEFAULT_COLOR = "#888888"


def build_quadrant(
    sources: list[dict],
    verdicts: list[dict],
    run_id: str,
    done_dir: Path,
) -> Path | None:
    """
    Ritar ett bubbeldiagram: X = relevansscore (proxy), Y = trovärdighetspoäng.
    Bubbelstorlek = trovärdighetspoäng normaliserat. Färg = ställningstagande.

    Sparar [run_id]_quadrant.png i done_dir. Returnerar sökvägen eller None vid fel.

    OBS: X-axeln använder relevance_score som proxy för "Fixed→Growth mindset"-dimensionen
    tills ett dedikerat semantiskt scoringssteg finns på plats.
    """
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        logger.warning("[quadrant_builder] matplotlib ej installerat — diagram hoppas över")
        return None

    if not sources:
        logger.warning("[quadrant_builder] Inga källor — diagram hoppas över")
        return None

    verdict_map = {v["index"]: v.get("verdict", "?") for v in verdicts}

    xs, ys, sizes, colors = [], [], [], []
    for i, src in enumerate(sources, 1):
        rel = src.get("relevance_score") or 0.0
        cred = src.get("credibility_score") or 0
        verdict = verdict_map.get(i, "?")

        xs.append(float(rel))
        ys.append(float(cred))
        sizes.append((float(cred) / 18) * 400 + 50)
        colors.append(_VERDICT_COLORS.get(verdict, _DEFAULT_COLOR))

    fig, ax = plt.subplots(figsize=(10, 7))
    fig.patch.set_facecolor("#F7F2E8")
    ax.set_facecolor("#F7F2E8")

    ax.scatter(xs, ys, s=sizes, c=colors, alpha=0.75, edgecolors="#3D2E0A", linewidths=0.5)

    ax.set_xlabel("Relevansscore (proxy: cosine similarity)", fontsize=10, color="#3D2E0A")
    ax.set_ylabel("Trovärdighetspoäng (0–18)", fontsize=10, color="#3D2E0A")
    ax.set_title(f"Artikelöversikt — {run_id}", fontsize=12, color="#2A3F6F", fontweight="bold")
    ax.set_xlim(-0.05, 1.05)
    ax.set_ylim(-1, 19)

    ax.axvline(0.5, color="#AAAAAA", linewidth=0.8, linestyle="--")
    ax.axhline(9, color="#AAAAAA", linewidth=0.8, linestyle="--")

    legend_items = [
        plt.scatter([], [], s=80, c=_VERDICT_COLORS["stöd"],    label="Stödjer", edgecolors="#3D2E0A", linewidths=0.5),
        plt.scatter([], [], s=80, c=_VERDICT_COLORS["neutral"], label="Neutral", edgecolors="#3D2E0A", linewidths=0.5),
        plt.scatter([], [], s=80, c=_VERDICT_COLORS["avvisar"], label="Avvisar", edgecolors="#3D2E0A", linewidths=0.5),
        plt.scatter([], [], s=80, c=_DEFAULT_COLOR,             label="Okänd",   edgecolors="#3D2E0A", linewidths=0.5),
    ]
    ax.legend(handles=legend_items, loc="upper left", fontsize=9)

    ax.tick_params(colors="#3D2E0A")
    for spine in ax.spines.values():
        spine.set_edgecolor("#AAAAAA")

    out_path = done_dir / f"{run_id}_quadrant.png"
    plt.tight_layout()
    plt.savefig(str(out_path), dpi=150, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)

    logger.info("[quadrant_builder] Diagram sparat: %s", out_path)
    return out_path
