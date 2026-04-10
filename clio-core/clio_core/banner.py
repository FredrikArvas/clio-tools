"""
clio_core.banner — ASCII-banner för Clio Tools-program
"""

_INNER = 62

_STATIC_TOP = [
    "      )))  *  (((          ___  _     _                       ",
    "          /|\\             / __\\| |   (_) ___                  ",
    "         |   |           / /   | |   | |/ _ \\                 ",
    "         |=|=|          / /___ | |___| | (_) |                ",
    "         |   |          \\____/ |_____|_|\\___/                 ",
    "        /|   |\\                                               ",
]
_SUBTITLE_ROW = "       /_|___|_\\          {:<30}"


def print_banner(program: str, version: str = "", subtitle: str = "Arvas Familjebibliotek") -> None:
    """Skriver ut ASCII-bannern med programnamnet på stdout."""
    program_str = f"{program} v{version}" if version else program

    prefix = "     ~~ ~~~~~~~ ~~        "
    middle = f"\u2500\u2500 {program_str} \u2500\u2500"
    inner_dyn = (prefix + middle).ljust(_INNER)[:_INNER]

    pad = "  "
    top    = f"{pad}\u2554{'=' * _INNER}\u2557".replace("=", "\u2550")
    empty  = f"{pad}\u2551{' ' * _INNER}\u2551"
    bottom = f"{pad}\u255a{'=' * _INNER}\u255d".replace("=", "\u2550")

    subtitle_inner = _SUBTITLE_ROW.format(subtitle)[:_INNER].ljust(_INNER)

    print(top)
    print(empty)
    for row in _STATIC_TOP:
        print(f"{pad}\u2551{row}\u2551")
    print(f"{pad}\u2551{subtitle_inner}\u2551")
    print(f"{pad}\u2551{inner_dyn}\u2551")
    print(empty)
    print(bottom)
