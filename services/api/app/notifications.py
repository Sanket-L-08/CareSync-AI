import httpx, logging
from .config import get_settings

log = logging.getLogger("caresync.notify")


async def ai_completion(system: str, user: str) -> str | None:
    s = get_settings()
    if not (s.ai_base_url and s.ai_api_key and s.ai_model):
        return None
    async with httpx.AsyncClient(timeout=45) as client:
        r = await client.post(f"{s.ai_base_url}/chat/completions", headers={"Authorization": f"Bearer {s.ai_api_key}"},
                              json={"model": s.ai_model, "temperature": 0.2,
                                    "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]})
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]


def send_webhook_sync(payload: dict) -> bool:
    """Webhook payloads never contain names or free text — only identifiers and severity (data minimisation)."""
    url = get_settings().alert_webhook_url
    if not url or not url.startswith("https://"):
        return False
    try:
        httpx.post(url, json=payload, timeout=10).raise_for_status()
        return True
    except Exception as e:  # pragma: no cover
        log.warning("webhook failed: %s", type(e).__name__)
        return False
