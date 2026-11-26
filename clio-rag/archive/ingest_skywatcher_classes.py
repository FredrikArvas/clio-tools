"""
Indexerar Skywatcher nio UAP-klasser till vigil_uap_docs.
En chunk per klass — optimal granularitet för RAG-sökning.
Källa: https://skywatcher.ai/research (skrapad 2026-09-07)
"""
import sys, uuid, hashlib, os
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).parent))

import config
config.COLLECTION_NAME = "vigil_uap_docs"

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env", override=True)
load_dotenv(Path(__file__).parent.parent / ".env", override=True)

from openai import OpenAI
from qdrant_client.models import PointStruct, Filter, FieldCondition, MatchValue

COLLECTION = "vigil_uap_docs"
SOURCE     = "Skywatcher UAP Classification Guide"
SOURCE_URL = "https://skywatcher.ai/research"
YEAR       = 2024
MODEL      = config.EMBEDDING_MODEL

CLASSES = [
    {
        "class_id": "I",
        "name": "Tetra",
        "text": (
            "Skywatcher Class I — Tetra. PRELIMINARY CLASSIFICATION.\n\n"
            "Description: Tetrahedron shaped UAP which tumbles on multiple axes while on a stable "
            "flight path. Often appears in groups of 3–20+.\n\n"
            "Visual Profile: Black with intermittent white vapor bursts. Exhibits strobing effect "
            "on electro-optical (EO) sensors several times per second.\n\n"
            "Size: 1.5–2 meters.\n\n"
            "Flight Behavior: Appears to tumble at high speed across multiple axes while maintaining "
            "a stable overall flight path. Typically descends from high altitude to below ~2,000 ft AGL.\n\n"
            "Source: Skywatcher UAP Classification Guide, skywatcher.ai/research"
        ),
    },
    {
        "class_id": "II",
        "name": "Tic Tac",
        "text": (
            "Skywatcher Class II — Tic Tac. PRELIMINARY CLASSIFICATION.\n\n"
            "Description: Cylindrical UAP that hovers. Elongates during stable flight and has an "
            "area effect on electronics and aircraft. Seen in groups of 1 to 3. Observed with the "
            "Manta Ray in proximity.\n\n"
            "Visual Profile: Bright white cylindrical craft that shifts shape during flight. "
            "Observed to elongate horizontally and shift color from white to purple to pink during "
            "transitions. Easily observable on IR.\n\n"
            "Size: 9–12 meters.\n\n"
            "Flight Behavior: Capable of vertical hovering with oscillation, rapid descent from "
            "high altitudes assessed at 60,000+ feet and Mach 1.5+, and abrupt arrest of motion "
            "mid-air. Frequently tumbles while descending and then stabilizes before resuming "
            "flight. Uses terrain masking and performs independent, unsynchronized maneuvers in "
            "proximity to other craft.\n\n"
            "Source: Skywatcher UAP Classification Guide, skywatcher.ai/research"
        ),
    },
    {
        "class_id": "III",
        "name": "Blob",
        "text": (
            "Skywatcher Class III — Blob. PRELIMINARY CLASSIFICATION.\n\n"
            "Description: Orb-shaped UAP that exhibits pulsing internal light, horizontal "
            "oscillation, and erratic point-to-point movement. Capable of extreme speed and rapid "
            "flare-driven expansion. Observed exclusively as singletons.\n\n"
            "Visual Profile: Red cloud-like orb with a pulsing, light-bodied core. The central "
            "element flares in size and brightness, at times expanding into a large red amorphous "
            "form. No visible propulsion observed. Easily detected on IR with strong heat signature.\n\n"
            "Size: 3–5 meters.\n\n"
            "Flight Behavior: Exhibits rapid, near-instantaneous jumps between positions with no "
            "observable transition or acceleration. Movement is generally erratic but often includes "
            "lateral oscillation. During motion or flare events, the form expands significantly, "
            "appearing to pulse or distort in size.\n\n"
            "Source: Skywatcher UAP Classification Guide, skywatcher.ai/research"
        ),
    },
    {
        "class_id": "IV",
        "name": "Beam",
        "text": (
            "Skywatcher Class IV — Beam. PRELIMINARY CLASSIFICATION.\n\n"
            "Description: IR-only orb-shaped UAP that vibrates while in a stable flight path. "
            "Hovers in place for hours at a time. Seen in pairs.\n\n"
            "Visual Profile: Not visible in EO spectrum; only observable on IR. Presents as a "
            "stable, orb-shaped UAP with a strong heat signature and no off-gassing or visible "
            "propulsion.\n\n"
            "Size: Unknown.\n\n"
            "Flight Behavior: Exhibits prolonged hovering, often remaining motionless for over an "
            "hour. Movement, when observed, is slow and deliberate. Vibrates laterally while "
            "maintaining a generally stable flight path.\n\n"
            "Source: Skywatcher UAP Classification Guide, skywatcher.ai/research"
        ),
    },
    {
        "class_id": "V",
        "name": "Manta Ray",
        "text": (
            "Skywatcher Class V — Manta Ray. PRELIMINARY CLASSIFICATION.\n\n"
            "Description: Manta-ray shaped UAP that tumbles on multiple axes. Rarely seen; "
            "observed in proximity to Tic Tacs.\n\n"
            "Visual Profile: Black, manta-ray shaped craft. Emits colored vapor or light from "
            "multiple points, including pink, green, teal, and translucent/white hues. Plumage "
            "appears to radiate from the top surface.\n\n"
            "Size: 2–3 meters.\n\n"
            "Flight Behavior: Observed tumbling and rotating on multiple axes. Capable of hovering "
            "in place and rapidly shifting altitude. Movements include both wind-assisted and "
            "wind-opposed trajectories at varying speeds.\n\n"
            "Source: Skywatcher UAP Classification Guide, skywatcher.ai/research"
        ),
    },
    {
        "class_id": "VI",
        "name": "Bright Star",
        "text": (
            "Skywatcher Class VI — Bright Star. PRELIMINARY CLASSIFICATION.\n\n"
            "Description: Reflective, tetrahedron-shaped UAP that oscillates horizontally, "
            "flashing light. Team has experienced sensor disruption apparently caused by directed "
            "energy.\n\n"
            "Visual Profile: Reflective, tetrahedron-shaped craft that flashes in teal, green, "
            "blue, red, and white light spectrums. Appears to shimmer across its surface in EO "
            "view. Endpoints of the craft are less opaque, possibly due to active plumage or "
            "light-based extension effects.\n\n"
            "Size: 1.5–3 meters.\n\n"
            "Flight Behavior: Exhibits rapid horizontal oscillation, fast enough to produce radar "
            "artifacts resembling a spinning propeller. Movement is erratic and high-frequency, "
            "but contained within a lateral plane.\n\n"
            "Source: Skywatcher UAP Classification Guide, skywatcher.ai/research"
        ),
    },
    {
        "class_id": "VII",
        "name": "Jellyfish",
        "text": (
            "Skywatcher Class VII — Jellyfish. PRELIMINARY CLASSIFICATION.\n\n"
            "Description: Jellyfish-shaped UAP with 'seeking' head motion and trailing tentacles. "
            "Exhibits a localized area effect on electronics, independent of specific targeting or "
            "interaction with sensors.\n\n"
            "Visual Profile: White, jellyfish-shaped craft with a bulbous head and trailing "
            "tentacle-like appendages. The head comprises roughly 1/5 of the overall length, while "
            "the tail extends downward and appears to move independently of wind conditions. "
            "Observable on both EO and IR.\n\n"
            "Size: 2 meters (head), 3–5 meters (tentacles).\n\n"
            "Flight Behavior: Exhibits winding, snake-like movement along deliberate flight paths. "
            "The craft often moves from point to point in a meandering, serpentine motion.\n\n"
            "Source: Skywatcher UAP Classification Guide, skywatcher.ai/research"
        ),
    },
    {
        "class_id": "VIII",
        "name": "Hornet",
        "text": (
            "Skywatcher Class VIII — Hornet. PRELIMINARY CLASSIFICATION.\n\n"
            "Description: Dual-body UAP with hanging tendrils and asynchronous rotation.\n\n"
            "Visual Profile: Multi-part craft with purple, red, blue, and black coloration. "
            "Features a prominent 'tail' that folds into a ball or extends in a stinger-like "
            "formation. The upper segment contains hanging tendrils, within which a secondary "
            "body appears to rest. Reflective flashes observed during flight.\n\n"
            "Size: 2–4 meters.\n\n"
            "Flight Behavior: Exhibits irregular motion and asynchronous rotation between upper "
            "and lower components. Rolls on both pitch and yaw axes while maneuvering.\n\n"
            "Source: Skywatcher UAP Classification Guide, skywatcher.ai/research"
        ),
    },
    {
        "class_id": "IX",
        "name": "Egg",
        "text": (
            "Skywatcher Class IX — Egg. PRELIMINARY CLASSIFICATION.\n\n"
            "Description: Off-white, egg-shaped UAP. Provisional class designation; no "
            "corroborated motion, structure, or spectral data.\n\n"
            "Visual Profile: Off-white metallic, egg-shaped craft. Visual data is limited to a "
            "single, low-quality recording. No observable propulsion, vapor trails, or aerodynamic "
            "control surfaces. EO-visible; IR and other multi-spectral sensor coverage was "
            "unavailable during observation.\n\n"
            "Size: Unknown.\n\n"
            "Flight Behavior: Undocumented. No verified pattern of motion has been established "
            "due to insufficient data. No radar tracking available during sightings to confirm "
            "flight behavior.\n\n"
            "Source: Skywatcher UAP Classification Guide, skywatcher.ai/research"
        ),
    },
]


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="Radera och re-indexera alla klasser")
    args = parser.parse_args()

    oai    = OpenAI()
    qdrant = config.get_qdrant_client()
    now    = datetime.now(timezone.utc).isoformat()

    if args.force:
        # Radera alla punkter med source = SOURCE
        from qdrant_client.models import FilterSelector
        qdrant.delete(
            collection_name=COLLECTION,
            points_selector=FilterSelector(
                filter=Filter(must=[FieldCondition(
                    key="source", match=MatchValue(value=SOURCE)
                )])
            ),
        )
        print(f"[force] Raderade befintliga Skywatcher-klasser ur {COLLECTION}")

    points = []
    for cls in CLASSES:
        text       = cls["text"]
        source_hash = hashlib.sha256(text.encode()).hexdigest()[:16]

        # Hoppa över om chunken redan finns (om ej --force)
        if not args.force:
            existing = qdrant.scroll(
                collection_name=COLLECTION,
                scroll_filter=Filter(must=[FieldCondition(
                    key="source_hash", match=MatchValue(value=source_hash)
                )]),
                limit=1,
                with_payload=False,
                with_vectors=False,
            )
            if existing[0]:
                print(f"[skip] Class {cls['class_id']} — {cls['name']} (oförändrad)")
                continue

        resp   = oai.embeddings.create(input=[text], model=MODEL)
        vector = resp.data[0].embedding

        points.append(PointStruct(
            id=str(uuid.uuid4()),
            vector=vector,
            payload={
                "title":       f"Skywatcher Class {cls['class_id']} — {cls['name']}",
                "source":      SOURCE,
                "source_url":  SOURCE_URL,
                "source_hash": source_hash,
                "year":        YEAR,
                "text":        text,   # query.py läser p.get("summary") or p.get("text")
                "class_id":    cls["class_id"],
                "class_name":  cls["name"],
                "indexed_at":  now,
            },
        ))
        print(f"[ok]   Class {cls['class_id']} — {cls['name']}")

    if points:
        qdrant.upsert(collection_name=COLLECTION, points=points)
        print(f"\n✅ {len(points)} klasser indexerade i {COLLECTION}.")
    else:
        print("\n✅ Inga nya klasser — allt redan indexerat.")


if __name__ == "__main__":
    main()
