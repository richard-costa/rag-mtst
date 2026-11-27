"""Collection identifiers that scope indexed sources and conversations."""

from __future__ import annotations

DEFAULT_COLLECTION = "default"
MAX_COLLECTION_ID_LENGTH = 255


def validate_collection_id(collection_id: str) -> str:
    """Check that a collection identifier is a usable opaque value.

    Collections select data; they are not proof of permission. Identifiers are
    case-sensitive and never normalized, so surrounding whitespace, slashes
    (which cannot round-trip through HTTP paths) and control characters are
    rejected instead of silently altered.

    Args:
        collection_id: Caller-supplied collection identifier.

    Returns:
        The unchanged identifier.

    Raises:
        ValueError: The identifier is empty, too long, or contains unsupported characters.
    """

    if not isinstance(collection_id, str) or not collection_id.strip():
        raise ValueError("A nonempty collection identifier is required")

    if len(collection_id) > MAX_COLLECTION_ID_LENGTH:
        raise ValueError(
            f"Collection identifiers must be at most {MAX_COLLECTION_ID_LENGTH} characters"
        )

    if (
        collection_id != collection_id.strip()
        or "/" in collection_id
        or not collection_id.isprintable()
    ):
        raise ValueError(
            "Collection identifiers must not contain slashes, control characters, "
            "or leading/trailing whitespace"
        )

    return collection_id
