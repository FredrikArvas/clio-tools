"""
run_tests.py
Test runner for clio-tools.

Usage:
    python tests/run_tests.py              # unit tests only (default, fast)
    python tests/run_tests.py --system     # system tests only (requires external tools)
    python tests/run_tests.py --all        # unit + system
    python tests/run_tests.py -v           # verbose output
    python tests/run_tests.py utils        # single unit suite
    python tests/run_tests.py --system fetch_live  # single system suite

Test layers:
    unit/    – fast, mocked, no external deps  (<5s)
    system/  – requires Tesseract, internet etc.
    uat/     – manual checklist: tests/uat/CHECKLIST.md
"""

import sys
import logging
import unittest
from pathlib import Path

# Suppress all logging during tests
logging.disable(logging.CRITICAL)

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "tests" / "unit"))
sys.path.insert(0, str(ROOT / "tests" / "system"))

UNIT_SUITES = {
    "utils":      "test_utils",
    "docs":       "test_docs",
    "transcribe": "test_transcribe",
    "narrate":    "test_narrate",
    "vision":     "test_vision",
    "fetch":      "test_fetch",
    "clio":       "test_clio",
    "research":   "test_research",
    "obit":       "test_obit",
    "cockpit":    "test_cockpit",       # clio_cockpit + odoo_reply (_md_to_html)
}

SYSTEM_SUITES = {
    "docs_ocr":         "test_docs_ocr",
    "narrate_edge":     "test_narrate_edge",
    "fetch_live":       "test_fetch_live",
    "cockpit_service":  "test_cockpit_service",  # smoke-tester mot clio-service :7200
}


def run(suite_names: list, verbosity: int = 1) -> bool:
    loader = unittest.TestLoader()
    suite  = unittest.TestSuite()

    for name in suite_names:
        try:
            module = __import__(name)
            suite.addTests(loader.loadTestsFromModule(module))
        except Exception as e:
            print(f"  Could not load {name}: {e}")

    runner = unittest.TextTestRunner(verbosity=verbosity, stream=sys.stdout)
    result = runner.run(suite)
    return result.wasSuccessful()


def check_fixtures():
    fixtures = ROOT / "tests" / "fixtures"
    fixture_files = ["sample.pdf", "sample.mp3", "sample.jpg",
                     "sample.docx", "sample.txt", "sample.md"]
    missing = [f for f in fixture_files if not (fixtures / f).exists()]
    if missing:
        print(f"\nMissing fixtures: {missing}")
        print(f"Run: python tests/fixtures/generate_fixtures.py\n")


def main():
    args = sys.argv[1:]
    verbose  = "-v" in args
    run_all  = "--all" in args
    run_sys  = "--system" in args
    args     = [a for a in args if a not in ("-v", "--all", "--system", "--unit")]

    verbosity = 2 if verbose else 1

    if run_all:
        layer = "unit+system"
        suites = list(UNIT_SUITES.values()) + list(SYSTEM_SUITES.values())
    elif run_sys:
        layer = "system"
        if args:
            unknown = [a for a in args if a not in SYSTEM_SUITES]
            if unknown:
                print(f"Unknown system suite(s): {unknown}")
                print(f"Available: {list(SYSTEM_SUITES.keys())}")
                sys.exit(1)
            suites = [SYSTEM_SUITES[a] for a in args]
        else:
            suites = list(SYSTEM_SUITES.values())
    else:
        layer = "unit"
        if args:
            unknown = [a for a in args if a not in UNIT_SUITES]
            if unknown:
                print(f"Unknown unit suite(s): {unknown}")
                print(f"Available: {list(UNIT_SUITES.keys())}")
                sys.exit(1)
            suites = [UNIT_SUITES[a] for a in args]
        else:
            suites = list(UNIT_SUITES.values())

    print(f"\nclio-tools test runner  [{layer}]")
    print(f"Running: {', '.join(suites)}")
    print("=" * 60)

    check_fixtures()

    ok = run(suites, verbosity=verbosity)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
