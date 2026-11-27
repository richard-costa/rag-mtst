import pytest

from app.collection import validate_collection_id


@pytest.mark.parametrize("collection_id", ["default", "Team A:1", "é-ü", "x" * 255])
def test_collection_ids_are_opaque_and_unchanged(collection_id) -> None:
    assert validate_collection_id(collection_id) == collection_id


@pytest.mark.parametrize(
    "collection_id", ["", "   ", " padded", "padded ", "a/b", "tab\tbed", "x" * 256]
)
def test_unusable_collection_ids_are_rejected(collection_id) -> None:
    with pytest.raises(ValueError):
        validate_collection_id(collection_id)
