"""Wire service detection utilities."""
from __future__ import annotations

import re

from datasketch import MinHash

# Wire service byline patterns (case-insensitive)
WIRE_SERVICE_PATTERNS = [
    r'\bAssociated Press\b',
    r'\bAP\b',
    r'\bReuters\b',
    r'\bAFP\b',
    r'\bAgence France[- ]Presse\b',
    r'\bUnited Press International\b',
    r'\bUPI\b',
    r'\bCanadian Press\b',
    r'\bThe Canadian Press\b',
    r'\bPress Association\b',
    r'\bPress Trust of India\b',
    r'\bPTI\b',
    r'\bIANS\b',
    r'\bANI\b',
    r'\bdpa\b',
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

_TOKEN_RE = re.compile(r"[A-Za-z0-9']+")

# Defaults for MinHash near-duplicate detection.
#
# - num_perm=128: Broder (1997, §4.2) recommends 100-200 samples for practical
#   applications. 128 gives ~1/sqrt(128) ≈ 8.8% standard error on the Jaccard
#   estimate, plenty for distinguishing near-duplicates from independent coverage.
#
# - shingle_size=5: Broder's AltaVista web-clustering experiment used w=7. We
#   use w=5 because news articles are shorter than typical web pages, so a
#   smaller window keeps more shingles per article. Either is defensible.
MINHASH_NUM_PERM = 128
MINHASH_SHINGLE_SIZE = 5


def is_wire_copy(author: str, source_uri: str) -> bool:
    """
    Determine if an article is a republished wire service story by byline.

    Returns True if the author byline matches a wire service pattern
    AND the source is NOT the wire service itself.
    """
    if not author:
        return False
    if source_uri and source_uri.lower() in WIRE_SERVICE_SOURCES:
        return False
    return bool(_WIRE_PATTERN.search(author))


def _word_shingles(content: str, shingle_size: int) -> set[str]:
    """Tokenize and return the set of overlapping word-level k-shingles."""
    tokens = _TOKEN_RE.findall(content.lower())
    if len(tokens) < shingle_size:
        return set()
    return {
        ' '.join(tokens[i:i + shingle_size])
        for i in range(len(tokens) - shingle_size + 1)
    }


def article_minhash(
    content: str,
    num_perm: int = MINHASH_NUM_PERM,
    shingle_size: int = MINHASH_SHINGLE_SIZE,
) -> MinHash | None:
    """
    Compute a MinHash signature over the article's word shingles.

    Two articles whose signatures have high Jaccard similarity are near-duplicates:
    the canonical fingerprint of wire-copy republication, robust to minor edits
    (a swapped word, fixed typo, light copy-edit) that defeat exact hashing.

    Returns None for content with fewer tokens than the shingle size.
    """
    if not content:
        return None
    shingles = _word_shingles(content, shingle_size)
    if not shingles:
        return None
    mh = MinHash(num_perm=num_perm)
    for shingle in shingles:
        mh.update(shingle.encode('utf-8'))
    return mh
