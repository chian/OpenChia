"""Recognize a gateway's refusal of service delivered as an ordinary reply.

Some gateways answer a refused request with HTTP 200 and the refusal as the
assistant message. ANL's Argo, after a monthly quota is exhausted, returns
"⚠️ IMPORTANT USAGE NOTICE FROM ARGO … ACCESS REVOKED … Your Argo usage limit
has been exceeded. Reason: Monthly limit exceeded." (2026-10-09). Treated as a
model answer, such text became refiner input and produced a run of one-second
"successful" calls. A notice is never a result: callers fail the call instead.
"""

from __future__ import annotations

#: Lower-case markers of a refusal notice. One alone can appear in a genuine
#: answer (e.g. a model discussing quotas); a notice carries several.
NOTICE_MARKERS = (
    "notice from argo",
    "access revoked",
    "usage limit has been exceeded",
    "usage limit exceeded",
    "monthly limit exceeded",
    "quota exceeded",
    "contact your directorate operations officer",
)
#: Minimum distinct markers, and the longest reply still considered a notice.
MIN_MARKERS = 2
MAX_NOTICE_CHARS = 4000


class ProviderRefusedService(RuntimeError):
    """The provider answered with a refusal-of-service notice instead of a result."""


def provider_notice(text: str | None) -> str | None:
    """The normalized notice when *text* is a refusal of service, else ``None``."""
    if not text or len(text) > MAX_NOTICE_CHARS:
        return None
    lowered = text.lower()
    if sum(marker in lowered for marker in NOTICE_MARKERS) < MIN_MARKERS:
        return None
    return " ".join(text.split())[:300]


__all__ = ["NOTICE_MARKERS", "ProviderRefusedService", "provider_notice"]
