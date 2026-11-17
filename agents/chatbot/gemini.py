"""Minimální klient Gemini API (REST, jen standardní knihovna, žádný balíček navíc).

Klíč jde v hlavičce x-goog-api-key, ne v URL, takže se neobjeví v chybových hláškách.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

API = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


class LLMError(Exception):
    """Selhání LLM. Zpráva obsahuje jen HTTP kód, nikdy klíč ani tělo odpovědi."""


def generate(*, api_key: str, model: str, system: str, contents: list, tools: list,
             max_output_tokens: int = 1024, timeout: float = 30) -> dict:
    if not api_key:
        raise LLMError("missing api key")
    body = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": contents,
        "tools": [{"functionDeclarations": tools}],
        "toolConfig": {"functionCallingConfig": {"mode": "AUTO"}},
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": max_output_tokens},
    }
    req = urllib.request.Request(
        API.format(model=model), data=json.dumps(body).encode(), method="POST",
        headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        raise LLMError(f"gemini http {e.code}") from None
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
        raise LLMError(f"gemini unreachable: {type(e).__name__}") from None
