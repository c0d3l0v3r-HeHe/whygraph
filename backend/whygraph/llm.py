"""Gemini client tuned for the free tier: JSON output, disk cache, timeouts,
per-model cooldowns and a fallback chain across models."""
from __future__ import annotations

import json
import logging
import re
import threading
import time
from typing import Any

from google import genai
from google.genai import types

from . import cache
from .config import GEMINI_API_KEY, GEMINI_MODELS, LLM_MIN_INTERVAL

log = logging.getLogger(__name__)

_client: genai.Client | None = None
_lock = threading.Lock()
_last_call = 0.0
_cooldown_until: dict[str, float] = {}


class LLMUnavailable(RuntimeError):
    pass


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        if not GEMINI_API_KEY:
            raise LLMUnavailable("GEMINI_API_KEY is not set")
        _client = genai.Client(
            api_key=GEMINI_API_KEY,
            http_options=types.HttpOptions(timeout=45_000),
        )
    return _client


def _throttle() -> None:
    global _last_call
    with _lock:
        wait = _last_call + LLM_MIN_INTERVAL - time.time()
        if wait > 0:
            time.sleep(wait)
        _last_call = time.time()


def _parse_json(text: str) -> Any:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Lite models sometimes emit backslashes from code (e.g. "\d") without escaping them.
        return json.loads(re.sub(r'\\(?!["\\/bfnrtu])', r"\\\\", text), strict=False)


def _retry_delay(err: str) -> float:
    m = re.search(r"retry in ([\d.]+)s", err) or re.search(r"retryDelay['\"]?: ['\"]?(\d+)s", err)
    return float(m.group(1)) if m else 60.0


def generate_json(
    prompt: str,
    *,
    system: str | None = None,
    namespace: str = "llm",
    temperature: float = 0.1,
    max_rounds: int = 6,
    use_cache: bool = True,
    models: list[str] | None = None,
    deadline_s: float | None = None,
) -> Any:
    """Return parsed JSON from the first model that answers. Cached by prompt."""
    key = json.dumps([system, prompt, temperature])
    if use_cache:
        hit = cache.get(namespace, key)
        if hit is not None:
            return hit

    client = _get_client()
    cfg = types.GenerateContentConfig(
        system_instruction=system,
        temperature=temperature,
        response_mime_type="application/json",
    )
    last_err = ""
    chain = models or GEMINI_MODELS
    stop_at = time.time() + deadline_s if deadline_s else None
    for round_ in range(max_rounds):
        tried_any = False
        for model in chain:
            if stop_at and time.time() > stop_at:
                raise LLMUnavailable(f"deadline exceeded ({last_err})")
            if _cooldown_until.get(model, 0) > time.time():
                continue
            tried_any = True
            _throttle()
            try:
                resp = client.models.generate_content(model=model, contents=prompt, config=cfg)
                data = _parse_json(resp.text or "")
                if use_cache:
                    cache.put(namespace, key, data)
                return data
            except json.JSONDecodeError as e:
                last_err = f"{model}: bad JSON ({e})"
                log.warning(last_err)
                continue
            except Exception as e:  # network, 429, 503, timeouts
                last_err = f"{model}: {e}"
                msg = str(e)
                if "429" in msg or "RESOURCE_EXHAUSTED" in msg:
                    _cooldown_until[model] = time.time() + _retry_delay(msg)
                elif "503" in msg or "UNAVAILABLE" in msg or "timed out" in msg.lower() or "timeout" in msg.lower():
                    _cooldown_until[model] = time.time() + 30
                elif "404" in msg or "NOT_FOUND" in msg:
                    _cooldown_until[model] = time.time() + 86400
                else:
                    _cooldown_until[model] = time.time() + 20
                log.warning("LLM call failed on %s: %s", model, msg[:200])
        # Everything is cooling down: wait for the soonest model to come back.
        soonest = min(_cooldown_until.get(m, 0) for m in chain)
        wait = max(5.0, min(soonest - time.time(), 120.0)) if not tried_any or soonest > time.time() else 5.0
        if stop_at:
            if time.time() + wait > stop_at:
                raise LLMUnavailable(f"deadline exceeded ({last_err})")
        log.info("All models busy (round %d); sleeping %.0fs", round_ + 1, wait)
        time.sleep(wait)
    raise LLMUnavailable(last_err or "no model available")


def available() -> bool:
    return bool(GEMINI_API_KEY)
