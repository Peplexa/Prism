"""Wire service detection utilities."""
from __future__ import annotations

import re

# Wire service byline patterns (case-insensitive)
WIRE_SERVICE_PATTERNS = [
    r'\bAssociated Press\b',
    r'\bAP\b',
    r'\bReuters\b',
    r'\bAFP\b',
    r'\bAgence France[- ]Presse\b',
    r'\bUnited Press International\b',
    r'\bUPI\b',
]

# Source URIs that ARE wire services (originals, not copies)
WIRE_SERVICE_SOURCES = {
    'apnews.com',
    'reuters.com',
    'afp.com',
    'upi.com',
}

_WIRE_PATTERN = re.compile(
    '|'.join(WIRE_SERVICE_PATTERNS),
    re.IGNORECASE,
)


def is_wire_copy(author: str, source_uri: str) -> bool:
    """
    Determine if an article is a republished wire service story.

    Returns True if the author byline matches a wire service pattern
    AND the source is NOT the wire service itself.
    """
    if not author:
        return False
    if source_uri and source_uri.lower() in WIRE_SERVICE_SOURCES:
        return False
    return bool(_WIRE_PATTERN.search(author))
