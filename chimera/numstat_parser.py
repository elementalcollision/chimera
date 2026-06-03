from typing import Tuple


def parse_numstat(line: str) -> Tuple[int, int, str]:
    """Parse a single line from 'git diff --numstat' output into (added, removed, path).

    - Counts may be digits or '-' (binary); '-' should be treated as 0.
    - The path is the remainder after the first two tab separators ("\t").
    """
    added_str, removed_str, path = line.rstrip("\n").split("\t", 2)

    def _to_int(s: str) -> int:
        return 0 if s == "-" else int(s)

    added = _to_int(added_str)
    removed = _to_int(removed_str)
    return added, removed, path
