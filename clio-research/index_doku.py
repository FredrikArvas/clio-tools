"""Indexerar dokumentar- och medlekallor (se-utan-ogon-kallor-dokumentar.md)
samt den kinesiska EHBF-linjen som identifierades vid granskningen.
"""
import sys, uuid, logging
sys.path.insert(0, ".")
logging.basicConfig(level=logging.INFO)

import qdrant_indexer as qi

RUN_ID = "clio-research-016-doku_20260726"

SOURCES = [
    {
        "title": ("The Craziness for Extra-Sensory Perception: Qigong Fever and the "
                  "Science-Pseudoscience Debate in China"),
        "authors": ["Zygon"],
        "year": 2015,
        "doi": "10.1111/zygo.12178",
        "fulltext_url": "https://onlinelibrary.wiley.com/doi/abs/10.1111/zygo.12178",
        "database": "manual-doku",
        "region": "Kina",
        "credibility_score": 10,
        "abstract": (
            "VERIFIERAD. Peer-reviewad genomgang av den kinesiska debatten 1979-1999 om "
            "'exceptional functions of the human body' (EFHB/EHBF). Utlosande fall: "
            "12-ariga Tang Yu i Sichuan, mars 1979, som pastods kunna 'lasa med oronen'. "
            "AVGORANDE: fallet avfardades inom tio dagar av en statlig undersokningsgrupp "
            "som replikerade prestationen med taskspelartrick. Trots detta foljde tjugo ar "
            "av 'qigong fever' med miljontals deltagare, till statens tillslag 1999. "
            "Kallan etablerar Kina som en fran ryska och indonesiska linjer OBEROENDE "
            "EOV-tradition - och som ett fall dar bade anspraket och dess falsifiering "
            "uppstod inom samma kultursfar. Saknas helt i clio-research-016."
        ),
    },
    {
        "title": "Qigong Fever: Body, Science, and Utopia in China",
        "authors": ["David A. Palmer"],
        "year": 2007,
        "doi": None,
        "fulltext_url": "https://en.wikipedia.org/wiki/Qigong_Fever:_Body,_Science,_and_Utopia_in_China",
        "database": "manual-doku",
        "region": "Kina/Frankrike",
        "credibility_score": 11,
        "abstract": (
            "VERIFIERAD som verk. Akademisk monografi (Columbia University Press) om "
            "qigong-rorelsens sociala och vetenskapliga historia i Kina. Primarreferens for "
            "den kinesiska EOV-linjens omfattning och institutionella forankring. Relevant "
            "for bedomning av geografisk konvergens: visar att den kinesiska traditionen "
            "hade statligt stod och egen forskningsapparat, alltsa inte ar ett derivat av "
            "vasterlandska eller ryska anspraken."
        ),
    },
    {
        "title": "Matrixwissen-Dokumentation: Sehen ohne Augen",
        "authors": ["Oliver Weis"],
        "year": 2018,
        "doi": None,
        "fulltext_url": "https://matrix-wissen.de/SehenOhneAugen.html",
        "database": "manual-doku",
        "region": "Tyskland",
        "credibility_score": 4,
        "abstract": (
            "DELVIS VERIFIERAD. Filmning och testning av fem barn nara Pforzheim, "
            "2018-10-27. Metodologiskt det mest seriosa i dokumentarmaterialet: Weis "
            "kontrollerade maskerna sjalv, bestallde en identisk mask och lat barnen bara "
            "hans egen, och del 2 uppges ha genomforts med ogonen tejpade under masken. "
            "Redovisar aven fall dar formagan uteblev - en godtrosmarkor som ar sallsynt i "
            "faltet. BEGRANSNINGAR: ej peer-reviewat; kursledaren var Evelyn Ohly, vilket "
            "gor deltagarna DIW-tranade och darmed harledda ur den RYSKA linjen, inte "
            "oberoende; och Weis var Tom Campbells tyske samarbetspartner, alltsa ingen "
            "ointresserad part. Weis ar avliden - materialet ar en sluten korpus."
        ),
    },
    {
        "title": "The Telepathy Tapes S2E11: Mindsight - Seeing Without Eyes",
        "authors": ["Ky Dickens"],
        "year": 2025,
        "doi": None,
        "fulltext_url": "https://thetelepathytapes.com/podcast/the-telepathy-tapes-s2-e11",
        "database": "manual-doku",
        "region": "USA/England/Indien/Kina",
        "credibility_score": 2,
        "abstract": (
            "EJ VERIFIERAD. Poddavsnitt (dec 2025, ca 75 min) om blindfold vision med "
            "material fran England, Indien och Kina, inklusive en juridiskt blind man som "
            "genomgatt traning. Ingen evidens, men relevant som diskursobjekt och som "
            "indikation pa att de indiska och kinesiska linjerna ar levande. Innehallets "
            "sakuppgifter ar ej oberoende kontrollerade."
        ),
    },
    {
        "title": "Blindsight (dokumentarfilm, 2006) - ej EOV, terminologisk varning",
        "authors": ["Lucy Walker"],
        "year": 2006,
        "doi": None,
        "fulltext_url": "https://en.wikipedia.org/wiki/Blindsight_(film)",
        "database": "manual-doku",
        "region": "Storbritannien/Tibet",
        "credibility_score": 1,
        "abstract": (
            "VERIFIERAD men IRRELEVANT for EOV-anspraket. Dokumentar om sex blinda "
            "tibetanska ungdomar som bestiger i Himalaya tillsammans med Erik Weihenmayer. "
            "Handlar om blindas formaga och navigering, inte om extra-okular perception. "
            "Indexeras enbart som terminologisk varning: titeln kolliderar bade med det "
            "neurologiska fenomenet blindsight (residual visuell diskriminering vid "
            "V1-skada) och med EOV-litteraturens sokord. Risk for falska traffar i "
            "framtida korningar."
        ),
    },
]


def main():
    protocol = {
        "protocol_id": "clio-research-016-doku",
        "created": "2026-07-26",
        "question": {
            "natural_language": (
                "Dokumentar- och mediematerial om extra-okular vision, samt den kinesiska "
                "EHBF-linjen (qigong fever 1979-1999) som oberoende tradition."
            )
        },
    }
    for s in SOURCES:
        s.setdefault("source_id", str(uuid.uuid4()))

    qi.index_report(protocol=protocol, sources=SOURCES,
                    report_path=None, run_id=RUN_ID)
    print("Indexerade %d kallor under run_id=%s" % (len(SOURCES), RUN_ID))


if __name__ == "__main__":
    main()
