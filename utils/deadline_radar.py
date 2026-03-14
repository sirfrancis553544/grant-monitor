from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict


def deadline_badge(deadline: Any) -> Dict[str, Any]:
    """
    Returns a structured badge used in grant cards.

    Example outputs:
      {"badge": "OPEN"}
      {"badge": "🔥 Closing soon", "days": 12}
      {"badge": "⚠️ Last days", "days": 3}
      {"badge": "Closed"}
    """

    if not deadline:
        return {"badge": "OPEN"}

    raw = str(deadline).strip().lower()

    if raw in {"rolling", "open"}:
        return {"badge": "OPEN"}

    try:
        d = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)

        now = datetime.now(timezone.utc)
        days_left = (d - now).days

    except Exception:
        return {"badge": "OPEN"}

    if days_left < 0:
        return {"badge": "Closed"}

    if days_left <= 7:
        return {"badge": "⚠️ Last days", "days": days_left}

    if days_left <= 30:
        return {"badge": "🔥 Closing soon", "days": days_left}

    return {"badge": "OPEN", "days": days_left}