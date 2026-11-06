"""Minimal multimodal client for Gemini (default, free tier) and OpenAI.

Plain HTTPS with `requests` — no SDKs — so the model ids in app.py are the only thing
that needs updating when providers release new models.
"""
import base64
import json
import re
import threading
import time

import cv2
import requests
from flask import current_app

_rate_lock = threading.Lock()
_last_call = [0.0]


class AIError(Exception):
    def __init__(self, msg, quota=False, fatal=False):
        super().__init__(msg)
        self.quota = quota
        self.fatal = fatal  # retrying won't help (bad key, no credit)


def settings():
    c = current_app.config
    prov = (c.get("AI_PROVIDER") or "none").lower()
    key = c.get("GEMINI_API_KEY") if prov == "gemini" else c.get("OPENAI_API_KEY") if prov == "openai" else ""
    model = c.get("GEMINI_MODEL") if prov == "gemini" else c.get("OPENAI_MODEL")
    return {"provider": prov, "key": key or "", "model": model, "rpm": max(1, int(c.get("AI_RPM", 8)))}


def available():
    s = settings()
    return s["provider"] in ("gemini", "openai") and bool(s["key"])


def status():
    s = settings()
    label = {"gemini": "Google Gemini", "openai": "OpenAI"}.get(s["provider"], "Off")
    return {"provider": s["provider"], "label": label, "model": s["model"], "configured": available(),
            "rpm": s["rpm"], "vlm": bool(current_app.config.get("VLM_ENABLED")) and available()}


