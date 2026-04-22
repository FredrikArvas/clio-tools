"""
test_cockpit_service.py
System-/smoke-tester mot live clio-service (port 7200).

Kräver att clio-service körs. Körs vanligen på elitedeskgpu.

Kör:
    python tests/run_tests.py --system cockpit_service
    # eller direkt:
    python tests/system/test_cockpit_service.py
"""

import os
import sys
import json
import unittest
import urllib.request
import urllib.error
from pathlib import Path

BASE = os.environ.get("CLIO_SERVICE_URL", "http://localhost:7200")


def _get(path: str, timeout: int = 10) -> dict:
    req = urllib.request.Request(f"{BASE}{path}", method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def _post(path: str, data: dict, timeout: int = 20) -> dict:
    body = json.dumps(data).encode()
    req  = urllib.request.Request(
        f"{BASE}{path}", data=body, method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


class TestServiceHealth(unittest.TestCase):

    def test_health_returns_ok(self):
        d = _get("/health")
        self.assertTrue(d.get("ok"), f"Svar: {d}")
        self.assertEqual(d.get("service"), "clio-service")

    def test_health_server_structure(self):
        d = _get("/health/server")
        self.assertTrue(d.get("ok"), f"Svar: {d}")
        for key in ["cpu_percent", "ram_used_gb", "ram_total_gb",
                    "disk_percent", "uptime_days", "updates_count"]:
            self.assertIn(key, d, f"Saknar nyckel '{key}'")

    def test_health_server_values_sane(self):
        d = _get("/health/server")
        self.assertGreaterEqual(d["cpu_percent"], 0)
        self.assertLessEqual(d["cpu_percent"], 100)
        self.assertGreater(d["ram_total_gb"], 0)
        self.assertGreaterEqual(d["disk_percent"], 0)
        self.assertLessEqual(d["disk_percent"], 100)
        self.assertGreaterEqual(d["updates_count"], 0)
        self.assertIsInstance(d["updates"], list)


class TestServiceAgents(unittest.TestCase):

    def test_agents_status_structure(self):
        d = _get("/agents/status")
        self.assertTrue(d.get("ok"), f"Svar: {d}")
        self.assertIn("agents", d)
        agents = d["agents"]
        self.assertIsInstance(agents, dict)

    def test_agents_has_known_keys(self):
        d = _get("/agents/status")
        agents = d.get("agents", {})
        # Minst en agent ska vara registrerad
        self.assertGreater(len(agents), 0, "Inga agenter returnerade")

    def test_each_agent_has_label_and_active(self):
        d = _get("/agents/status")
        for key, info in d.get("agents", {}).items():
            self.assertIn("label",  info, f"Agent '{key}' saknar 'label'")
            self.assertIn("active", info, f"Agent '{key}' saknar 'active'")
            self.assertIn("status", info, f"Agent '{key}' saknar 'status'")


class TestServiceRag(unittest.TestCase):

    def test_rag_query_returns_text(self):
        d = _post("/rag/query", {"q": "vad är en obligation", "top": 2, "ncc": False})
        self.assertTrue(d.get("ok"), f"Svar: {d}")
        self.assertIn("text", d)
        self.assertIsInstance(d["text"], str)
        self.assertGreater(len(d["text"]), 0)

    def test_rag_query_sources_is_list(self):
        d = _post("/rag/query", {"q": "ränta", "top": 3, "ncc": False})
        self.assertIn("sources", d)
        self.assertIsInstance(d["sources"], list)

    def test_rag_ncc_mode(self):
        d = _post("/rag/query", {"q": "odoo", "top": 2, "ncc": True})
        self.assertTrue(d.get("ok"), f"Svar: {d}")
        self.assertIn("text", d)


class TestServiceLibrary(unittest.TestCase):

    def test_library_search_returns_text(self):
        d = _post("/library/search", {"q": "ekonomi"})
        self.assertTrue(d.get("ok"), f"Svar: {d}")
        self.assertIn("text", d)
        self.assertIsInstance(d["text"], str)

    def test_library_empty_query(self):
        """Tom sökning ska returnera ok eller ett tydligt felmeddelande."""
        try:
            d = _post("/library/search", {"q": ""})
            # Antingen ok:true med tomt svar, eller ok:false med error
            self.assertIn("ok", d)
        except urllib.error.HTTPError as e:
            # 4xx är ok — felhantering på server
            self.assertIn(e.code, [400, 422])


class TestServiceUnknownRoute(unittest.TestCase):

    def test_unknown_route_returns_404(self):
        try:
            _get("/this/does/not/exist")
            self.fail("Förväntade HTTPError 404")
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 404)
        except urllib.error.URLError:
            self.fail("Anslutningsfel — är clio-service igång?")


if __name__ == "__main__":
    unittest.main(verbosity=2)
