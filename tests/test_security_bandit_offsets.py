# ruff: noqa: E402
"""Pinned Bandit child offsets differ from surrounding parent context lines."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from security_bandit import validate_offsets
from security_sarif import Invalid


class Offsets(unittest.TestCase):
    def valid(self, source, context, line, first, last):
        validate_offsets(source.splitlines(keepends=True), context, line, first, last)

    def bad(self, *args):
        with self.assertRaises(Invalid):
            self.valid(*args)

    def test_string_child_inside_short_parent_edges(self):
        self.valid(b'x = {\n    "password": "synthetic-only-value",\n}\n', [1, 2, 3], 2, 4, 14)

    def test_multiline_child_end_before_parent_end(self):
        self.valid(b'x = [\n    """a\nend of synthetic string""",\n]\n', [1, 2, 3, 4], 2, 4, 26)

    def test_utf8_offsets_are_bytes(self):
        self.valid('x="é"\n'.encode(), [1], 1, 2, 6)

    def test_unknown_start_sentinel(self):
        self.valid(b"x=1\n", [1], 1, -1, 0)

    def test_unknown_end_sentinel(self):
        self.valid(b"x=1\n", [1], 1, 2, 0)

    def test_start_uses_issue_line_not_long_other_context(self):
        self.bad(b"long_context_name = (\n1\n)\n", [1, 2, 3], 2, 5, 0)

    def test_end_bound_ignores_earlier_context(self):
        self.bad(b"long_context_name = (\n1\n)\n", [1, 2, 3], 2, 0, 10)

    def test_end_beyond_all_possible_lines(self):
        self.bad(b"x=(\n  1\n)\n", [1, 2, 3], 2, 2, 4)

    def test_negative_start(self):
        self.bad(b"x=1\n", [1], 1, -2, 0)

    def test_negative_end(self):
        self.bad(b"x=1\n", [1], 1, 0, -1)

    def test_bool_start(self):
        self.bad(b"x=1\n", [1], 1, True, 1)

    def test_bool_end(self):
        self.bad(b"x=1\n", [1], 1, 0, True)

    def test_reversed_single_line(self):
        self.bad(b"x=1\n", [1], 1, 2, 1)

    def test_crlf_not_part_of_columns(self):
        self.bad(b"x=1\r\n", [1], 1, 0, 4)
