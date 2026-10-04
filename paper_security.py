"""Deterministic boundaries; text screening is defense in depth, not a proof."""
import hashlib
import hmac
import json
import os
import re
import unicodedata
from pathlib import Path

MAX_INPUT_BYTES = 8_000_000
MAX_BUNDLE_BYTES = 32_000_000
MAX_MODEL_CALLS = 300
MAX_PAYLOAD_CHARS = 160_000

# Deliberately conservative: flag for investigation, never silently delete evidence.
PATTERNS = {
    "instruction_override": r"\b(?:ignore|disregard|override)\b.{0,60}\b(?:instructions?|prompts?|rules?|system)\b",
    "role_spoofing": r"<\|(?:im_start|im_end|system|assistant)|\[INST\]|(?:^|\n)\s*(?:system|developer)\s*:",
    "approval_spoofing": r"\b(?:skip|bypass|disable)\b.{0,60}\b(?:review|verification|guardrails?|approval)\b",
    "secret_request": r"\b(?:reveal|print|send|exfiltrate|upload)\b.{0,80}\b(?:api.?key|secret|password|environment variable|system prompt)\b",
    "active_markup": r"<\s*(?:script|iframe|object|embed)\b|javascript\s*:",
}


def security_flags(value):
    if isinstance(value, dict):
        return sorted({flag for item in value.values() for flag in security_flags(item)})
    if isinstance(value, list):
        return sorted({flag for item in value for flag in security_flags(item)})
    text = value if isinstance(value, str) else str(value)
    normalized = unicodedata.normalize("NFKC", text)
    flags = [name for name, pattern in PATTERNS.items()
             if re.search(pattern, normalized, re.IGNORECASE)]
    if any(unicodedata.category(c) in {"Cf", "Cs"} or
           (unicodedata.category(c) == "Cc" and c not in "\n\r\t") for c in text):
        flags.append("hidden_or_control_characters")
    return flags


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def load_json(path, max_bytes=MAX_INPUT_BYTES):
    with Path(path).open("rb") as handle:
        data = handle.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ValueError("JSON file exceeds size limit")
    return json.loads(data, object_pairs_hook=_unique_object,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite JSON number")))


def write_new_json(path, value):
    """Exclusive creation: never follow an existing symlink or overwrite an artifact."""
    data = json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as handle:
        handle.write(data)


def review_key(key=None):
    key = key if key is not None else os.environ.get("PAPER_REVIEW_SIGNING_KEY", "")
    if not isinstance(key, str) or len(key.encode()) < 32:
        raise ValueError("A reviewer/publisher-only PAPER_REVIEW_SIGNING_KEY of at least 32 bytes is required")
    return key.encode()


def review_signature(review, key=None):
    payload = {k: v for k, v in review.items() if k != "signature"}
    return hmac.new(review_key(key), json.dumps(payload, sort_keys=True,
                    ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode(), hashlib.sha256).hexdigest()


def require_signed_review(review, key=None):
    supplied = review.get("signature")
    if not isinstance(supplied, str) or not hmac.compare_digest(supplied, review_signature(review, key)):
        raise ValueError("Missing or invalid human review signature")
