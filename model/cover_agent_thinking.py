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
MAX_MALFORMED_TURNS = 2
_SAFE_INTEGER = 2 ** 53 - 1
_NAME = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")
_INVALID = "COVER_AGENT_THINKING_CONTEXT_INVALID"
_UNKNOWN = "COVER_AGENT_THINKING_CONTEXT_UNKNOWN"
_MISMATCH = "COVER_AGENT_THINKING_CONTEXT_MISMATCH"
_LIMIT = "COVER_AGENT_THINKING_MEMORY_LIMIT"
_CODES = frozenset({_INVALID, _UNKNOWN, _MISMATCH, _LIMIT})
_REASONS = frozenset({"JSON_SYNTAX", "DUPLICATE_KEY", "NON_OBJECT_ARGUMENTS",
    "NON_FINITE_NUMBER", "UNSAFE_INTEGER", "INVALID_TYPE", "INVALID_SHAPE",
    "IDENTITY_MISMATCH", "UNKNOWN_HISTORY", "MEMORY_LIMIT", "ARGUMENTS_TYPE",
    "MESSAGE_CONTENT_TYPE", "TOOL_CALLS_TYPE", "REASONING_TYPE", "OPAQUE_TYPE", "JSON_SYNTAX_REPAIR_LIMIT"})
_DEFAULT_REASONS = {_INVALID: "INVALID_SHAPE", _UNKNOWN: "UNKNOWN_HISTORY",
    _MISMATCH: "IDENTITY_MISMATCH", _LIMIT: "MEMORY_LIMIT"}
_DIAGNOSTIC_KEYS = frozenset({"phase", "reason", "code", "ordinal", "entry_count", "retained_bytes"})


class ThinkingError(ValueError):
    def __init__(self, code=_MISMATCH, *, reason=None):
        self.code = code if code in _CODES else _INVALID
        self.reason = reason if type(reason) is str and reason in _REASONS else _DEFAULT_REASONS[self.code]
        super().__init__(self.code)


ThinkingStateError = ThinkingError


def validated_thinking_diagnostics(value):
    """Only fixed categories and bounded counters may leave the RAM helper."""
    if (type(value) is not dict or set(value) != _DIAGNOSTIC_KEYS
            or type(value["phase"]) is not str or value["phase"] not in {"remember", "restore"}
            or type(value["reason"]) is not str or value["reason"] not in _REASONS
            or type(value["code"]) is not str or value["code"] not in _CODES
            or any(type(value[key]) is not int or not 0 <= value[key] <= limit
                   for key, limit in (("ordinal", 1000000), ("entry_count", 1000000),
                                      ("retained_bytes", MAX_MEMORY_BYTES)))):
        return None
    return dict(value)


def _need(condition, code=_INVALID, *, reason=None):
    if not condition:
        raise ThinkingError(code, reason=reason)


def _dump(value):
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError):
        raise ThinkingError(_INVALID, reason="INVALID_TYPE") from None


def _pairs(items):
    result = {}
    for key, value in items:
        _need(key not in result, reason="DUPLICATE_KEY")
        result[key] = value
    return result


def _constant(_value):
    raise ThinkingError(_INVALID, reason="NON_FINITE_NUMBER")


def _typed(value):
    """Match JSON values with JS number semantics and without bool/int aliasing."""
    if value is None:
        return ["null"]
    if type(value) is bool:
        return ["boolean", value]
    if type(value) is str:
        return ["string", value]
    if type(value) in {int, float}:
        _need(math.isfinite(value), reason="NON_FINITE_NUMBER")
        if isinstance(value, int) or value.is_integer():
            _need(abs(value) <= _SAFE_INTEGER, reason="UNSAFE_INTEGER")
        number = float(value)
        return ["number", (0.0 if number == 0 else number).hex()]
    if type(value) is list:
        return ["array", [_typed(item) for item in value]]
    _need(type(value) is dict and all(type(key) is str for key in value), reason="INVALID_TYPE")
    return ["object", [[key, _typed(value[key])] for key in sorted(value)]]


def _arguments(text):
    _need(type(text) is str, reason="ARGUMENTS_TYPE")
    try:
        value = json.loads(text, object_pairs_hook=_pairs, parse_constant=_constant)
        _need(type(value) is dict, reason="NON_OBJECT_ARGUMENTS")
        return _typed(value)
    except ThinkingError:
        raise
    except json.JSONDecodeError:
        raise ThinkingError(_INVALID, reason="JSON_SYNTAX") from None
    except (ValueError, TypeError, OverflowError, RecursionError):
        raise ThinkingError(_INVALID) from None


