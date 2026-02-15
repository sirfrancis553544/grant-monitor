import os
import json
import urllib.parse
import urllib.request
import urllib.error


def _env(name: str) -> str:
    v = os.environ.get(name)
    if not v:
        raise RuntimeError(f"Missing env var: {name}")
    return v.strip()


def _request(method: str, url: str, headers: dict, body: dict | None = None) -> dict | list | None:
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")

    req = urllib.request.Request(url=url, data=data, method=method)
    for k, v in headers.items():
        req.add_header(k, v)

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8").strip()
            if not raw:
                return None
            return json.loads(raw)
    except urllib.error.HTTPError as e:
        err = e.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"HTTP {e.code} calling {url}: {err}") from e


def _rest_headers() -> dict:
    # We don't actually need supabase_url here, but leaving it is fine.
    supabase_key = _env("SUPABASE_SERVICE_ROLE_KEY")

    # ✅ This is the correct “common bug fix” header set:
    return {
        "apikey": supabase_key,
        "Authorization": f"Bearer {supabase_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        # Optional but fine to keep (PostgREST)
        "Prefer": "return=representation",
    }


def get_active_subscribers() -> list[dict]:
    supabase_url = _env("SUPABASE_URL").rstrip("/")
    headers = _rest_headers()

    qs = urllib.parse.urlencode({
        "select": "id,email,pack,unsubscribe_token",
        "status": "eq.active",
    })
    url = f"{supabase_url}/rest/v1/subscribers?{qs}"

    data = _request("GET", url, headers)
    return data if isinstance(data, list) else []


def log_send(
    subscriber_id: str,
    pack: str,
    item_count: int,
    status: str = "ok",
    error: str | None = None
) -> None:
    supabase_url = _env("SUPABASE_URL").rstrip("/")
    headers = _rest_headers()

    payload = {
        "subscriber_id": subscriber_id,
        "pack": pack,
        "item_count": int(item_count),
        "status": status,
        "error": error,
    }

    url = f"{supabase_url}/rest/v1/send_logs"
    _request("POST", url, headers, payload)
