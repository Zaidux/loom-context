"""Token accounting.

Real tokenisers disagree, so the project ships two counters:

* :func:`estimate_tokens` - dependency-free heuristic, always available.
* :func:`count_tokens`   - tiktoken when installed, with a graceful fallback.

The benchmark reports the counter used, because "40% fewer tokens" is
meaningless without naming the tokeniser.
"""

from __future__ import annotations

import math
from functools import lru_cache

DEFAULT_ENCODING = "o200k_base"

_ENCODERS: dict[str, object | None] = {}


def _encoder(name: str):
    if name in _ENCODERS:
        return _ENCODERS[name]
    try:  # pragma: no cover - depends on install/network
        import tiktoken

        try:
            enc = tiktoken.get_encoding(name)
        except Exception:
            enc = tiktoken.get_encoding("cl100k_base")
    except Exception:
        enc = None
    _ENCODERS[name] = enc
    return enc


def estimate_tokens(text: str) -> int:
    """Cheap, stable estimate that never needs a download.

    Roughly 4 ASCII characters per token, but CJK and code punctuation are
    denser, so they are charged separately. This is only used when tiktoken
    cannot be loaded and for internal budget decisions.
    """
    if not text:
        return 0
    ascii_chars = 0
    wide_chars = 0
    for ch in text:
        if ord(ch) < 128:
            ascii_chars += 1
        else:
            wide_chars += 1
    # ~4.0 chars/token for prose, ~3.2 for dense syntax is a reasonable blend
    return max(1, math.ceil(ascii_chars / 3.8 + wide_chars / 1.6))


@lru_cache(maxsize=4096)
def count_tokens(text: str, encoding: str = DEFAULT_ENCODING) -> int:
    """Count tokens with tiktoken, falling back to the estimator."""
    enc = _encoder(encoding)
    if enc is None:
        return estimate_tokens(text)
    return len(enc.encode(text))


def tokenizer_name(encoding: str = DEFAULT_ENCODING) -> str:
    return encoding if _encoder(encoding) is not None else "estimate(3.8c/tok)"
