"""Anthropic API access for the weekly report narrative and Pat-GPT.

The model is ANTHROPIC_MODEL if set; otherwise the newest Sonnet model the
API key can use, looked up once from the models list.
"""
from __future__ import annotations

import threading

from app.config import MissingConfig, load_settings

_MODEL: dict = {}
_LOCK = threading.Lock()


def client():
    import anthropic
    key = load_settings().anthropic_api_key
    if not key:
        raise MissingConfig("ANTHROPIC_API_KEY")
    return anthropic.Anthropic(api_key=key, timeout=90, max_retries=2)


def model() -> str:
    configured = load_settings().anthropic_model
    if configured:
        return configured
    with _LOCK:
        if "id" not in _MODEL:
            ids = [m.id for m in client().models.list(limit=50)]       # newest first
            _MODEL["id"] = next((i for i in ids if "sonnet" in i), ids[0])
        return _MODEL["id"]


def text_of(message) -> str:
    return "".join(b.text for b in message.content if getattr(b, "type", "") == "text").strip()


def check() -> dict:
    return {"ok": True, "model": model()}
