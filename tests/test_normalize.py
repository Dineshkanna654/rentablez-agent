from rentablez.normalize import normalize_serial


def test_strips_leading_and_trailing_whitespace():
    assert normalize_serial("  ABC123  ") == "ABC123"


def test_collapses_internal_whitespace():
    assert normalize_serial("ABC    123") == "ABC 123"


def test_uppercases_hex_looking_strings():
    assert normalize_serial("abcdef1234") == "ABCDEF1234"
    assert normalize_serial("0xdeadbeef") == "0XDEADBEEF"


def test_preserves_case_of_non_hex_strings():
    assert normalize_serial("Samsung_9C3D1E") == "Samsung_9C3D1E"


def test_handles_none():
    assert normalize_serial(None) is None


def test_handles_empty_string():
    assert normalize_serial("") == ""


def test_handles_non_string():
    assert normalize_serial(12345) == "12345"
    assert normalize_serial(True) == "True"


def test_idempotent():
    s = "  abc   def  "
    assert normalize_serial(normalize_serial(s)) == normalize_serial(s)
