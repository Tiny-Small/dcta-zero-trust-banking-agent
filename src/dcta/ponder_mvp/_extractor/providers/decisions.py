"""Minimal evaluation-only OpenRouter Decisions transport. Never logs credentials."""
import json
import math
import os
import re
import shlex
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ENDPOINT = "https://openrouter.ai/api/alpha/decisions"
DEFAULT_MODEL = "typesafe/jev-1.13"

def read_settings(path=Path(".envrc")):
    settings = {}
    if Path(path).is_file():
        for line in Path(path).read_text().splitlines():
            found = re.fullmatch(r"\s*(?:export\s+)?(OPENROUTER_API_KEY|JEV_MODEL)\s*=\s*(.*?)\s*", line)
            if not found:
                continue
            try:
                words = shlex.split(found[2], comments=True)
            except ValueError:
                raise ValueError("Invalid local provider assignment") from None
            if len(words) != 1 or "$" in words[0] or "\x60" in words[0]:
                raise ValueError("Provider settings must be literal values")
            settings[found[1]] = words[0]
    key = os.getenv("OPENROUTER_API_KEY") or settings.get("OPENROUTER_API_KEY")
    model = os.getenv("JEV_MODEL") or settings.get("JEV_MODEL", DEFAULT_MODEL)
    if not key or not isinstance(model, str) or not model.strip():
        raise ValueError("Configured provider credential or model unavailable")
    return key, model

def _probability(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and 0 <= value <= 1

def parse_choices(envelope, questions):
    """Exact question keys and supplied choices only. Noul never becomes NONE."""
    all_errors = {key: "provider_contract_error" for key in questions}
    answers = envelope.get("answers") if isinstance(envelope, dict) else None
    if not isinstance(answers, dict) or set(answers) != set(questions):
        return {}, all_errors
    valid, errors = {}, {}
    for key, answer in answers.items():
        criteria = questions[key].get("criteria", {})
        bad = not isinstance(answer, dict) or answer.get("type") != "choice"
        if not bad:
            bad = not isinstance(answer.get("choice"), str) or answer["choice"] not in criteria
        if not bad and answer.get("confidence") is not None:
            bad = not _probability(answer["confidence"])
        if not bad and answer.get("probabilities") is not None:
            probs = answer["probabilities"]
            bad = not isinstance(probs, dict) or not set(probs) <= set(criteria) or any(not _probability(p) for p in probs.values())
        if bad:
            errors[key] = "provider_contract_error"
        else:
            valid[key] = answer
    return valid, errors

def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result

def _reject_constant(value):
    raise ValueError("Nonfinite JSON constant")

class DecisionsProvider:
    def __init__(self, api_key, *, model=DEFAULT_MODEL, timeout=20, opener=urlopen):
        if not api_key:
            raise ValueError("Provider credential required")
        self._key = api_key
        self.model = model
        self.timeout = timeout
        self._opener = opener

    def decide(self, *, state, questions):
        body = {"model": self.model, "state": state, "questions": questions}
        safe_headers = {"Content-Type": "application/json", "X-OpenRouter-Metadata": "enabled"}
        request = Request(ENDPOINT, data=json.dumps(body, ensure_ascii=False, allow_nan=False).encode(),
                          headers={**safe_headers, "Authorization": "Bearer " + self._key}, method="POST")
        result = {"request": {"method": "POST", "endpoint": ENDPOINT, "body": body, "headers": safe_headers},
                  "http_status": None, "raw_response_text": None, "raw_response": None,
                  "answers": {}, "errors": {}, "error_class": None, "retries": 0}
        started = time.perf_counter()
        try:
            try:
                with self._opener(request, timeout=self.timeout) as response:
                    result["http_status"] = response.status
                    raw = response.read()
            except HTTPError as error:
                result["http_status"] = error.code
                raw = error.read()
            except (URLError, TimeoutError, OSError) as error:
                result["error_class"] = "provider_timeout/error"
                result["transport_error_type"] = type(error).__name__
                raw = None
            if raw is not None:
                text = raw.decode("utf-8", errors="replace").replace(self._key, "[REDACTED]")
                result["raw_response_text"] = text
                try:
                    envelope = json.loads(text, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
                    result["raw_response"] = envelope
                except (ValueError, TypeError):
                    envelope = None
                if not 200 <= result["http_status"] < 300:
                    result["error_class"] = "provider_timeout/error"
                else:
                    result["answers"], result["errors"] = parse_choices(envelope, questions)
                    if result["errors"]:
                        result["error_class"] = "provider_contract_error"
            if result["error_class"] and not result["errors"]:
                result["errors"] = {key: result["error_class"] for key in questions}
        finally:
            result["latency_ms"] = (time.perf_counter() - started) * 1000
        # Scrub the known credential even if a caller accidentally included it in state.
        return json.loads(json.dumps(result, ensure_ascii=False, allow_nan=False).replace(self._key, "[REDACTED]"))
