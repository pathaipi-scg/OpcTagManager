from datetime import datetime
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from services.shared_resources import SharedResourceError, SharedResourceStore
from services.tag_knowledge import TagIdentity


class SharedResourceStoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "Tags"
        self.store = SharedResourceStore(self.root, "Asia/Bangkok", True)
        self.identity = TagIdentity("LP2", "MIX", ["FAULT"], "Cement_FML", "LP2.MIX.FAULT.Cement_FML", "1", 5, 100, 1)
        self.index = {
            "schema_version": 1,
            "resource_id": "DOC_AS550_MANUAL",
            "resource_type": "Manuals",
            "display_name": "AS550 Inverter Manual",
            "manufacturer": "Delta",
            "model": "AS550",
            "part_no": "AS550-4T0055",
            "material_code": "1000123456",
            "active_version": 1,
            "active_file": "AS550_Manual_v1.pdf",
            "created_at": "2026-08-17T10:00:00+07:00",
            "updated_at": "2026-08-17T10:00:00+07:00",
            "versions": [{
                "version": 1,
                "filename": "AS550_Manual_v1.pdf",
                "sha256": "a" * 64,
                "created_at": "2026-08-17T10:00:00+07:00",
                "original_filename": "AS550 Manual.pdf",
            }],
        }

    def tearDown(self):
        self.temporary.cleanup()

    def test_resource_root_and_paths_remain_beneath_tag_root(self):
        self.store.resource_root.relative_to(self.root.resolve())
        path = self.store.directory_for_resource("Manuals", "DOC_AS550_MANUAL")
        path.relative_to(self.store.resource_root)
        with self.assertRaises(SharedResourceError):
            self.store.directory_for_resource("../Outside", "DOC_AS550_MANUAL")

    def test_resource_id_validation_and_generation(self):
        self.assertEqual(self.store.validate_resource_id("DOC_AS550_MANUAL"), "DOC_AS550_MANUAL")
        self.assertEqual(self.store.generate_resource_id("Manuals", "AS550 / Manual"), "MAN_AS550_MANUAL")
        for unsafe in ("..", "doc_lower", "DOC/ESCAPE", "C:\\external"):
            with self.subTest(unsafe=unsafe), self.assertRaises(SharedResourceError):
                self.store.validate_resource_id(unsafe)

    def test_invalid_windows_and_reserved_tag_names_are_encoded(self):
        identity = TagIdentity("CON", "MIX/A:B", [], "NUL", "CON.MIX/A:B.NUL", "1", 5, 100, 1)
        parts = self.store.references_path(identity).relative_to(self.root).parts
        self.assertEqual(parts, ("~R~CON", "~E~MIX~2FA~3AB", "~R~NUL", "references.json"))

    def test_resource_index_round_trip_and_list(self):
        self.store.write_index(self.index)
        self.assertEqual(self.store.read_index("DOC_AS550_MANUAL"), self.index)
        self.assertEqual(self.store.list_resources(), [self.index])

    def test_tag_references_round_trip_duplicate_rejection_and_unlink(self):
        self.store.write_index(self.index)
        linked = self.store.link(self.identity, "DOC_AS550_MANUAL", "Manual", datetime(2026, 8, 17, 11, 0, 0))
        self.assertEqual(linked["resources"][0]["resource_id"], "DOC_AS550_MANUAL")
        self.assertEqual(self.store.read_references(self.identity)["kepware_path"], self.identity.full_path)
        with self.assertRaisesRegex(SharedResourceError, "already linked"):
            self.store.link(self.identity, "DOC_AS550_MANUAL", "Manual")
        self.assertEqual(self.store.unlink(self.identity, "DOC_AS550_MANUAL")["resources"], [])
        with self.assertRaisesRegex(SharedResourceError, "not linked"):
            self.store.unlink(self.identity, "DOC_AS550_MANUAL")

    def test_atomic_replace_failure_preserves_existing_references(self):
        self.store.write_index(self.index)
        self.store.link(self.identity, "DOC_AS550_MANUAL", "Manual")
        path = self.store.references_path(self.identity)
        before = path.read_bytes()
        with patch("services.shared_resources.os.replace", side_effect=OSError("simulated")):
            with self.assertRaises(OSError):
                self.store.unlink(self.identity, "DOC_AS550_MANUAL")
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(list(path.parent.glob(".references.json.*.tmp")), [])

    def test_sha256_is_repeatable_for_file_and_stream_and_duplicate_lookup(self):
        sample = Path(self.temporary.name) / "sample.bin"
        sample.write_bytes(b"same resource bytes")
        first = self.store.sha256(sample)
        second = self.store.sha256(io.BytesIO(b"same resource bytes"))
        self.assertEqual(first, second)
        self.index["versions"][0]["sha256"] = first
        self.store.write_index(self.index)
        self.assertEqual(self.store.find_by_sha256(first)["resource_id"], "DOC_AS550_MANUAL")

    def test_write_gate_disabled_does_not_create_root(self):
        disabled_root = Path(self.temporary.name) / "DisabledTags"
        disabled = SharedResourceStore(disabled_root, "Asia/Bangkok", False)
        self.assertEqual(disabled.list_resources(), [])
        with self.assertRaisesRegex(SharedResourceError, "write mode is disabled"):
            disabled.write_index(self.index)
        with self.assertRaisesRegex(SharedResourceError, "write mode is disabled"):
            disabled.link(self.identity, "DOC_AS550_MANUAL", "Manual")
        self.assertFalse(disabled_root.exists())

    def test_index_rejects_external_or_nested_filenames(self):
        for filename in ("../manual.pdf", "C:\\external\\manual.pdf"):
            candidate = json.loads(json.dumps(self.index))
            candidate["active_file"] = filename
            candidate["versions"][0]["filename"] = filename
            with self.subTest(filename=filename), self.assertRaises(SharedResourceError):
                self.store.write_index(candidate)


if __name__ == "__main__":
    unittest.main()
