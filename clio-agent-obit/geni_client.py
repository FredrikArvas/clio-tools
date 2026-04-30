"""
Geni API-klient.
Hämtar immediate-family för en profil och returnerar ett strukturerat fingeravtryck.
"""
import os
import re
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

BASE_URL = "https://www.geni.com/api"
TOKEN_URL = "https://www.geni.com/platform/oauth/token"


def _token() -> str:
    t = os.getenv("GENI_ACCESS_TOKEN", "")
    if not t:
        raise RuntimeError("GENI_ACCESS_TOKEN saknas i .env — kor geni_auth.py")
    return t


def _refresh() -> str:
    app_id = os.getenv("GENI_APP_ID", "")
    app_secret = os.getenv("GENI_APP_SECRET", "")
    refresh = os.getenv("GENI_REFRESH_TOKEN", "")
    if not all([app_id, app_secret, refresh]):
        raise RuntimeError("Kan inte refresha token — kor geni_auth.py")
    resp = requests.post(TOKEN_URL, data={
        "client_id": app_id,
        "client_secret": app_secret,
        "refresh_token": refresh,
        "grant_type": "refresh_token",
    }, timeout=15)
    resp.raise_for_status()
    return resp.json()["access_token"]


def _get(path: str, params: dict = None) -> dict:
    token = _token()
    p = {"access_token": token, **(params or {})}
    resp = requests.get(f"{BASE_URL}/{path}", params=p, timeout=15)
    if resp.status_code == 401:
        token = _refresh()
        p["access_token"] = token
        resp = requests.get(f"{BASE_URL}/{path}", params=p, timeout=15)
    resp.raise_for_status()
    return resp.json()


def profile_id_from_url(url: str) -> str:
    """https://www.geni.com/people/Namn/6000000072669832838 -> 6000000072669832838"""
    m = re.search(r"/people/[^/]+/(\d+)", url)
    if m:
        return m.group(1)
    m = re.search(r"(\d{10,})", url)
    if m:
        return m.group(1)
    raise ValueError(f"Kan inte extrahera profil-ID ur: {url}")


def _parse_profile(node: dict) -> dict:
    names = node.get("names", {})
    sv = names.get("sv", names.get("en", {}))
    first = sv.get("first_name", node.get("first_name", ""))
    last = sv.get("last_name", node.get("last_name", ""))
    return {
        "geni_id": node.get("id", "").replace("profile-", ""),
        "name": f"{first} {last}".strip() or node.get("name", ""),
        "birth_date": node.get("birth", {}).get("date", {}).get("formatted", ""),
        "birth_location": node.get("birth", {}).get("location", {}).get("city", ""),
        "death_date": node.get("death", {}).get("date", {}).get("formatted", ""),
        "gender": node.get("gender", ""),
    }


def get_immediate_family(profile_id: str) -> dict:
    """
    Hamtar narmaste familj for en Geni-profil.
    Returnerar: focus, partners, children, siblings, parents.
    """
    data = _get(f"profile-{profile_id}/immediate-family")

    focus_raw = data.get("focus", {})
    nodes = data.get("nodes", {})
    focus = _parse_profile(focus_raw)
    focus_geni_id = f"profile-{profile_id}"

    partners, children, siblings, parents = [], [], [], []

    unions = {k: v for k, v in nodes.items() if k.startswith("union-")}
    profiles = {k: v for k, v in nodes.items() if k.startswith("profile-")}

    for union_id, union in unions.items():
        partners_in = union.get("partners", [])
        children_in = union.get("children", [])
        is_focus_partner = focus_geni_id in partners_in

        if is_focus_partner:
            for pid in partners_in:
                if pid != focus_geni_id and pid in profiles:
                    partners.append(_parse_profile(profiles[pid]))
            for cid in children_in:
                if cid in profiles:
                    children.append(_parse_profile(profiles[cid]))
        else:
            if focus_geni_id in children_in:
                for pid in partners_in:
                    if pid in profiles:
                        parents.append(_parse_profile(profiles[pid]))
                for cid in children_in:
                    if cid != focus_geni_id and cid in profiles:
                        siblings.append(_parse_profile(profiles[cid]))

    return {
        "focus": focus,
        "partners": partners,
        "children": children,
        "siblings": siblings,
        "parents": parents,
    }
