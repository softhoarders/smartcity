"""Shared Google Gemini JSON generation for Spotflow."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import requests

import config

logger = logging.getLogger(__name__)


def is_configured() -> bool:
    return bool(config.GEMINI_API_KEY)


def generate_text(
    parts: list[dict[str, Any]],
    *,
    model: str | None = None,
    temperature: float = 0.1,
    max_output_tokens: int = 512,
    json_mode: bool = True,
    timeout: int = 120,
) -> str:
    api_key = config.GEMINI_API_KEY
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not configured")

    model_name = model or config.GEMINI_MODEL
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent"

    generation_config: dict[str, Any] = {
        "temperature": temperature,
        "maxOutputTokens": max_output_tokens,
    }
    if json_mode:
        generation_config["responseMimeType"] = "application/json"

    payload = {
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": generation_config,
    }

    resp = requests.post(url, params={"key": api_key}, json=payload, timeout=timeout)
    resp.raise_for_status()
    body = resp.json()

    candidates = body.get("candidates") or []
    if not candidates:
        raise RuntimeError("Gemini returned no candidates")

    content = candidates[0].get("content") or {}
    out_parts = content.get("parts") or []
    texts = [p.get("text", "") for p in out_parts if p.get("text")]
    if not texts:
        raise RuntimeError("Gemini returned empty text")
    return "".join(texts)


def parse_json_response(raw: str) -> dict[str, Any]:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        data = json.loads(match.group(0))
        if isinstance(data, dict):
            return data
    raise ValueError("Could not parse JSON response from Gemini.")


def generate_json(
    parts: list[dict[str, Any]],
    *,
    model: str | None = None,
    temperature: float = 0.1,
    max_output_tokens: int = 512,
    timeout: int = 120,
) -> dict[str, Any]:
    raw = generate_text(
        parts,
        model=model,
        temperature=temperature,
        max_output_tokens=max_output_tokens,
        json_mode=True,
        timeout=timeout,
    )
    return parse_json_response(raw)
