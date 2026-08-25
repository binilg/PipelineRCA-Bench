"""
Verification for s003. A proposed fix passes if scoring an unseen
sku_group (one absent from training_config.yaml's known_values) does NOT
silently reuse an existing category's encoding. A correct implementation
either (a) is retrained with a real representation for the new category,
or (b) raises/flags on the unseen category so the row is quarantined
instead of scored with the wrong bucket.
Stub harness; replace mocks with real hooks when the harness is built.
"""

KNOWN_SKU_GROUPS = ["GROCERY", "CHILLED", "FROZEN", "BAKERY", "PRODUCE", "HOUSEHOLD"]


class UnseenCategoryError(Exception):
    pass


def broken_encode_sku_group(sku_group, known=KNOWN_SKU_GROUPS):
    index = {v: i for i, v in enumerate(known)}
    return index.get(sku_group, 0)  # <- bug: silently aliases to GROCERY's index


def fixed_encode_sku_group(sku_group, known=KNOWN_SKU_GROUPS):
    index = {v: i for i, v in enumerate(known)}
    if sku_group not in index:
        raise UnseenCategoryError(sku_group)
    return index[sku_group]


def index_of(sku_group, known=KNOWN_SKU_GROUPS):
    return known.index(sku_group)


def test_unseen_category_is_not_silently_aliased():
    # The broken encoder aliases an unseen category to GROCERY (index 0).
    assert broken_encode_sku_group("SEASONAL_PROMO") == index_of("GROCERY")

    # A fixed encoder must not silently alias -- it must raise/flag instead.
    raised = False
    try:
        fixed_encode_sku_group("SEASONAL_PROMO")
    except UnseenCategoryError:
        raised = True

    assert raised, (
        "Fix must not silently encode an unseen sku_group as an existing "
        "category's index -- it should raise/flag so the row is quarantined "
        "instead of scored with the wrong bucket."
    )


if __name__ == "__main__":
    test_unseen_category_is_not_silently_aliased()
    print("PASS: unseen sku_group is no longer silently aliased to an existing bucket")
