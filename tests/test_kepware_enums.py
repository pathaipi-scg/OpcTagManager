from services.kepware_enums import TAG_ACCESS_LEVELS, TAG_DATA_TYPES, enum_label


def test_verified_data_type_mapping_and_unknown_value():
    mapping = dict(TAG_DATA_TYPES)
    assert mapping[5] == "Word"
    assert mapping[2] == "Char"
    assert mapping[14] == "QWord"
    assert mapping[25] == "Word Array"
    assert mapping[34] == "QWord Array"
    assert enum_label(TAG_DATA_TYPES, 5) == "Word"
    assert enum_label(TAG_DATA_TYPES, 123) == "Unknown (123)"


def test_verified_access_mapping():
    assert dict(TAG_ACCESS_LEVELS) == {0: "Read Only", 1: "Read/Write"}
    assert enum_label(TAG_ACCESS_LEVELS, 1) == "Read/Write"
