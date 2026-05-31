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
_UNCLASSIFIED_COLOR = "#CCCCCC"


def build_quadrant(
    sources: list[dict],
    verdicts: list[dict],
    run_id: str,
    done_dir: Path,
) -> Path | None:
    """
    Ritar ett bubbeldiagram: X = relevansscore, Y = trovärdighetspoäng.
    Bubbelstorlek = trovärdighetspoäng normaliserat. Färg = ställningstagande.

    Klassificerade källor (med verdict) ritas i förgrunden med fulla färger.
    Oklassificerade källor ritas som bakgrundsgrå med låg alpha.

    Axlarna skalas dynamiskt efter faktisk dataspridning.

    Sparar [run_id]_quadrant.png i done_dir. Returnerar sökvägen eller None vid fel.

    OBS: X-axeln använder relevance_score som proxy tills ett dedikerat
    semantiskt scoringssteg finns på plats.
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

    classified_xs, classified_ys, classified_sizes, classified_colors = [], [], [], []
    unclassified_xs, unclassified_ys, unclassified_sizes = [], [], []

    for i, src in enumerate(sources, 1):
        rel  = float(src.get("relevance_score") or 0.0)
        cred = float(src.get("credibility_score") or 0)
        size = (cred / 18) * 300 + 40
        verdict = verdict_map.get(i, "?")

        if verdict in _VERDICT_COLORS:
            classified_xs.append(rel)
            classified_ys.append(cred)
            classified_sizes.append(size)
            classified_colors.append(_VERDICT_COLORS[verdict])
        else:
            unclassified_xs.append(rel)
            unclassified_ys.append(cred)
            unclassified_sizes.append(size * 0.6)

    # Dynamiska axelgränser baserade på faktisk dataspridning
    all_xs = classified_xs + unclassified_xs
    all_ys = classified_ys + unclassified_ys
    x_min, x_max = min(all_xs), max(all_xs)
    y_min, y_max = min(all_ys), max(all_ys)
    x_pad = max(0.03, (x_max - x_min) * 0.12)
    y_pad = max(0.3,  (y_max - y_min) * 0.15)

    fig, ax = plt.subplots(figsize=(11, 7))
    fig.patch.set_facecolor("#F7F2E8")
    ax.set_facecolor("#F7F2E8")

    # Oklassificerade i bakgrunden
    if unclassified_xs:
        ax.scatter(
            unclassified_xs, unclassified_ys,
            s=unclassified_sizes,
            c=_UNCLASSIFIED_COLOR,
            alpha=0.25,
            edgecolors="none",
            zorder=1,
        )

    # Klassificerade i förgrunden
    if classified_xs:
        ax.scatter(
            classified_xs, classified_ys,
            s=classified_sizes,
            c=classified_colors,
            alpha=0.85,
            edgecolors="#3D2E0A",
            linewidths=0.6,
            zorder=2,
        )

    ax.set_xlim(x_min - x_pad, x_max + x_pad)
    ax.set_ylim(y_min - y_pad, y_max + y_pad)

    # Kvartilinjer (median av faktisk data)
    x_mid = (x_min + x_max) / 2
    y_mid = (y_min + y_max) / 2
    ax.axvline(x_mid, color="#AAAAAA", linewidth=0.8, linestyle="--")
    ax.axhline(y_mid, color="#AAAAAA", linewidth=0.8, linestyle="--")

    ax.set_xlabel("Relevansscore (cosine similarity mot frågeställning)", fontsize=10, color="#3D2E0A")
    ax.set_ylabel("Trovärdighetspoäng", fontsize=10, color="#3D2E0A")
    ax.set_title(
        f"Artikelöversikt — {run_id}\n"
        f"{len(classified_xs)} klassificerade · {len(unclassified_xs)} oklassificerade",
        fontsize=11, color="#2A3F6F", fontweight="bold",
    )

    legend_items = [
        plt.scatter([], [], s=70, c=_VERDICT_COLORS["stöd"],    label="Stödjer",        edgecolors="#3D2E0A", linewidths=0.6),
        plt.scatter([], [], s=70, c=_VERDICT_COLORS["neutral"], label="Neutral",         edgecolors="#3D2E0A", linewidths=0.6),
        plt.scatter([], [], s=70, c=_VERDICT_COLORS["avvisar"], label="Avvisar",         edgecolors="#3D2E0A", linewidths=0.6),
        plt.scatter([], [], s=40, c=_UNCLASSIFIED_COLOR,        label="Oklassificerad",  edgecolors="none"),
    ]
    ax.legend(handles=legend_items, loc="upper left", fontsize=9, framealpha=0.7)

    ax.tick_params(colors="#3D2E0A")
    for spine in ax.spines.values():
        spine.set_edgecolor("#AAAAAA")

    out_path = done_dir / f"{run_id}_quadrant.png"
    plt.tight_layout()
    plt.savefig(str(out_path), dpi=150, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)

    logger.info("[quadrant_builder] Diagram sparat: %s (%d klassif., %d oklassif.)",
                out_path, len(classified_xs), len(unclassified_xs))
    return out_path
