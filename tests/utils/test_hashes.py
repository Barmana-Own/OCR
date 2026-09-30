from ocr_platform.utils.hashes import deterministic_id, stable_hash


def test_stable_hash_and_deterministic_ids_are_repeatable() -> None:
    value = {"page": 1, "document": "doc-1", "text": "شماره ۱۲۳"}

    assert stable_hash(value) == stable_hash({"text": "شماره ۱۲۳", "document": "doc-1", "page": 1})
    assert deterministic_id("page", value) == deterministic_id("page", value)
    assert deterministic_id("page", value) != deterministic_id("region", value)
    assert deterministic_id("page", value).startswith("page-")