def jpeg_bytes(img_bgr, max_side=1280, quality=85):
    h, w = img_bgr.shape[:2]
    k = min(1.0, max_side / max(h, w))
    if k < 1:
        img_bgr = cv2.resize(img_bgr, (int(w * k), int(h * k)), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", img_bgr, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok:
        raise AIError("Could not encode image")
    return buf.tobytes()


def _throttle(rpm):
    """Keep under the provider's requests-per-minute limit (free tier ~10 RPM)."""
    gap = 60.0 / rpm
    with _rate_lock:
        wait = _last_call[0] + gap - time.time()
        if wait > 0:
            time.sleep(wait)
        _last_call[0] = time.time()


def _parse_json(text):
    text = (text or "").strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if m:
        text = m.group(1)
    try:
        return json.loads(text)
    except ValueError:
        a, b = text.find("{"), text.rfind("}")
        if a >= 0 and b > a:
            return json.loads(text[a:b + 1])
        raise AIError("The model did not return valid JSON")


def generate_json(system, prompt, images=(), temperature=0.2, max_tokens=4096):
    """images: list of JPEG bytes. Returns a dict parsed from the model's JSON answer."""
    s = settings()
    if not available():
        raise AIError("No AI provider configured")
    last_err = None
    for attempt in range(3):
        _throttle(s["rpm"])
        try:
            if s["provider"] == "gemini":
                text = _gemini(s, system, prompt, images, temperature, max_tokens)
            else:
                text = _openai(s, system, prompt, images, temperature, max_tokens)
            return _parse_json(text)
        except AIError as e:
            last_err = e
            current_app.logger.warning("AI call failed (attempt %s): %s", attempt + 1, e)
            if e.quota and attempt < 2:
                time.sleep(15 * (attempt + 1))
                continue
            if not e.quota and not e.fatal and attempt < 1:
                continue
            raise
        except requests.RequestException as e:
            last_err = AIError(f"Network error reaching {s['provider']}: {e.__class__.__name__}: {e}"[:300])
            current_app.logger.warning("AI call failed (attempt %s): %s", attempt + 1, last_err)
            if attempt >= 1:
                break
            time.sleep(3)
    raise last_err


def _check(r, who):
    if r.status_code == 200:
        return
    try:
        msg = r.json().get("error", {}).get("message", r.text[:200])
    except ValueError:
        msg = r.text[:200]
    low = (msg or "").lower()
    if "insufficient_quota" in r.text or "exceeded your current quota" in low or "billing" in low:
        # No credit on the account: retrying won't help.
        raise AIError(f"{who} {r.status_code}: no API credit on this account. Add billing/credit, then try again. ({msg})", fatal=True)
    if r.status_code in (401, 403):
        raise AIError(f"{who} {r.status_code}: the API key was rejected. Check the key in .env. ({msg})", fatal=True)
    raise AIError(f"{who} {r.status_code}: {msg}", quota=r.status_code in (429, 503))


_no_thinking_cfg = set()  # models that rejected thinkingConfig


def _gemini(s, system, prompt, images, temperature, max_tokens):
    parts = [{"text": prompt}]
    for b in images:
        parts.append({"inline_data": {"mime_type": "image/jpeg", "data": base64.b64encode(b).decode()}})
    gen = {"temperature": temperature, "maxOutputTokens": max_tokens, "responseMimeType": "application/json"}
    level = (current_app.config.get("GEMINI_THINKING") or "").strip().lower()
    if level and s["model"] not in _no_thinking_cfg:
        # Gemini 3.x thinks before answering and the thinking counts against maxOutputTokens.
        gen["thinkingConfig"] = {"thinkingLevel": level}
    body = {
        "system_instruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": gen,
    }
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{s['model']}:generateContent"
    r = requests.post(url, json=body, headers={"x-goog-api-key": s["key"]}, timeout=90)
    if r.status_code == 400 and "thinking" in r.text.lower() and "thinkingConfig" in gen:
        _no_thinking_cfg.add(s["model"])  # this model doesn't take thinkingLevel; retry without it
        gen.pop("thinkingConfig")
        r = requests.post(url, json=body, headers={"x-goog-api-key": s["key"]}, timeout=90)
    _check(r, "Gemini")
    data = r.json()
    cands = data.get("candidates") or []
    if not cands:
        reason = (data.get("promptFeedback") or {}).get("blockReason") or "empty response"
        raise AIError(f"Gemini returned no answer ({reason})")
    cand = cands[0]
    text = "".join(p.get("text", "") for p in (cand.get("content") or {}).get("parts", []) if not p.get("thought"))
    finish = cand.get("finishReason", "")
    if not text.strip():
        raise AIError(f"Gemini returned an empty answer (finishReason={finish or 'unknown'})")
    if finish == "MAX_TOKENS":
        try:
            json.loads(_strip_fence(text))
        except ValueError:
            raise AIError("Gemini ran out of output tokens before finishing the JSON (finishReason=MAX_TOKENS)")
    return text


def _strip_fence(text):
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    return m.group(1) if m else text


def ping():
    """Small text + image round trip to test the key, the model id and vision input. Returns (ok, message, ms)."""
    import numpy as np
    img = np.full((64, 64, 3), 200, np.uint8)
    t = time.time()
    try:
        data = generate_json("Reply with JSON only.", 'Return {"ok": true, "shape": "<what you see in the image>"}',
                             [jpeg_bytes(img)], temperature=0, max_tokens=1024)
        return True, f"Connected. The model answered: {json.dumps(data, ensure_ascii=False)[:160]}", int((time.time() - t) * 1000)
    except AIError as e:
        return False, str(e), int((time.time() - t) * 1000)


def _openai(s, system, prompt, images, temperature, max_tokens):
    content = [{"type": "text", "text": prompt}]
    for b in images:
        content.append({"type": "image_url",
                        "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(b).decode(),
                                      "detail": "high"}})
    body = {
        "model": s["model"],
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": content}],
        "response_format": {"type": "json_object"},
        "max_completion_tokens": max(max_tokens, 16000),  # reasoning tokens count toward this
    }
    effort = (current_app.config.get("OPENAI_REASONING") or "").strip().lower()
    if effort:
        body["reasoning_effort"] = effort
    url = "https://api.openai.com/v1/chat/completions"
    headers = {"Authorization": f"Bearer {s['key']}"}
    r = requests.post(url, json=body, headers=headers, timeout=120)
    # Drop optional parameters the model doesn't accept and try once more.
    for _ in range(2):
        if r.status_code != 400:
            break
        txt = r.text.lower()
        dropped = False
        for k in ("reasoning_effort", "response_format"):
            if k in body and k in txt:
                body.pop(k)
                dropped = True
        if not dropped:
            break
        r = requests.post(url, json=body, headers=headers, timeout=120)
    _check(r, "OpenAI")
    choice = r.json()["choices"][0]
    text = (choice.get("message") or {}).get("content") or ""
    if not text.strip():
        raise AIError(f"OpenAI returned an empty answer (finish_reason={choice.get('finish_reason')})")
    return text
