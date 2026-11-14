"""Indexerar EOV-källor som saknas i clio-research-016 till Qdrant (vigil_research).

Källorna är funna manuellt vid djupanalys av rapport 016 och representerar
verifierade vita fläckar. Markeras med phase_found=99 och added_by='clio-analys-016'
så att de går att skilja från pipeline-genererade källor.
"""
import sys, uuid, logging
sys.path.insert(0, ".")
logging.basicConfig(level=logging.INFO)

import qdrant_indexer as qi

RUN_ID = "clio-research-016-analys_20260726"

SOURCES = [
    {
        "title": "Dermo-optical Perception: A Peek Down the Nose",
        "authors": ["Martin Gardner"],
        "year": 1966,
        "doi": "10.1126/science.151.3711.654",
        "fulltext_url": "https://www.science.org/doi/10.1126/science.151.3711.654",
        "database": "manual",
        "region": "USA",
        "credibility_score": 9,
        "abstract": (
            "Gardners kanoniska metodologiska granskning av dermo-optisk perception i Science. "
            "Introducerar 'nose peek' som primar forklaringsmodell for positiva DOP-resultat och "
            "dokumenterar att Rosa Kuleshova ertappades med att titta under ogonbindeln. "
            "Artikeln ar den som de fyra Science-kommentarerna 1966 (Makous, Youtz & Weintraub, "
            "Buckhout, Weintraub) svarar pa. Saknas helt i clio-research-016."
        ),
    },
    {
        "title": ("Seeing Without Eyes: Climbing up the impossibility ladder with "
                  "controlled experiments in talented individuals"),
        "authors": ["Alex Gomez-Marin"],
        "year": 2023,
        "doi": None,
        "fulltext_url": "https://noetic.org/wp-content/uploads/2023/06/Seeing-Without-Eyes-Full-Proposal.pdf",
        "database": "manual",
        "region": "Spanien",
        "credibility_score": 8,
        "abstract": (
            "Forskningsproposal, delad vinnare av IONS Linda G. O'Bryant Noetic Research Prize 2023. "
            "Instituto de Neurociencias, Alicante. Foreslar kontrollerade EOV-experiment pa kliniskt "
            "blinda deltagare for att eliminera nose-peek-invandningen. Protokoll: flerlagers "
            "ogonbindlar, ljustat hjalm med kameror for ogonrorelser och luxmatning, stimulusbox "
            "(Romains Bouclier), ganzfeld-inspirerad fyrkortsmatchning med blindade domare, "
            "forhandsbestamt antal trials mot optional stopping. Preliminara observationer pa "
            "blind deltagare 'Vicente'. Saknas helt i clio-research-016."
        ),
    },
    {
        "title": "Eyeless Sight: A Study of Extra-Retinal Vision and the Paroptic Sense",
        "authors": ["Jules Romains"],
        "year": 1924,
        "doi": None,
        "fulltext_url": "https://archive.org/details/eyelesssightstud00roma",
        "database": "manual",
        "region": "Frankrike",
        "credibility_score": 3,
        "abstract": (
            "Grundtexten for extra-retinal vision. Romains beskriver 'Bouclier' - en lada med "
            "lock dar deltagaren for in handerna, konstruerad for att avskara varje rat linje "
            "mellan objekt och oga. Fallbeskrivningar med krigsblindade soldater. Metodologiskt "
            "svag men historiskt konstitutiv for faltet; refereras som primarkalla av Gomez-Marin."
        ),
    },
    {
        "title": "Extraocular vision",
        "authors": ["Jacobo Grinberg-Zylberbaum"],
        "year": 1983,
        "doi": None,
        "fulltext_url": None,
        "database": "manual",
        "region": "Mexiko",
        "credibility_score": 4,
        "abstract": (
            "Mexikansk neurofysiologisk studie som rapporterar att tranade barn kan uppfatta "
            "objekt utan ogon, inklusive i totalt morkt kallarutrymme dar fyra kontrollvittnen "
            "inte kunde uppfatta nagot. Rapporterar att EOV foljer samma lagar som retinal vision "
            "(perspektiv, kontrast, skarpa, overlappning, rorelse). Star i direkt motsattning till "
            "Romains pastaende att perception saknas i absolut morker - en testbar konflikt. "
            "Saknas helt i clio-research-016. Publikationsdata ej fullstandigt verifierade."
        ),
    },
    {
        "title": "Opsin expression in human epidermal skin",
        "authors": ["Kirk W. Haltaufderhyde", "Rana N. Ozdeslik", "Nadine L. Wicks",
                    "Julia A. Najera", "Elena Oancea"],
        "year": 2015,
        "doi": "10.1111/php.12354",
        "fulltext_url": "https://www.ncbi.nlm.nih.gov/pmc/articles/PMC4303996/",
        "database": "manual",
        "region": "USA",
        "credibility_score": 12,
        "abstract": (
            "Pavisar att fyra opsiner - OPN1-SW, OPN2 (rhodopsin), OPN3 (encefalopsin/panopsin) "
            "och OPN5 - uttrycks i mansklig epidermis, i bade melanocyter och keratinocyter. "
            "OPN3 uttrycks i hogst niva. Etablerad, peer-reviewad biologi som ger den mekanistiska "
            "forutsattningen for hudbaserad fotoreception, men visar ingen bildbildande formaga. "
            "Saknas i clio-research-016 trots att rapportens avsnitt I.3 efterlyser just detta."
        ),
    },
    {
        "title": ("Human nonvisual opsin 3 regulates pigmentation of epidermal melanocytes "
                  "through functional interaction with melanocortin 1 receptor"),
        "authors": ["Rana N. Ozdeslik", "Lauren E. Olinski", "Melissa M. Trieu",
                    "Daniel D. Oprian", "Elena Oancea"],
        "year": 2019,
        "doi": "10.1073/pnas.1902825116",
        "fulltext_url": "https://www.pnas.org/doi/10.1073/pnas.1902825116",
        "database": "manual",
        "region": "USA",
        "credibility_score": 13,
        "abstract": (
            "Visar att OPN3 i mansklig hud fungerar som funktionell G-proteinkopplad receptor som "
            "reglerar pigmentering via MC1R. Bekraftar att hudopsiner ar biologiskt aktiva, men "
            "signalvagen ar pigmentreglerande, inte perceptuell - vilket gor den till ett "
            "avgorande gransvarde for DOP-mekanismhypotesen. Saknas i clio-research-016."
        ),
    },
    {
        "title": "Dermo-Optical Perception (Psi Encyclopedia)",
        "authors": ["Society for Psychical Research"],
        "year": 2020,
        "doi": None,
        "fulltext_url": "https://psi-encyclopedia.spr.ac.uk/articles/dermo-optical-perception/",
        "database": "manual",
        "region": "Storbritannien",
        "credibility_score": 5,
        "abstract": (
            "SPR:s uppslagsartikel om dermo-optisk perception. Representerar den parapsykologiska "
            "tidskriftstraditionen (SPR/JSE/Journal of Parapsychology) som clio-research-016 "
            "identifierar som helt franvarande fran kallmaterialet. Ingangspunkt till den "
            "litteratur pipelinen inte indexerar."
        ),
    },
]


def main():
    protocol = {
        "protocol_id": "clio-research-016-analys",
        "created": "2026-07-26",
        "question": {
            "natural_language": (
                "Vita flackar i clio-research-016 (EOV): kallor identifierade vid manuell "
                "djupanalys som saknas i pipelinens 60 relevansfiltrerade kallor."
            )
        },
    }
    for s in SOURCES:
        s.setdefault("source_id", str(uuid.uuid4()))
        s["phase_found"] = 99
        s["added_by"] = "clio-analys-016"

    qi.index_report(
        protocol=protocol,
        sources=SOURCES,
        report_path=None,
        run_id=RUN_ID,
    )
    print("Indexerade %d kallor under run_id=%s" % (len(SOURCES), RUN_ID))


if __name__ == "__main__":
    main()
