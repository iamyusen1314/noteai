"""Job-local, memory-only replay of validated Ark assistant thinking state.

The SDK may re-encode tool arguments, so identity uses strict JSON values, not
their wire formatting. Opaque content never belongs in SDK history or tools.
"""
from copy import deepcopy
import hashlib
import json
import math
import re
import sys


MAX_MEMORY_BYTES = 16 * 1024 * 1024
_SAFE_INTEGER = 2 ** 53 - 1
_NAME = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")
_INVALID = "COVER_AGENT_THINKING_CONTEXT_INVALID"
_UNKNOWN = "COVER_AGENT_THINKING_CONTEXT_UNKNOWN"
_MISMATCH = "COVER_AGENT_THINKING_CONTEXT_MISMATCH"
_LIMIT = "COVER_AGENT_THINKING_MEMORY_LIMIT"
_CODES = frozenset({_INVALID, _UNKNOWN, _MISMATCH, _LIMIT})


class ThinkingError(ValueError):
    def __init__(self, code=_MISMATCH):
        self.code = code if code in _CODES else _INVALID
        super().__init__(self.code)


ThinkingStateError = ThinkingError


def _need(condition, code=_INVALID):
    if not condition:
        raise ThinkingError(code)


def _dump(value):
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError):
        raise ThinkingError(_INVALID) from None


def _pairs(items):
    result = {}
    for key, value in items:
        _need(key not in result)
        result[key] = value
    return result


def _constant(_value):
    raise ThinkingError(_INVALID)


def _typed(value):
    """Match JSON values with JS number semantics and without bool/int aliasing."""
    if value is None:
        return ["null"]
    if type(value) is bool:
        return ["boolean", value]
    if type(value) is str:
        return ["string", value]
    if type(value) in {int, float}:
        _need(math.isfinite(value))
        if isinstance(value, int) or value.is_integer():
            _need(abs(value) <= _SAFE_INTEGER)
        number = float(value)
        return ["number", (0.0 if number == 0 else number).hex()]
    if type(value) is list:
        return ["array", [_typed(item) for item in value]]
    _need(type(value) is dict and all(type(key) is str for key in value))
    return ["object", [[key, _typed(value[key])] for key in sorted(value)]]


def _arguments(text):
    _need(type(text) is str)
    try:
        value = json.loads(text, object_pairs_hook=_pairs, parse_constant=_constant)
        _need(type(value) is dict)
        return _typed(value)
    except (ValueError, TypeError, OverflowError, RecursionError):
        raise ThinkingError(_INVALID) from None


def _assistant(message):
    _need(type(message) is dict and message.get("role") == "assistant")
    content = message.get("content")
    _need(content is None or type(content) is str)
    saved = {"role": "assistant", "content": content}
    original_calls = message.get("tool_calls", [])
    _need(original_calls is None or type(original_calls) is list)
    calls = original_calls or []
    identifiers, signatures, projected = [], [], []
    for call in calls:
        _need(type(call) is dict and call.get("type") == "function"
              and type(call.get("id")) is str and _NAME.fullmatch(call["id"]))
        function = call.get("function")
        _need(type(function) is dict and type(function.get("name")) is str
              and _NAME.fullmatch(function["name"]))
        identifier, name = call["id"], function["name"]
        _need(identifier not in identifiers)
        arguments = function.get("arguments")
        signatures.append([identifier, name, _arguments(arguments)])
        identifiers.append(identifier)
        projected.append({"id": identifier, "type": "function",
                          "function": {"name": name, "arguments": arguments}})
    if "tool_calls" in message:
        saved["tool_calls"] = None if original_calls is None else projected
    for key in ("reasoning_content", "encrypted_content"):
        value = message.get(key)
        _need(value is None or type(value) is str)
        if value is not None:
            saved[key] = value
    # The fixed SDK turns empty text into null when replaying a tool-call turn.
    # Nonempty text is always matched exactly; non-tool null/empty stay distinct.
    content_key = ["tool-empty"] if calls and content in {None, ""} else ["text", content]
    fingerprint = hashlib.sha256(_dump([content_key, signatures])).hexdigest()
    return saved, fingerprint, identifiers


def _size(value, seen=None):
    """Conservative retained Python-container footprint, including map overhead."""
    seen = set() if seen is None else seen
    identity = id(value)
    if identity in seen:
        return 0
    seen.add(identity)
    result = sys.getsizeof(value)
    if isinstance(value, dict):
        result += sum(_size(key, seen) + _size(item, seen) for key, item in value.items())
    elif isinstance(value, (tuple, list)):
        result += sum(_size(item, seen) for item in value)
    return result


class ThinkingState:
    """One Bridge/job only; no persistence, export, retry, or Invocation changes."""
    def __init__(self, job_id, *, max_bytes=MAX_MEMORY_BYTES):
        _need(type(job_id) is str and _NAME.fullmatch(job_id))
        _need(type(max_bytes) is int and 0 < max_bytes <= MAX_MEMORY_BYTES)
        self._job_id = job_id
        self._max_bytes = max_bytes
        self._messages = {}
        self._ids = {}
        self._bytes = _size((job_id, self._messages, self._ids))
        _need(self._bytes <= max_bytes, _LIMIT)

    @property
    def retained_bytes(self):
        return self._bytes

    @property
    def entry_count(self):
        return len(self._messages)

    def remember(self, response):
        """Retain allowed assistant state; return response without its cipher."""
        _need(type(response) is dict and type(response.get("choices")) is list
              and len(response["choices"]) == 1 and type(response["choices"][0]) is dict)
        message = response["choices"][0].get("message")
        saved, key, identifiers = _assistant(message)
        body = _dump(saved)
        _need(len(body) <= self._max_bytes, _LIMIT)
        _need(all(self._ids.get(identifier, key) == key for identifier in identifiers), _MISMATCH)
        if key in self._messages:
            _need(self._messages[key] == body, _MISMATCH)
        else:
            messages, ids = dict(self._messages), dict(self._ids)
            messages[key] = body
            ids.update((identifier, key) for identifier in identifiers)
            retained = _size((self._job_id, messages, ids))
            _need(retained <= self._max_bytes, _LIMIT)
            self._messages, self._ids, self._bytes = messages, ids, retained
        result = deepcopy(response)
        result["choices"][0]["message"].pop("encrypted_content", None)
        return result

    def restore(self, payload):
        """Restore only whole known assistant turns, before the normal meter."""
        _need(type(payload) is dict and type(payload.get("messages")) is list)
        result = deepcopy(payload)
        used_ids = set()
        for index, message in enumerate(result["messages"]):
            _need(type(message) is dict)
            if message.get("role") != "assistant":
                continue
            _projected, key, identifiers = _assistant(message)
            _need(not used_ids.intersection(identifiers), _MISMATCH)
            used_ids.update(identifiers)
            known = self._messages.get(key)
            if known is None:
                _need(not any(identifier in self._ids for identifier in identifiers), _MISMATCH)
                raise ThinkingError(_UNKNOWN)
            original = json.loads(known)
            if "encrypted_content" in message:
                _need(message["encrypted_content"] == original.get("encrypted_content"), _MISMATCH)
            result["messages"][index] = original
        return result
