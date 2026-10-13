# ruff: noqa: E402
"""Pure disposable RECORD fixtures; no Bandit import or scanner execution."""

import base64
import csv
import hashlib
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from check_bandit import unfiltered_record_files
from security_source import bounded_regular


class RecordTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="record-inventory-fixture-")
        self.root = Path(self.temp.name) / "tool"
        self.site = self.root / "lib/python3.12/site-packages"
        self.metadata = self.site / "fixture-1.dist-info"
        self.metadata.mkdir(parents=True)
        self.record = self.metadata / "RECORD"
        self.name = "fixture-1.dist-info/RECORD"
        self.hash = (
            "sha256="
            + base64.urlsafe_b64encode(hashlib.sha256(b"x").digest()).rstrip(b"=").decode()
        )
        (self.site / "fixture.py").write_bytes(b"x")
        self.rows = [["fixture.py", self.hash, "1"], [self.name, "", ""]]
        owner = self

        class Dist:
            def locate_file(self, item):
                return owner.site / str(item)

            @property
            def files(self):
                return [row[0] for row in owner.rows if row and (owner.site / row[0]).exists()]

        self.dist = Dist()

    def tearDown(self):
        self.temp.cleanup()

    def write(self):
        out = io.StringIO()
        csv.writer(out).writerows(self.rows)
        self.record.write_text(out.getvalue())

    def parse(self):
        self.write()
        return unfiltered_record_files(self.dist, self.root)

    def reject(self):
        with self.assertRaises((ValueError, OSError)):
            self.parse()

    def test_valid_hash_and_size(self):
        rows = self.parse()
        self.assertEqual(rows[0].hash.mode, "sha256")
        self.assertEqual(rows[0].size, 1)

    def test_missing_declared_module_survives_metadata_filter(self):
        (self.site / "fixture.py").unlink()
        rows = self.parse()
        self.assertIn("fixture.py", list(map(str, rows)))
        with self.assertRaises(FileNotFoundError):
            bounded_regular(self.root, "lib/python3.12/site-packages/fixture.py")

    def test_missing_manpage_survives_metadata_filter(self):
        self.rows.append(["../../../share/man/man1/bandit.1", self.hash, "1"])
        self.assertIn("../../../share/man/man1/bandit.1", list(map(str, self.parse())))

    def test_unused_console_record_remains_explicit(self):
        self.rows.append(["../../../bin/bandit", self.hash, "1"])
        self.assertIn("../../../bin/bandit", list(map(str, self.parse())))

    def test_console_parent_refused(self):
        self.rows.append(["../../../bin/..", self.hash, "1"])
        self.reject()

    def test_console_dot_refused(self):
        self.rows.append(["../../../bin/.", self.hash, "1"])
        self.reject()

    def test_duplicate_row_refused(self):
        self.rows.append(self.rows[0])
        self.reject()

    def test_empty_row_refused(self):
        self.rows.append([])
        self.reject()

    def test_two_fields_refused(self):
        self.rows[0] = self.rows[0][:2]
        self.reject()

    def test_four_fields_refused(self):
        self.rows[0].append("extra")
        self.reject()

    def test_missing_self_record_refused(self):
        self.rows = self.rows[:1]
        self.reject()

    def test_missing_all_metadata_refused(self):
        self.rows = []
        self.reject()

    def test_unhashed_module_refused(self):
        self.rows[0][1:] = ["", ""]
        self.reject()

    def test_unhashed_installer_allowed(self):
        self.rows.append(["fixture-1.dist-info/INSTALLER", "", ""])
        self.assertEqual(len(self.parse()), 3)

    def test_other_directory_unhashed_installer_refused(self):
        self.rows.append(["other/INSTALLER", "", ""])
        self.reject()

    def test_hash_algorithm_refused(self):
        self.rows[0][1] = self.hash.replace("sha256", "sha1")
        self.reject()

    def test_padded_hash_refused(self):
        self.rows[0][1] += "="
        self.reject()

    def test_noncanonical_base64_refused(self):
        self.rows[0][1] = "sha256=" + "A" * 42 + "B"
        self.reject()

    def test_missing_size_refused(self):
        self.rows[0][2] = ""
        self.reject()

    def test_negative_size_refused(self):
        self.rows[0][2] = "-1"
        self.reject()

    def test_noncanonical_size_refused(self):
        self.rows[0][2] = "01"
        self.reject()

    def test_hashed_record_refused(self):
        self.rows[1][1:] = [self.hash, "1"]
        self.reject()

    def test_absolute_path_refused(self):
        self.rows.append(["/absolute", self.hash, "1"])
        self.reject()

    def test_internal_alias_refused(self):
        self.rows.append(["pkg/../fixture.py", self.hash, "1"])
        self.reject()

    def test_unknown_external_record_refused(self):
        self.rows.append(["../../../share/other", self.hash, "1"])
        self.reject()

    def test_nested_console_path_refused(self):
        self.rows.append(["../../../bin/sub/tool", self.hash, "1"])
        self.reject()

    def test_newline_path_refused(self):
        self.rows.append(["bad\nname.py", self.hash, "1"])
        self.reject()

    def test_multiple_visible_records_refused(self):
        second = self.site / "other-1.dist-info"
        second.mkdir()
        (second / "RECORD").write_text("fixture")
        self.rows.append(["other-1.dist-info/RECORD", "", ""])
        self.reject()

    def test_record_symlink_refused(self):
        self.write()
        target = self.metadata / "target"
        self.record.rename(target)
        self.record.symlink_to(target)
        with self.assertRaises((ValueError, OSError)):
            unfiltered_record_files(self.dist, self.root)

    def test_record_hardlink_refused(self):
        self.write()
        os.link(self.record, self.metadata / "alias")
        with self.assertRaises((ValueError, OSError)):
            unfiltered_record_files(self.dist, self.root)

    def test_record_parent_symlink_refused(self):
        self.write()
        target = self.site / "moved"
        self.metadata.rename(target)
        self.metadata.symlink_to(target, target_is_directory=True)
        with self.assertRaises((ValueError, OSError)):
            unfiltered_record_files(self.dist, self.root)
