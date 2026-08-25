from datetime import datetime
import json
from pathlib import Path
import tempfile
import unittest

from services.tag_knowledge import (
    MAX_IMAGE_BYTES,
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

    @staticmethod
    def png_bytes():
        return b"\x89PNG\r\n\x1a\n" + b"test-image"

    def upload(self, section="how_to_check", filename="sensor.png", content_type="image/png"):
        return self.store.store_attachment(
            self.identity, section, filename, content_type, self.png_bytes(),
            datetime(2026, 8, 25, 18, 15, 0),
        )

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

    def test_valid_image_upload_uses_generated_section_relative_path(self):
        attachment = self.upload()
        self.assertEqual(attachment["section"], "how_to_check")
        self.assertRegex(
            attachment["relative_path"],
            r"^attachments/how_to_check/how_to_check_20260825_181500_[0-9a-f]{8}\.png$",
        )
        stored = self.store.attachment_path(self.identity, attachment["relative_path"])
        self.assertEqual(stored.read_bytes(), self.png_bytes())

    def test_jpeg_and_webp_clipboard_style_names_use_the_existing_upload_contract(self):
        jpeg = self.store.store_attachment(
            self.identity, "description", "clipboard_20260825_181530.jpg", "image/jpeg",
            b"\xff\xd8\xff\xe0jpeg", datetime(2026, 8, 25, 18, 15, 30),
        )
        webp = self.store.store_attachment(
            self.identity, "safety_warning", "clipboard_20260825_181531.webp", "image/webp",
            b"RIFF\x08\x00\x00\x00WEBPdata", datetime(2026, 8, 25, 18, 15, 31),
        )
        self.assertEqual(jpeg["content_type"], "image/jpeg")
        self.assertTrue(jpeg["relative_path"].endswith(".jpg"))
        self.assertEqual(webp["content_type"], "image/webp")
        self.assertTrue(webp["relative_path"].endswith(".webp"))

    def test_unsupported_extension_mime_and_signature_are_rejected(self):
        with self.assertRaisesRegex(TagKnowledgeError, "Only PNG"):
            self.store.store_attachment(self.identity, "description", "payload.exe", "application/octet-stream", b"MZ")
        with self.assertRaisesRegex(TagKnowledgeError, "content type"):
            self.store.store_attachment(self.identity, "description", "image.png", "image/jpeg", self.png_bytes())
        with self.assertRaisesRegex(TagKnowledgeError, "not a valid"):
            self.store.store_attachment(self.identity, "description", "image.png", "image/png", b"not-png")
        with self.assertRaisesRegex(TagKnowledgeError, "10 MiB"):
            self.store.store_attachment(
                self.identity, "description", "image.png", "image/png", b"x" * (MAX_IMAGE_BYTES + 1)
            )

    def test_attachment_path_traversal_and_absolute_paths_are_rejected(self):
        for path in ("../outside.png", "/absolute.png", "attachments/how_to_check/../outside.png",
                     "attachments\\how_to_check\\outside.png"):
            with self.subTest(path=path), self.assertRaises(TagKnowledgeError):
                self.store.attachment_path(self.identity, path, require_exists=False)

    def test_multiple_images_are_kept_in_their_section_and_markdown_uses_relative_references(self):
        first = self.upload()
        second = self.upload(filename="second.png")
        first["caption"] = "Sensor location"
        attachments = self.store._empty_attachments()
        attachments["how_to_check"] = [first, second]
        saved = self.store.save(self.identity, self.fields, attachments=attachments)
        markdown = (self.store.directory_for(self.identity) / saved["active_file"]).read_text(encoding="utf-8")
        self.assertIn(f"![Sensor location]({first['relative_path']})", markdown)
        self.assertIn(f"![]({second['relative_path']})", markdown)
        self.assertNotIn(str(self.root), markdown)
        loaded = self.store.load(self.identity)
        self.assertEqual(len(loaded["attachments"]["how_to_check"]), 2)
        self.assertEqual(loaded["fields"], self.fields)

    def test_existing_text_only_markdown_loads_with_empty_attachment_lists(self):
        self.store.save(self.identity, self.fields)
        loaded = self.store.load(self.identity)
        self.assertEqual(loaded["fields"], self.fields)
        self.assertEqual(loaded["attachments"], self.store._empty_attachments())

    def test_preview_returns_images_in_the_correct_sections(self):
        attachment = self.upload(section="corrective_action")
        attachment["caption"] = "Replacement position"
        attachments = self.store._empty_attachments()
        attachments["corrective_action"] = [attachment]
        preview = self.store.preview(self.identity, fields=self.fields, attachments=attachments)
        self.assertEqual(preview["fields"], self.fields)
        self.assertEqual(preview["attachments"]["corrective_action"][0]["caption"], "Replacement position")
        self.assertEqual(preview["attachments"]["how_to_check"], [])

    def test_removing_reference_in_new_version_retains_file_and_old_version_reference(self):
        attachment = self.upload()
        attachments = self.store._empty_attachments()
        attachments["how_to_check"] = [attachment]
        first = self.store.save(self.identity, self.fields, attachments=attachments)
        stored = self.store.attachment_path(self.identity, attachment["relative_path"])
        second = self.store.save(self.identity, self.fields, attachments=self.store._empty_attachments())
        directory = self.store.directory_for(self.identity)
        self.assertTrue(stored.is_file())
        self.assertIn(attachment["relative_path"], (directory / first["active_file"]).read_text(encoding="utf-8"))
        self.assertNotIn(attachment["relative_path"], (directory / second["active_file"]).read_text(encoding="utf-8"))

    def test_legacy_save_without_attachment_field_preserves_active_references(self):
        attachment = self.upload()
        attachments = self.store._empty_attachments()
        attachments["how_to_check"] = [attachment]
        self.store.save(self.identity, self.fields, attachments=attachments)
        second = self.store.save(self.identity, {**self.fields, "description": "Updated text"})
        markdown = (self.store.directory_for(self.identity) / second["active_file"]).read_text(encoding="utf-8")
        self.assertIn(attachment["relative_path"], markdown)


if __name__ == "__main__":
    unittest.main()
