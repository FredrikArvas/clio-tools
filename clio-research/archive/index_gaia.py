"""Indexerar EOV-kallor fran gaia.com-sammanstallningen (clio-research-016-sources.md).

Verifieringsstatus anges explicit i varje abstract. Trovardighetspoang satta enligt
clio-research 6-dimensionsmodell (0-18), dar kommersiella traningsaktorer utan
peer-review far lagt varde oavsett hur utbredda de ar.
"""
import sys, uuid, logging
sys.path.insert(0, ".")
logging.basicConfig(level=logging.INFO)

import qdrant_indexer as qi

RUN_ID = "clio-research-016-gaia_20260726"

SOURCES = [
    {
        "title": "On the So-Called Alternative Vision or Direct Vision Phenomenon",
        "authors": ["N. P. Bekhtereva", "L. Y. Lozovskaya", "S. G. Dan'ko"],
        "year": 2002,
        "doi": "10.1023/A:1013948132328",
        "fulltext_url": "https://link.springer.com/article/10.1023/A:1013948132328",
        "database": "manual-gaia",
        "region": "Ryssland",
        "credibility_score": 9,
        "abstract": (
            "VERIFIERAD. Human Physiology 28(1). Natalya Bekhtereva, RAS Institute of the "
            "Human Brain, St Petersburg. Sju gymnasieelever tranade enligt Bronnikov-metoden "
            "undersoktes med EEG och evoked potentials under 'seende med slutna ogon'. "
            "Forfattarna rapporterar att samtliga uppvisade alternativ syn och att EEG visade "
            "omorganisation av hjarnaktivitet. AVGORANDE INVANDNING: betingelsen ar slutna "
            "ogon respektive ogonbindel, inte avskuren siktlinje - alltsa exakt den "
            "konfiguration dar naskik ar trivialt. Studien mater fysiologi under pastadd EOV "
            "men kontrollerar inte om EOV ager rum. Motsager likval pastaendet att inga "
            "storre neurovetenskapliga institutioner undersokt EOV."
        ),
    },
    {
        "title": ("CICAP-test av R.G. vid Universita di Pavia: pastadd rontgensyn "
                  "genom forseglade lador"),
        "authors": ["Massimo Polidoro", "Luigi Garlaschelli", "Adalberto Piazzoli"],
        "year": 2010,
        "doi": None,
        "fulltext_url": "https://en.wikipedia.org/wiki/Dermo-optical_perception",
        "database": "manual-gaia",
        "region": "Italien",
        "credibility_score": 8,
        "abstract": (
            "DELVIS VERIFIERAD. Italiensk kvinna (R.G.) som pastod sig kunna se in i "
            "forseglade lador testades vid Universita di Pavia av CICAP-forskarna Polidoro, "
            "Garlaschelli och Piazzoli. Tolv objekt placerades i traladar. Testets existens "
            "och upplagg ar bekraftat; det specifika utfallet 1 av 12 kunde INTE verifieras "
            "och ska behandlas som obekraftat. Metodologiskt intressant: forseglad lada "
            "avskar siktlinjen och testar darmed geometrin snarare an stimulustypen."
        ),
    },
    {
        "title": "Derren Brown Investigates: The Man with X-Ray Eyes",
        "authors": ["Derren Brown"],
        "year": 2010,
        "doi": None,
        "fulltext_url": "https://www.martialdevelopment.com/derren-brown-investigates-bronnikov-method/",
        "database": "manual-gaia",
        "region": "Storbritannien",
        "credibility_score": 4,
        "abstract": (
            "VERIFIERAD. Channel 4-dokumentar. Brown besoker Bronnikov-centret med den blinda "
            "deltagaren Judy Dunk, som inte uppvisar nagon forbattring. Vyacheslav Bronnikov "
            "erbjuds testet att ange innehallet i en forseglad lada och AVBOJER med motivering "
            "att Brown ar olamplig testperson. Epistemiskt ar vagran att genomga ett "
            "geometriblockerande test ett annat slags datum an ett dokumenterat naskik - "
            "svagare som falsifiering, men det avser exakt det test som skulle diskriminera. "
            "Kategori I enligt rapport 016:s indelning (informellt avfarjande, ej formell "
            "falsifiering)."
        ),
    },
    {
        "title": "Vibravision / Merpati Putih - indonesisk traningstradition for 'mindsight'",
        "authors": ["Mike Zeleznick"],
        "year": 2020,
        "doi": None,
        "fulltext_url": "https://vibravision.com/",
        "database": "manual-gaia",
        "region": "Indonesien/USA",
        "credibility_score": 2,
        "abstract": (
            "EJ VERIFIERAD som evidens; verifierad som fenomen. Kommersiellt traningssystem "
            "harlett ur den javanesiska kampkonsten Merpati Putih. Pastar att utovare "
            "uppfattar farg och form blindfoldat via 'vibrationell energi'. Inga peer-reviewade "
            "data. Refererad neurologisk registrering av Jeffrey Fannin saknar publicerad "
            "studie. VARDE FOR ANALYSEN: utgor den enda EOV-traditionen i materialet med "
            "ursprung oberoende av den ryska linjen, och ar darmed avgorande for bedomningen "
            "av geografisk konvergens."
        ),
    },
    {
        "title": "InfoVision - Center of Direct Information Perception",
        "authors": ["Mark Komissarov", "Mihaela Istrati"],
        "year": 1999,
        "doi": None,
        "fulltext_url": "https://mkomissarov.com/",
        "database": "manual-gaia",
        "region": "Ryssland/internationellt",
        "credibility_score": 2,
        "abstract": (
            "EJ VERIFIERAD. Traningssystem utvecklat 1999, uppges ha tranat ca 10 000 personer "
            "i ett tjugotal lander. Postulerar ett 'Center of Direct Information Perception' i "
            "hjarnan. Anspraken eskalerar bortom EOV till att se genom vaggar, pa avstand och "
            "lasa innehall pa hardiskar - vilket ar analytiskt betydelsefullt: anspraksglidning "
            "bort fran det empiriskt avgrandsade DOP-paradigmet gor pastaendena samtidigt mer "
            "spektakulara och mindre testbara. Ursprungskalla for DIW/sehen-ohne-augen."
        ),
    },
    {
        "title": "Superhuman: The Invisible Made Visible",
        "authors": ["Caroline Cory"],
        "year": 2020,
        "doi": None,
        "fulltext_url": "https://www.imdb.com/title/tt8756802/",
        "database": "manual-gaia",
        "region": "USA/Italien",
        "credibility_score": 2,
        "abstract": (
            "EJ VERIFIERAD. Dokumentarfilm distribuerad via Gaia. Visar blindfoldade barn "
            "testade av neurovetare som uppges vara knutna till Universita di Bari, med "
            "maskprovning for ljusleckage. Inga av experimenten ar publicerade peer-reviewat "
            "och institutionsanknytningen ar inte oberoende bekraftad. Filmen ar sannolikt "
            "den storsta enskilda spridningskanalen for moderna EOV-anspraken i vasterlandet, "
            "vilket gor den relevant som diskursobjekt snarare an som evidens."
        ),
    },
]


def main():
    protocol = {
        "protocol_id": "clio-research-016-gaia",
        "created": "2026-07-26",
        "question": {
            "natural_language": (
                "Praktiker- och dokumentarmaterial om extra-okular vision insamlat via "
                "gaia.com-ekosystemet: traningstraditioner, avslojanden och den enda "
                "peer-reviewade institutionella studien (Bekhtereva 2002)."
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
