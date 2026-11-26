"""Indexerar kallor om utbildningsarrangorernas svar pa naskiks-invandningen,
inklusive den indiska midbrain activation-linjen.
"""
import sys, uuid, logging
sys.path.insert(0, ".")
logging.basicConfig(level=logging.INFO)

import qdrant_indexer as qi

RUN_ID = "clio-research-016-svar_20260726"

SOURCES = [
    {
        "title": "Midbrain activation - indisk traningsrorelse for blindfoldad lasning",
        "authors": ["Diverse"],
        "year": 2015,
        "doi": None,
        "fulltext_url": "https://en.wikipedia.org/wiki/Midbrain_activation",
        "database": "manual-svar",
        "region": "Indien",
        "credibility_score": 3,
        "abstract": (
            "VERIFIERAD som fenomen. Kommersiell traningsrorelse i Indien och Sydostasien "
            "som pastar sig aktivera mellanhjarnan sa att barn kan lasa blindfoldat. "
            "Beskrivs i granskningar som byggande pa att deltagarna tranas att se genom "
            "bindeln. AVGORANDE FOR KONVERGENSBEDOMNING: rorelsens ursprung ar inte "
            "sjalvstandigt utrett - den kan vara en fjarde oberoende linje eller ett "
            "derivat av den kinesiska eller indonesiska. Behandlas darfor som overifierad "
            "i analysens konvergensrakning."
        ),
    },
    {
        "title": ("Narendra Nayak / FIRA: utmaning om fem lakh mot midbrain "
                  "activation-anspraken"),
        "authors": ["Narendra Nayak"],
        "year": 2015,
        "doi": None,
        "fulltext_url": "https://en.wikipedia.org/wiki/Narendra_Nayak",
        "database": "manual-svar",
        "region": "Indien",
        "credibility_score": 6,
        "abstract": (
            "VERIFIERAD. Ordforanden for Federation of Indian Rationalist Associations "
            "utlyste 500 000 rupier for demonstration av blindfoldad lasning. Vinoj "
            "Surendran antog utmaningen for ett offentligt mote i Kozhikode men drog sig ur "
            "med motiveringen att barnen 'inte kan fungera i en fientlig miljo'. Foraldrar "
            "som tog med 'midbrain-aktiverade' barn misslyckades. SVARSMONSTER: "
            "villkorsargumentet - anspraket upprathalls men testet undviks genom "
            "hanvisning till miljoen. Parallell till Bronnikovs vagran mot Derren Brown."
        ),
    },
    {
        "title": ("Arrangorssvar pa naskiks-invandningen: anspraksomdefiniering och "
                  "protokollkrav"),
        "authors": ["Bronnikov-organisationen", "Vinoj Surendran"],
        "year": 2015,
        "doi": None,
        "fulltext_url": "https://www.newsclick.in/Blindfolded-Seeing-Story-Scam",
        "database": "manual-svar",
        "region": "Ryssland/Indien",
        "credibility_score": 5,
        "abstract": (
            "VERIFIERAD via sekundarkallor. Dokumenterar tva atervandande svarsmonster. "
            "(1) ANSPRAKSOMDEFINIERING: pa James Randis miljondollarsutmaning svarade "
            "Bronnikov-gruppen att blindfoldad lasning 'is not the aim of the Method, but "
            "only one of the consequences' - den testbara delen omdefinieras som "
            "bieffekt. (2) PROTOKOLLKRAV SOM ATERSKAPAR KONFUNDEN: Surendran havdade att "
            "barnen tror sig se med ogonen och att objekt darfor maste placeras framfor dem "
            "med ogonen blockerade - alltsa exakt den geometri som tillater naskik. "
            "Rapporterat forekommer aven bindlar med extra tygbit vid nasryggen, vilket "
            "underlattar kik utan huvudlutning."
        ),
    },
]


def main():
    protocol = {
        "protocol_id": "clio-research-016-svar",
        "created": "2026-07-26",
        "question": {
            "natural_language": (
                "Hur bemoter EOV-utbildningsarrangorer naskiks-invandningen? "
                "Svarsmonster, testvagran och protokollkrav."
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
