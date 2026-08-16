from datetime import datetime
import json
from pathlib import Path
import tempfile
import unittest

from services.tag_knowledge import (
    TagIdentity,
    TagKnowledgeError,
    TagKnowledgeStore,
    encode_windows_component,
)


class TagKnowledgeStoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "Tags"
        self.store = TagKnowledgeStore(self.root, "Asia/Bangkok", True)
        self.identity = TagIdentity(
            channel="LP2_SIEMENS",
            device="PACKER",
            group_path=["FAULT"],
            tag_name="AK30_1_FUSE_TRIPPED",
            full_path="LP2_SIEMENS.PACKER.FAULT.AK30_1_FUSE_TRIPPED",
            address="DB1.X0",
            data_type=5,
            scan_rate=1000,
            access=1,
        )
        self.fields = {
            "description": "Fuse trip indication",
            "possible_cause": "Blown fuse",
            "how_to_check": "Isolate power and inspect",
            "corrective_action": "Replace with rated fuse",
            "safety_warning": "Follow lockout procedures",
            "additional_notes": "Escalate repeat failures",
        }

    def tearDown(self):
        self.temporary.cleanup()

    def test_first_and_second_save_are_versioned_and_old_file_is_preserved(self):
        moment = datetime(2026, 8, 16, 21, 35, 0)
        first = self.store.save(self.identity, self.fields, moment)
        second = self.store.save(self.identity, self.fields, moment)

        directory = self.store.directory_for(self.identity)
        self.assertEqual(first["version"], 1)
        self.assertEqual(second["version"], 2)
        self.assertNotEqual(first["active_file"], second["active_file"])
        self.assertTrue((directory / first["active_file"]).is_file())
        self.assertTrue((directory / second["active_file"]).is_file())
        index = json.loads((directory / "knowledge.index.json").read_text(encoding="utf-8"))
        self.assertEqual(index["active_version"], 2)
        self.assertEqual(index["active_filename"], second["active_file"])
        loaded = self.store.load(self.identity)
        self.assertEqual(loaded["fields"], self.fields)

    def test_markdown_contains_exact_identity_metadata_fields_and_timezone(self):
        result = self.store.save(self.identity, self.fields, datetime(2026, 8, 16, 21, 35, 0))
        content = (self.store.directory_for(self.identity) / result["active_file"]).read_text(encoding="utf-8")
        self.assertIn("CreatedAt: 2026-08-16T21:35:00+07:00", content)
        self.assertIn("KepwarePath: LP2_SIEMENS.PACKER.FAULT.AK30_1_FUSE_TRIPPED", content)
        self.assertIn('TagGroups: ["FAULT"]', content)
        self.assertIn("DataType: 5", content)
        self.assertIn("ScanRateMs: 1000", content)
        self.assertIn("## Safety / Warning\nFollow lockout procedures", content)

    def test_preview_timestamp_produces_the_same_filename_on_save(self):
        moment = datetime(2026, 8, 16, 21, 35, 0)
        preview = self.store.preview(self.identity, moment)
        saved = self.store.save(self.identity, self.fields, moment)
        self.assertEqual(saved["active_file"], preview["new_file"])
        self.assertEqual(saved["version"], preview["new_version"])

    def test_path_traversal_is_rejected_without_creating_root(self):
        unsafe = TagIdentity("LP2", "..", [], "Tag", "LP2...Tag", "1", 5, 100, 1)
        with self.assertRaises(TagKnowledgeError):
            self.store.save(unsafe, self.fields)
        self.assertFalse(self.root.exists())

    def test_invalid_and_reserved_windows_components_are_deterministically_encoded(self):
        self.assertEqual(encode_windows_component("Valid_Name"), "Valid_Name")
        self.assertEqual(encode_windows_component("FAULT/A:B"), "~E~FAULT~2FA~3AB")
        self.assertEqual(encode_windows_component("CON"), "~R~CON")
        identity = TagIdentity("CON", "Device", ["FAULT/A:B"], "Tag", "CON.Device.FAULT/A:B.Tag", "1", 5, 100, 1)
        directory = self.store.directory_for(identity)
        self.assertEqual(directory.relative_to(self.root).parts, ("~R~CON", "Device", "~E~FAULT~2FA~3AB", "Tag"))

    def test_write_disabled_reads_but_does_not_create_any_path(self):
        disabled = TagKnowledgeStore(self.root, "Asia/Bangkok", False)
        self.assertFalse(disabled.load(self.identity)["exists"])
        with self.assertRaisesRegex(TagKnowledgeError, "write mode is disabled"):
            disabled.save(self.identity, self.fields)
        self.assertFalse(self.root.exists())

    def test_all_written_files_remain_beneath_temporary_root(self):
        self.store.save(self.identity, self.fields)
        for path in self.root.rglob("*"):
            path.resolve().relative_to(self.root.resolve())


if __name__ == "__main__":
    unittest.main()
