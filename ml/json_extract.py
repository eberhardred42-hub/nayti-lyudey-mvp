from __future__ import annotations

import json
from typing import Any, Optional


class JsonExtractError(ValueError):
    pass


def _try_json_loads(candidate: str) -> Optional[dict[str, Any]]:
    try:
        parsed = json.loads(candidate)
    except Exception:
        return None
    if isinstance(parsed, dict):
        return parsed
    return None


def _extract_from_code_fence(text: str) -> Optional[dict[str, Any]]:
    # Looks for ```json ... ``` or ``` ... ``` and tries to parse inside.
    # Keep it simple: scan for fences instead of regex (avoids catastrophic backtracking).
    fence = "```"
    i = 0
    n = len(text)
    while True:
        start = text.find(fence, i)
        if start == -1:
            return None
        header_end = text.find("\n", start + 3)
        if header_end == -1:
            return None
        header = text[start + 3 : header_end].strip().lower()
        end = text.find(fence, header_end + 1)
        if end == -1:
            return None
        body = text[header_end + 1 : end].strip()
        if header in ("", "json"):
            parsed = _try_json_loads(body)
            if parsed is not None:
                return parsed
        i = end + 3
        if i >= n:
            return None


def _find_balanced_object(text: str, start: int) -> Optional[str]:
    # Returns substring containing a balanced JSON object starting at `start`.
    if start < 0 or start >= len(text) or text[start] != "{":
        return None

    depth = 0
    in_string = False
    escape = False
    for idx in range(start, len(text)):
        ch = text[idx]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue

        if ch == '"':
            in_string = True
            continue

        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : idx + 1]

    return None


def extract_json(text: str) -> dict[str, Any]:
    """Extract a JSON object from a potentially wrapped LLM output.

    Supports:
    - pure JSON object
    - fenced code blocks (```json ...```)
    - JSON object embedded in surrounding text

    Returns a dict; raises JsonExtractError on failure.
    """

    if text is None:
        raise JsonExtractError("no text")

    raw = text.strip()
    if not raw:
        raise JsonExtractError("empty text")

    direct = _try_json_loads(raw)
    if direct is not None:
        return direct

    fenced = _extract_from_code_fence(raw)
    if fenced is not None:
        return fenced

    # Scan for first balanced {...} that parses as dict.
    # Try multiple starts to be robust when there are multiple JSON blocks.
    idx = 0
    while True:
        start = raw.find("{", idx)
        if start == -1:
            break
        candidate = _find_balanced_object(raw, start)
        if candidate is not None:
            parsed = _try_json_loads(candidate)
            if parsed is not None:
                return parsed
            # if balanced but not parseable, keep scanning after start
        idx = start + 1

    raise JsonExtractError("could not extract JSON object")
