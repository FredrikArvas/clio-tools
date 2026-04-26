"""
Testscript: hämta och visa närmaste familj för en Geni-profil.

Kör: python geni_family.py https://www.geni.com/people/Johan-Arvas/6000000072669832838
"""
import sys
from geni_client import get_immediate_family, profile_id_from_url


def print_family(result: dict):
    focus = result["focus"]
    print(f"\n{'='*50}")
    print(f"  {focus['name']}")
    if focus["birth_date"]:
        print(f"  Född: {focus['birth_date']}  {focus['birth_location']}")
    if focus["death_date"]:
        print(f"  Död:  {focus['death_date']}")
    print(f"{'='*50}")

    sections = [
        ("Föräldrar",  result["parents"]),
        ("Partner(s)", result["partners"]),
        ("Barn",       result["children"]),
        ("Syskon",     result["siblings"]),
    ]
    for label, people in sections:
        if people:
            print(f"\n{label}:")
            for p in people:
                extra = f"  (f. {p['birth_date']})" if p["birth_date"] else ""
                print(f"  • {p['name']}{extra}")

    print()


def main(argv=None):
    args = argv or sys.argv[1:]
    if not args:
        print("Användning: python geni_family.py <geni-URL-eller-ID>")
        sys.exit(1)

    arg = args[0]
    if arg.startswith("http"):
        profile_id = profile_id_from_url(arg)
    else:
        profile_id = arg

    print(f"Hämtar familj för profil-ID: {profile_id}...")
    result = get_immediate_family(profile_id)
    print_family(result)


if __name__ == "__main__":
    main()
