import pytest
from chimera.numstat_parser import parse_numstat


def test_parse_normal_line():
    assert parse_numstat("5\t1\tsrc/main.py") == (5, 1, "src/main.py")


def test_parse_binary_line():
    assert parse_numstat("-\t-\tbinary.bin") == (0, 0, "binary.bin")


def test_parse_zero_counts():
    assert parse_numstat("0\t0\tempty.txt") == (0, 0, "empty.txt")


def test_parse_path_with_spaces():
    assert parse_numstat("1\t2\tpath with spaces.txt") == (1, 2, "path with spaces.txt")


def test_parse_line_with_tabs_only_in_fields():
    # path does not contain tabs – standard git-numstat output
    assert parse_numstat("10\t5\tno-tabs-here") == (10, 5, "no-tabs-here")


def test_discriminating_against_naive_parsing():
    # A naive implementation that treats "-" as a missing value would raise
    # or produce wrong results; this test pins the correct handling.
    result = parse_numstat("-\t0\tmixed-binary.txt")
    assert result == (0, 0, "mixed-binary.txt")
    # If '-' were naively passed to int(), it would ValueError. Our
    # assertion ensures it is treated as 0.
