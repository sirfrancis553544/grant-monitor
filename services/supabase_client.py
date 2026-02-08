import os
import requests

def supabase_get(path: str, params: dict | None = None):
    url = os.environ["SUPABASE_URL"].rstrip("/") + "/rest/v1/" + path.lstrip("/")
    key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Accept": "application/json",
    }
    r = requests.get(url, headers=headers, params=params, timeout=30)
    r.raise_for_status()
    return r.json()

def supabase_post(path: str, payload: dict):
    url = os.environ["SUPABASE_URL"].rstrip("/") + "/rest/v1/" + path.lstrip("/")
    key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }
    r = requests.post(url, headers=headers, json=payload, timeout=30)
    r.raise_for_status()
    return r.json()
