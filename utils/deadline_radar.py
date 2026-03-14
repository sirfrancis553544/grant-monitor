from datetime import datetime

def deadline_badge(deadline):
    if not deadline or deadline == "rolling":
        return {"badge": "OPEN"}

    try:
        d = datetime.fromisoformat(deadline)
        days_left = (d - datetime.utcnow()).days
    except Exception:
        return {"badge": "OPEN"}

    if days_left <= 7:
        return {"badge": "⚠️ Closing soon", "days": days_left}

    if days_left <= 30:
        return {"badge": "🔥 Closing soon", "days": days_left}

    return {"badge": "OPEN", "days": days_left}