def _assistant(message, *, malformed=None):
    _need(type(message) is dict and message.get("role") == "assistant")
    content = message.get("content")
    _need(content is None or type(content) is str, reason="MESSAGE_CONTENT_TYPE")
    saved = {"role": "assistant", "content": content}
    original_calls = message.get("tool_calls", [])
    _need(original_calls is None or type(original_calls) is list, reason="TOOL_CALLS_TYPE")
    calls = original_calls or []
    identifiers, signatures, projected = [], [], []
    for call in calls:
        _need(type(call) is dict and call.get("type") == "function"
              and type(call.get("id")) is str and _NAME.fullmatch(call["id"]))
        function = call.get("function")
        _need(type(function) is dict and type(function.get("name")) is str
              and _NAME.fullmatch(function["name"]))
        identifier, name = call["id"], function["name"]
        _need(identifier not in identifiers, reason="IDENTITY_MISMATCH")
        arguments = function.get("arguments")
        try:
            identity = _arguments(arguments)
        except ThinkingError as error:
            # Only a known response may register unparseable argument bytes.
            # Empty input is excluded: this SDK parses raw || '{}' and could
            # execute it, instead of producing the native JSON-input failure.
            if malformed is None or error.reason != "JSON_SYNTAX" or not arguments:
                raise
            malformed[identifier] = arguments
            identity = ["invalid-json-exact-raw", arguments]
        signatures.append([identifier, name, identity])
        identifiers.append(identifier)
        projected.append({"id": identifier, "type": "function",
                          "function": {"name": name, "arguments": arguments}})
    if "tool_calls" in message:
        saved["tool_calls"] = None if original_calls is None else projected
    for key in ("reasoning_content", "encrypted_content"):
        value = message.get(key)
        _need(value is None or type(value) is str,
              reason="REASONING_TYPE" if key == "reasoning_content" else "OPAQUE_TYPE")
        if value is not None:
            saved[key] = value
    # The fixed SDK turns empty text into null when replaying a tool-call turn.
    # Nonempty text is always matched exactly; non-tool null/empty stay distinct.
    content_key = ["tool-empty"] if calls and content in {None, ""} else ["text", content]
    fingerprint = hashlib.sha256(_dump([content_key, signatures])).hexdigest()
    return saved, fingerprint, identifiers


def _native_json_error(arguments):
    """Pinned SDK 2.1.2 tool.input-json envelope, including JS UTF-16 slice."""
    encoded = arguments.encode("utf-16-le", errors="surrogatepass")
    excerpt = encoded[:4096].decode("utf-16-le", errors="surrogatepass")
    length, kept = len(encoded) // 2, len(excerpt.encode("utf-16-le", errors="surrogatepass")) // 2
    message = ("The tool input could not be parsed as JSON, so the call was not executed. "
        "Reissue the call with valid JSON arguments.")
    if length:
        message += "\n\nInput excerpt (first " + str(kept) + " of " + str(length) + " characters):\n" + excerpt
        if length > kept:
            message += "\n[truncated]"
    return {"error": {"type": "tool.input-json", "message": message}, "content": []}


def _native_json_rejections(messages, index, original, identifiers):
    """Accept the SDK's specific non-execution projection, never an ID alone."""
    following = []
    for message in messages[index + 1:]:
        if type(message) is not dict or message.get("role") != "tool":
            break
        following.append(message)
    for call in original["tool_calls"]:
        if call["id"] not in identifiers:
            continue
        matches = [item for item in following if item.get("tool_call_id") == call["id"]]
        _need(len(matches) == 1, _MISMATCH)
        item = matches[0]
        _need(set(item) == {"role", "tool_call_id", "content"} and type(item["content"]) is str, _MISMATCH)
        try:
            value = json.loads(item["content"], object_pairs_hook=_pairs, parse_constant=_constant)
        except (ValueError, TypeError, RecursionError):
            raise ThinkingError(_MISMATCH) from None
        _need(value == _native_json_error(call["function"]["arguments"]), _MISMATCH)


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
        self._malformed = {}
        self._bytes = _size((job_id, self._messages, self._ids, self._malformed))
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
        malformed = {}
        saved, key, identifiers = _assistant(message, malformed=malformed)
        body = _dump(saved)
        _need(len(body) <= self._max_bytes, _LIMIT)
        _need(all(self._ids.get(identifier, key) == key for identifier in identifiers), _MISMATCH)
        if key in self._messages:
            _need(self._messages[key] == body, _MISMATCH)
        else:
            messages, ids, projections = dict(self._messages), dict(self._ids), dict(self._malformed)
            if malformed:
                _need(len(projections) < MAX_MALFORMED_TURNS, reason="JSON_SYNTAX_REPAIR_LIMIT")
                projected = deepcopy(saved)
                for call in projected["tool_calls"]:
                    if call["id"] in malformed:
                        call["function"]["arguments"] = "{}"
                # This is only a replay identity. The raw argument string is
                # never parsed, repaired, or passed to a callable by Python.
                projected_key = _assistant(projected)[1]
                _need(projected_key not in projections, _MISMATCH)
                projections[projected_key] = (key, tuple(malformed))
            messages[key] = body
            ids.update((identifier, key) for identifier in identifiers)
            retained = _size((self._job_id, messages, ids, projections))
            _need(retained <= self._max_bytes, _LIMIT)
            self._messages, self._ids, self._malformed, self._bytes = messages, ids, projections, retained
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
            projection = self._malformed.get(key)
            if known is None and projection is not None:
                original_key, malformed_ids = projection
                # Valid siblings, the whole ordered group and content already
                # matched its fingerprint. Bad inputs must be this exact SDK
                # empty-object projection plus its adjacent native failure.
                _need(all(call["function"]["arguments"] == "{}" for call in message["tool_calls"]
                    if call["id"] in malformed_ids), _MISMATCH)
                known = self._messages[original_key]
                _native_json_rejections(result["messages"], index, json.loads(known), malformed_ids)
            if known is None:
                _need(not any(identifier in self._ids for identifier in identifiers), _MISMATCH)
                raise ThinkingError(_UNKNOWN)
            original = json.loads(known)
            if "encrypted_content" in message:
                _need(message["encrypted_content"] == original.get("encrypted_content"), _MISMATCH)
            result["messages"][index] = original
        return result
