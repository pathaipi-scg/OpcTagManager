import asyncio
import inspect
import json
import io
from pathlib import Path
import tempfile
import unittest
from urllib.parse import urlsplit
from unittest.mock import AsyncMock, MagicMock, patch

import OpcTagManager
from starlette.datastructures import Headers, UploadFile
from services.kepware_config_api import KepwareConfigError
from services.tag_knowledge import TagIdentity
from services.shared_resources import SharedResourceStore
from services.supplier_profiles import SupplierProfileStore
from services.equipment_parts import EquipmentPartStore
from services.resource_relationships import ResourceRelationshipStore
from services.tag_reconcile import ReconcileResult
from services.tag_fast_sync import FastSyncError, FastSyncResult


class FakeCursor:
    def execute(self, _query, _parameters):
        return None

    def fetchall(self):
        return [(17, "SERVER/DEVICE/Tag", 5)]


class FakeConnection:
    def cursor(self):
        return FakeCursor()

    def close(self):
        return None


class OpcTagManagerAppTests(unittest.TestCase):
    @staticmethod
    def request(method, path, body=None):
        target = urlsplit(path)
        messages = []
        request_body = json.dumps(body).encode() if body is not None else b""
        received = False

        async def receive():
            nonlocal received
            if received:
                return {"type": "http.disconnect"}
            received = True
            return {"type": "http.request", "body": request_body, "more_body": False}

        async def send(message):
            messages.append(message)

        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": method,
            "scheme": "http",
            "path": target.path,
            "raw_path": target.path.encode(),
            "query_string": target.query.encode(),
            "root_path": "",
            "headers": (
                [(b"content-type", b"application/json")] if body is not None else []
            ),
            "client": ("testclient", 50000),
            "server": ("testserver", 80),
        }
        asyncio.run(OpcTagManager.app(scope, receive, send))
        status = next(message["status"] for message in messages if message["type"] == "http.response.start")
        content = b"".join(
            message.get("body", b"")
            for message in messages
            if message["type"] == "http.response.body"
        )
        return status, content

    @patch.object(OpcTagManager, "ALARM_WRITE_ENABLED", True)
    @patch.object(OpcTagManager.alarm_service, "delete")
    def test_delete_route_uses_exact_alarm_id_and_returns_reload_result(self, delete):
        delete.return_value = {
            "mapping_saved": True,
            "mapping_deleted": True,
            "deleted_alarm_id": 4,
            "reload_notified": True,
            "reload_error": None,
        }
        status, body = self.request("DELETE", "/api/alarms/4")
        payload = json.loads(body)
        self.assertEqual(status, 200)
        self.assertTrue(payload["success"])
        self.assertEqual(payload["deleted_alarm_id"], 4)
        self.assertTrue(payload["reload_notified"])
        delete.assert_called_once_with(4)

    @patch.object(OpcTagManager, "ALARM_WRITE_ENABLED", False)
    @patch.object(OpcTagManager.alarm_service, "delete")
    def test_delete_route_reports_disabled_alarm_write_gate(self, delete):
        delete.side_effect = OpcTagManager.AlarmServiceError("Alarm configuration write mode is disabled.")
        status, body = self.request("DELETE", "/api/alarms/3")
        payload = json.loads(body)
        self.assertEqual(status, 403)
        self.assertFalse(payload["success"])
        self.assertIn("write mode is disabled", payload["error"])
        delete.assert_called_once_with(3)

    @patch.object(OpcTagManager, "KM_RESOURCE_WRITE_ENABLED", False)
    @patch.object(OpcTagManager, "KM_TAG_WRITE_ENABLED", False)
    @patch.object(OpcTagManager, "KEPWARE_CONFIG_WRITE_ENABLED", False)
    @patch.object(OpcTagManager, "get_conn", return_value=FakeConnection())
    def test_home_and_static_assets_render_without_external_services(self, _get_conn):
        status, body = self.request("GET", "/")
        html = body.decode()
        self.assertEqual(status, 200)
        self.assertIn('id="new-tag-data-type"', html)
        self.assertIn('id="new-tag-scan-rate"', html)
        self.assertIn('id="new-tag-access"', html)
        self.assertIn('id="use-tag-template"', html)
        self.assertIn('id="tag-knowledge-panel"', html)
        self.assertEqual(html.count('class="knowledge-attach-button"'), 6)
        self.assertEqual(html.count('class="knowledge-image-input hidden"'), 6)
        self.assertEqual(html.count('paste a screenshot with Ctrl+V'), 6)
        self.assertIn('accept=".png,.jpg,.jpeg,.webp,image/png,image/jpeg,image/webp"', html)
        self.assertIn('id="tag-resources-panel"', html)
        self.assertEqual(html.count('id="tag-knowledge-panel"'), 1)
        self.assertEqual(html.count('id="tag-resources-panel"'), 1)
        self.assertIn('id="runtime-knowledge-host"', html)
        self.assertLess(html.index('id="alarm-panel"'), html.index('id="runtime-knowledge-host"'))
        self.assertLess(html.index('id="runtime-knowledge-host"'), html.index('id="kepware-details-view"'))
        self.assertIn('data-alarm-filter="alarm"', html)
        self.assertIn('id="alarm-panel"', html)
        self.assertIn('id="use-tag-as-alarm"', html)
        self.assertIn('id="preview-alarm-mp3"', html)
        self.assertIn('Legacy CHANGE mappings remain readable', html)
        self.assertIn('id="alarm-summary"', html)
        self.assertNotIn('id="alarm-mp3-search"', html)
        self.assertIn('id="alarm-mp3-warning"', html)
        self.assertIn('id="production-alarm-owner">legacy_alarm_system', html)
        self.assertIn('<summary>Advanced / Diagnostics</summary>', html)
        self.assertIn('id="alarm-capability">development_ready', html)
        self.assertIn('id="development-historian-runtime"', html)
        self.assertIn('id="production-historian-owner"', html)
        self.assertIn('id="operator-opc-state"', html)
        self.assertIn('id="operator-historian-state"', html)
        self.assertIn('id="operator-tag-count"', html)
        self.assertIn('id="operator-last-error"', html)
        self.assertIn('<strong>Current Alarm Mapping</strong>', html)
        self.assertNotIn('id="runtime-mp3-panel"', html)
        self.assertIn('id="alarm-center-splitter"', html)
        self.assertIn('id="alarm-horizontal-splitter"', html)
        self.assertIn('id="opc-tag-list-workspace" class="alarm-top-workspace"', html)
        self.assertIn('id="tag-configuration-workspace" class="tag-configuration-workspace hidden"', html)
        self.assertIn('aria-orientation="horizontal"', html)
        self.assertIn('aria-label="Resize OPC Tag List and Tag Details"', html)
        self.assertNotIn('class="alarm-mp3-list" role="listbox"', html)
        self.assertIn('<select id="alarm-selected-mp3">', html)
        self.assertIn('- Sound not selected -', html)
        self.assertNotIn('id="selected-tag-id"', html)
        self.assertNotIn('id="selected-tag-data-type"', html)
        self.assertIn('<thead><tr><th>Tag Name / Tag Path</th></tr></thead>', html)
        self.assertNotIn('<th>MP3 File</th>', html)
        self.assertNotIn('<th>Actions</th>', html)
        self.assertIn('id="test-alarm"', html)
        self.assertNotIn('<th>Enabled</th>', html)
        self.assertLess(html.index('id="runtime-tree-view"'), html.index('id="alarm-summary"'))
        self.assertLess(html.index('id="alarm-summary"'), html.index('id="runtime-details-view"'))
        self.assertIn('id="runtime-kepware-tree-host"', html)
        self.assertIn("All Tags browses the live Kepware hierarchy", html)
        self.assertNotIn('class="tag-name tag-click"', html)
        self.assertIn('<html lang="en" data-theme="dark">', html)
        self.assertIn('id="theme-toggle"', html)
        self.assertIn('opcTagManagerTheme', html)
        self.assertIn('saved === "light" || saved === "dark" ? saved : "dark"', html)
        self.assertIn('data-km-write-enabled="false"', html)
        self.assertIn('data-km-resource-write-enabled="false"', html)
        self.assertIn('class="view-tab active" data-view="runtime">OPC Tag List</button>', html)
        self.assertIn('class="view-tab" data-view="kepware">Tag Configuration</button>', html)
        self.assertLess(html.index(">OPC Tag List</button>"), html.index(">Tag Configuration</button>"))
        self.assertIn('<h2>Tag Configuration Tree</h2>', html)
        self.assertIn('<h2>OPC Tag List</h2>', html)
        self.assertIn('id="full-reconcile"', html)
        self.assertNotIn("Production subscriber ownership has not moved yet.", html)
        self.assertIn("Development Historian Runtime", html)
        self.assertIn("Production Historian Owner", html)
        self.assertIn("Refresh Configuration", html)
        self.assertIn('<select id="new-tag-data-type"', html)
        self.assertIn('<option value="5">Word</option>', html)
        self.assertIn('<option value="25">Word Array</option>', html)
        self.assertIn('<select id="new-tag-access"', html)
        self.assertIn('<option value="1">Read/Write</option>', html)
        self.assertIn('class="view-tab" data-view="opc-runtime">OPC Runtime</button>', html)
        self.assertIn('id="opc-runtime-workspace" class="opc-runtime-workspace hidden"', html)
        self.assertIn('id="subscription-activity-list"', html)
        self.assertIn('id="influx-activity-list"', html)
        self.assertIn('id="alarm-activity-list"', html)
        javascript = Path("static/app.js").read_text(encoding="utf-8")
        self.assertIn('document.querySelector(\'.view-tab[data-view="runtime"]\').click();', javascript)
        self.assertIn('Number(document.getElementById("new-tag-data-type").value)', javascript)
        self.assertIn('selectEnumValue("new-tag-data-type", templateTag?.tag_details?.data_type', javascript)
        self.assertIn('friendlyEnumValue("new-tag-data-type", dataType)', javascript)
        self.assertIn('friendlyEnumValue("new-tag-access", access)', javascript)
        self.assertIn("Kepware Tag Created ✅", javascript)
        self.assertIn("Runtime Registry Sync", javascript)
        self.assertIn("Historian Subscription Sync", javascript)
        self.assertIn('`Unknown (${value})`', javascript)
        self.assertIn('value === "dark" || value === "light" ? value : "dark"', javascript)
        self.assertIn('localStorage.setItem(themeStorageKey, safeTheme)', javascript)
        self.assertIn('applyTheme(document.documentElement.dataset.theme)', javascript)
        self.assertLess(javascript.index('applyTheme(document.documentElement.dataset.theme)'), javascript.index('document.querySelector(\'.view-tab[data-view="runtime"]\').click();'))
        self.assertIn("runtimeKepwareTreeHost", javascript)
        self.assertIn('appendChild(kepwareTree)', javascript)
        self.assertIn('fetch(`/api/opc-tags/resolve/by-path?path=', javascript)
        self.assertIn('...(node.context.group_path || [])', javascript)
        self.assertIn('.join("/")', javascript)
        self.assertIn('if (!alarmId && !selectedRuntimeTag.tagId)', javascript)
        self.assertIn('confirm: "SYNC_ONE_EXISTING_TAG"', javascript)
        self.assertIn('payload.tag_id = selectedRuntimeTag.tagId', javascript)
        self.assertIn('fetchWithTimeout("/api/runtime/status")', javascript)
        self.assertIn('controller.abort()', javascript)
        self.assertIn('loadAlarmMp3();', javascript)
        self.assertIn('document.getElementById("alarm-selected-mp3").value', javascript)
        self.assertIn('fetch("/api/alarm-mp3")', javascript)
        self.assertIn('document.createElement("option")', javascript)
        self.assertIn('row.addEventListener("click", () => selectMappedAlarm(alarm))', javascript)
        self.assertIn('row.classList.toggle("selected-mapping"', javascript)
        self.assertIn('loadOperationalTagContext(knowledgeNodeFromAlarm(alarm))', javascript)
        self.assertIn('loadOperationalTagContext(node);', javascript)
        self.assertIn('button.dataset.canonicalPath === selectedRuntimeTag?.path', javascript)
        self.assertIn('runtimeKnowledgeHost.append(', javascript)
        self.assertIn('document.getElementById("tag-knowledge-panel")', javascript)
        self.assertIn('fetch("/api/tag-knowledge/attachments", { method: "POST", body: form })', javascript)
        self.assertIn('knowledgeAttachmentReadUrl(attachment)', javascript)
        self.assertIn('knowledge-preview-images', javascript)
        self.assertIn('attachments: knowledgeAttachments', javascript)
        self.assertIn('textarea.addEventListener("paste", async (event)', javascript)
        self.assertIn('event.clipboardData?.items', javascript)
        self.assertIn('item.kind === "file" && item.type.startsWith("image/")', javascript)
        self.assertIn('if (!imageItem) return', javascript)
        self.assertIn('event.preventDefault()', javascript)
        self.assertIn('insertClipboardText(textarea, event.clipboardData.getData("text/plain"))', javascript)
        self.assertIn('await uploadKnowledgeImages(section, [file])', javascript)
        self.assertIn('`clipboard_${timestamp}${extension}`', javascript)
        self.assertIn('"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"', javascript)
        self.assertIn('}[blob.type] || ".bin"', javascript)
        self.assertIn('document.getElementById("tag-resources-panel")', javascript)
        configuration_selection = javascript[javascript.index("function selectKepwareObject"):javascript.index("function displayKepwareObject")]
        self.assertNotIn("loadTagKnowledge", configuration_selection)
        self.assertNotIn("loadTagResources", configuration_selection)
        alarm_submit_start = javascript.index('document.getElementById("alarm-form").addEventListener("submit"')
        alarm_submit = javascript[alarm_submit_start:javascript.index('document.getElementById("delete-alarm")', alarm_submit_start)]
        self.assertNotIn("knowledgeFieldsPayload", alarm_submit)
        knowledge_submit = javascript[javascript.index('document.getElementById("tag-knowledge-form").addEventListener("submit"'):javascript.index('document.getElementById("cancel-knowledge-save")')]
        self.assertNotIn("/api/alarms", knowledge_submit)
        summary_render = javascript[javascript.index("async function loadAlarmSummary"):javascript.index("document.querySelectorAll(\".alarm-filter-button\")")]
        self.assertNotIn('edit.textContent = "Edit"', summary_render)
        self.assertNotIn('remove.textContent = "Delete"', summary_render)
        self.assertNotIn('test.textContent = "Test"', summary_render)
        self.assertIn('document.getElementById("test-alarm").addEventListener("click"', javascript)
        self.assertIn('previewAlarmMp3(selectedMp3)', javascript)
        self.assertIn('fetch(`/api/alarms/${encodeURIComponent(alarmId)}`, { method: "DELETE" })', javascript)
        self.assertNotIn('document.getElementById("delete-alarm").click()', javascript)
        self.assertIn('await loadAlarmSummary()', javascript)
        self.assertIn('selectedMp3 = ""', javascript)
        self.assertIn('Mapping Delete        Failed', javascript)
        self.assertIn('runtimeSecondaryHost.append(operatorHealth, diagnosticsPanel)', javascript)
        self.assertIn('opcTagManager.alarmPane.leftWidth', javascript)
        self.assertIn('opcTagManager.alarmPane.centerWidth', javascript)
        self.assertIn('opcTagManager.alarmPane.topHeight', javascript)
        self.assertIn('alarmMinimumWidths = { left: 260, center: 240, right: 320 }', javascript)
        self.assertIn('localStorage.setItem(alarmLeftWidthKey', javascript)
        self.assertIn('localStorage.removeItem(alarmLeftWidthKey)', javascript)
        self.assertIn('localStorage.removeItem(alarmCenterWidthKey)', javascript)
        self.assertIn('applyAlarmPaneWidths(true)', javascript)
        self.assertIn('bindAlarmPaneSplitter(alarmCenterSplitter, "center")', javascript)
        self.assertIn('if (splitter.dataset.alarmResizeBound === "true") return', javascript)
        self.assertIn('splitter.setPointerCapture?.(event.pointerId)', javascript)
        self.assertIn('splitter.addEventListener("pointermove", onPointerMove)', javascript)
        self.assertIn('splitter.addEventListener("pointercancel", finishResize)', javascript)
        self.assertIn('splitter.releasePointerCapture(finishEvent.pointerId)', javascript)
        self.assertIn('alarmMinimumHeights = { top: 280, mapping: 160 }', javascript)
        self.assertIn('alarmHorizontalSplitter.addEventListener("pointerdown", beginAlarmHorizontalResize)', javascript)
        self.assertIn('alarmHorizontalSplitter.setPointerCapture?.(event.pointerId)', javascript)
        self.assertIn('alarmHorizontalSplitter.addEventListener("pointermove", onPointerMove)', javascript)
        self.assertIn('alarmHorizontalSplitter.addEventListener("pointercancel", finishResize)', javascript)
        self.assertIn('localStorage.setItem(alarmTopHeightKey', javascript)
        self.assertIn('localStorage.removeItem(alarmTopHeightKey)', javascript)
        self.assertIn('applyAlarmTopHeight(true)', javascript)
        self.assertIn('alarmUpperWorkspace.style.height = `${topHeight}px`', javascript)
        self.assertIn('alarmUpperWorkspace.style.removeProperty("height")', javascript)
        self.assertNotIn('alarmTopWorkspace.style.height = `${topHeight}px`', javascript)
        self.assertNotIn('workspace.style.height = `${topHeight}px`', javascript)
        self.assertIn('(isKepware ? tagConfigurationWorkspace : alarmTopWorkspace).appendChild(workspace)', javascript)
        self.assertIn('alarmTopWorkspace.classList.toggle("hidden", isKepware || isOpcRuntime)', javascript)
        self.assertIn('opcRuntimeWorkspace.classList.toggle("hidden", !isOpcRuntime)', javascript)
        self.assertIn('startOpcRuntimePolling()', javascript)
        self.assertIn('stopOpcRuntimePolling()', javascript)
        self.assertIn('fetchWithTimeout("/api/runtime/activity")', javascript)
        self.assertIn('tagConfigurationWorkspace.classList.toggle("hidden", !isKepware)', javascript)
        self.assertIn('Math.max(alarmMinimumHeights.top', javascript)
        self.assertIn('total - alarmMinimumHeights.mapping', javascript)
        self.assertIn('workspace.style.setProperty("--alarm-left-width", `${left}px`)', javascript)
        self.assertIn('workspace.style.setProperty("--alarm-center-width", `${center}px`)', javascript)
        self.assertIn('Math.max(alarmMinimumWidths.left', javascript)
        self.assertIn('startLeft + startRight - alarmMinimumWidths.right', javascript)
        self.assertIn('usedAlarmMp3 = new Map()', javascript)
        self.assertIn('alarmIds.add(Number(alarm.alarm_id))', javascript)
        self.assertIn('usedByAnotherAlarm = [...usedByAlarmIds].some', javascript)
        self.assertIn('row.disabled = usedByAnotherAlarm', javascript)
        self.assertIn('`${file.filename} - already used by an alarm`', javascript)
        self.assertIn('const currentAlarmId = Number(selectedAlarm?.alarm_id || 0)', javascript)
        self.assertIn('loadedTag.classList.add("selected-object")', javascript)
        self.assertGreaterEqual(javascript.count('await loadAlarmSummary();'), 2)
        self.assertIn('function selectedAlarmMp3()', javascript)
        self.assertIn('let selectedMp3 = ""', javascript)
        self.assertIn('return selectedMp3', javascript)
        self.assertIn('selectedUsedByAnotherAlarm = [...selectedUsedByIds].some', javascript)
        self.assertNotIn('writeEnabled && selectedRuntimeTag?.path', javascript)
        self.assertIn('row.disabled = usedByAnotherAlarm', javascript)
        self.assertIn('selectedMp3 = event.target.value', javascript)
        self.assertIn('function updateAlarmSaveReadiness()', javascript)
        self.assertIn('const ready = Boolean(selectedRuntimeTag?.path)', javascript)
        self.assertIn('document.getElementById("save-alarm").disabled = !ready', javascript)
        self.assertIn('loadAlarmMp3(alarm?.mp3_file ?? pendingMp3)', javascript)
        self.assertIn('if (!selectedRuntimeTag?.path) return', javascript)
        self.assertLess(
            javascript.index('document.getElementById("alarm-form").addEventListener("submit"'),
            javascript.index('fetch("/api/opc-tags/sync-one"'),
        )
        self.assertIn('alarm_mode: document.getElementById("alarm-mode").value || "HIGH"', javascript)
        self.assertIn('threshold_high: alarmNumber("alarm-threshold-high")', javascript)
        self.assertIn('threshold_low: alarmNumber("alarm-threshold-low")', javascript)
        self.assertIn('mp3_file: selectedAlarmMp3()', javascript)
        self.assertIn('priority: Number(document.getElementById("alarm-priority").value || "1")', javascript)
        self.assertIn('repeat: Number(document.getElementById("alarm-repeat").value || "3")', javascript)
        self.assertIn('enable_alarm: document.getElementById("alarm-enable").checked', javascript)
        alarm_runtime = Path("../alarm_sound/alarm_sound_v11.py").read_text(encoding="utf-8")
        self.assertIn('if not mp3_file:', alarm_runtime)
        self.assertIn('if alarm.get("mp3_file"):', alarm_runtime)
        _get_conn.assert_not_called()
        stylesheet = Path("static/app.css").read_text(encoding="utf-8")
        self.assertIn('[data-theme="dark"]', stylesheet)
        self.assertIn('[data-theme="light"]', stylesheet)
        self.assertIn('background: var(--bg-card)', stylesheet)
        self.assertNotIn('background: #f8fafc', stylesheet)
        self.assertIn('min-width: 260px', stylesheet)
        self.assertIn('min-width: 320px', stylesheet)
        self.assertIn('flex: 0 0 10px', stylesheet)
        self.assertIn('pointer-events: auto', stylesheet)
        self.assertIn('cursor: col-resize', stylesheet)
        self.assertIn('z-index: 3', stylesheet)
        self.assertIn('.alarm-horizontal-splitter', stylesheet)
        self.assertIn('height: 10px', stylesheet)
        self.assertIn('cursor: row-resize', stylesheet)
        self.assertIn('.alarm-top-workspace { height: calc(100vh - 140px); min-height: 440px; }', stylesheet)
        self.assertIn('.alarm-left-center-workspace { display: flex;', stylesheet)
        self.assertIn('.workspace.runtime-mode .details-panel { flex: 1 1 auto !important; min-width: 320px; overflow-y: auto; }', stylesheet)
        self.assertIn('tr.alarm-enabled', stylesheet)
        self.assertIn('tr.alarm-disabled', stylesheet)
        self.assertIn('.tag-configuration-workspace { height: calc(100vh - 140px); min-height: 120px; }', stylesheet)
        self.assertNotIn('.workspace.runtime-mode { height:', stylesheet)
        self.assertIn('@media (max-width: 980px)', stylesheet)
        self.assertIn('.alarm-audio-options', stylesheet)
        self.assertIn('data.status === "similar_resource_found"', javascript)
        self.assertIn("Upload as New Version", javascript)
        self.assertIn("Create Separate Resource", javascript)
        self.assertIn("Confirm Separate Resource", javascript)
        self.assertIn('id="new-supplier"', html)
        self.assertIn('id="find-supplier"', html)
        self.assertIn('id="supplier-directory-view"', html)
        self.assertIn('id="supplier-form"', html)
        self.assertIn('View Supplier', javascript)
        self.assertIn('id="new-equipment-part"', html)
        self.assertIn('id="find-equipment-part"', html)
        self.assertIn('id="equipment-part-directory-view"', html)
        self.assertIn('id="equipment-part-form"', html)
        self.assertIn("similar_equipment_part_found", javascript)
        self.assertIn("Create Separate Equipment / Part", javascript)
        self.assertIn('beginTargetSelection(resource)', javascript)
        self.assertIn("The selected file has different content.", javascript)
        self.assertEqual(self.request("GET", "/static/app.js")[0], 200)
        self.assertEqual(self.request("GET", "/static/app.css")[0], 200)

    def test_full_reconcile_endpoint_returns_structured_result_without_subscriber_sync(self):
        expected = ReconcileResult(
            total_discovered=4,
            added=1,
            changed=1,
            unchanged=2,
            deactivated=1,
            run_id=9,
            duration=0.125,
        )
        with patch.object(OpcTagManager.tag_reconcile_service, "reconcile", new=AsyncMock(return_value=expected)):
            status, body = self.request("POST", "/api/runtime/full-reconcile", {"confirm": "FULL_RECONCILE"})
        payload = json.loads(body)
        self.assertEqual(status, 200)
        self.assertEqual(payload["run_id"], 9)
        self.assertEqual(payload["added"], 1)
        self.assertFalse(payload["subscriber_synchronized"])
        OpcTagManager.last_reconcile_result = None

    def test_full_reconcile_endpoint_requires_explicit_confirmation(self):
        status, _body = self.request("POST", "/api/runtime/full-reconcile", {"confirm": "no"})
        self.assertEqual(status, 422)

    def test_all_tags_source_returns_live_kepware_nodes_without_tagmaster_access(self):
        unregistered_channel = {
            "name": "UNREGISTERED_CHANNEL",
            "object_type": "Channel",
            "full_path": "UNREGISTERED_CHANNEL",
            "expandable": True,
            "context": {"channel": "UNREGISTERED_CHANNEL", "device": "", "group_path": []},
            "properties": {},
        }
        with patch.object(OpcTagManager.kepware_config_api, "get_channels", return_value=[unregistered_channel]), patch.object(
            OpcTagManager, "get_conn"
        ) as get_conn:
            status, body = self.request("GET", "/api/kepware/channels")
        payload = json.loads(body)
        self.assertEqual(status, 200)
        self.assertTrue(payload["connected"])
        self.assertEqual(payload["nodes"], [unregistered_channel])
        get_conn.assert_not_called()

        unregistered_tag = {
            "name": "NotYetRegistered",
            "object_type": "Tag",
            "full_path": "UNREGISTERED_CHANNEL.Device.Group.NotYetRegistered",
            "expandable": False,
            "context": {"channel": "UNREGISTERED_CHANNEL", "device": "Device", "group_path": ["Group"]},
            "properties": {},
            "tag_details": {"data_type": 1, "address": "X1"},
        }
        with patch.object(OpcTagManager.kepware_config_api, "get_group_children", return_value=[unregistered_tag]), patch.object(
            OpcTagManager, "get_conn"
        ) as get_conn:
            status, body = self.request(
                "GET", "/api/kepware/group-children?channel=UNREGISTERED_CHANNEL&device=Device&group_path=Group"
            )
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["nodes"], [unregistered_tag])
        get_conn.assert_not_called()

    def test_single_existing_tag_sync_requires_confirmation(self):
        status, _body = self.request(
            "POST",
            "/api/opc-tags/sync-one",
            {"path": "Line/Device/Tag", "confirm": "no"},
        )
        self.assertEqual(status, 422)

    def test_single_existing_tag_sync_has_no_kepware_alarm_or_historian_mutation(self):
        synced = FastSyncResult(
            path="Line/Device/Tag",
            node_id="ns=2;s=Line.Device.Tag",
            data_type="Boolean",
            tag_id=12,
            registry_state="added",
            run_id=8,
            attempts=1,
            duration=0.02,
            historian_rebuild_requested=False,
        )
        with (
            patch.object(
                OpcTagManager.tag_fast_sync_service,
                "sync_existing_tag",
                new=AsyncMock(return_value=synced),
            ) as sync,
            patch.object(OpcTagManager.kepware_config_api, "create_tag") as create,
            patch.object(OpcTagManager.alarm_reload_notifier, "notify") as notify,
            patch.object(OpcTagManager.runtime_supervisor, "notify_registry_changed") as historian,
        ):
            status, body = self.request(
                "POST",
                "/api/opc-tags/sync-one",
                {"path": "Line/Device/Tag", "confirm": "SYNC_ONE_EXISTING_TAG"},
            )
        payload = json.loads(body)
        self.assertEqual(status, 200)
        self.assertTrue(payload["success"])
        self.assertEqual(payload["operation"], "single_existing_tag_sync")
        self.assertEqual(payload["kepware_mutation"], "not_requested")
        self.assertEqual(payload["alarm_reload"], "not_requested")
        self.assertEqual(payload["historian_subscription_sync"]["status"], "not_requested")
        sync.assert_awaited_once_with("Line/Device/Tag")
        create.assert_not_called()
        notify.assert_not_called()
        historian.assert_not_called()

    def test_exact_path_lookup_distinguishes_unregistered_and_reuses_registered_tag_id(self):
        class LookupCursor:
            def __init__(self, row):
                self.row = row
                self.query = None
                self.path = None

            def execute(self, query, path):
                self.query = " ".join(query.split())
                self.path = path

            def fetchone(self):
                return self.row

        class LookupConnection:
            def __init__(self, row):
                self.lookup_cursor = LookupCursor(row)

            def cursor(self):
                return self.lookup_cursor

            def close(self):
                return None

        missing = LookupConnection(None)
        with patch.object(OpcTagManager, "get_conn", return_value=missing), patch.object(
            OpcTagManager.tag_reconcile_service, "reconcile", new=AsyncMock()
        ) as reconcile, patch.object(OpcTagManager.tag_fast_sync_service, "sync_existing_tag", new=AsyncMock()) as sync:
            status, body = self.request("GET", "/api/opc-tags/resolve/by-path?path=Line%2FDevice%2FUnregistered")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), {"success": True, "registered": False, "tag": None, "alarm": None})
        self.assertEqual(missing.lookup_cursor.path, "Line/Device/Unregistered")
        reconcile.assert_not_awaited()
        sync.assert_not_awaited()

        registered = LookupConnection((42, "Line/Device/Registered", "ns=2;s=Line.Device.Registered", "Boolean"))
        alarm = {"alarm_id": 7, "tag_id": 42, "tag_path": "Line/Device/Registered"}
        with patch.object(OpcTagManager, "get_conn", return_value=registered), patch.object(
            OpcTagManager.alarm_service, "get_for_tag", return_value=alarm
        ) as get_alarm, patch.object(OpcTagManager.tag_fast_sync_service, "sync_existing_tag", new=AsyncMock()) as sync:
            status, body = self.request("GET", "/api/opc-tags/resolve/by-path?path=Line%2FDevice%2FRegistered")
        payload = json.loads(body)
        self.assertEqual(status, 200)
        self.assertTrue(payload["registered"])
        self.assertEqual(payload["tag"]["tag_id"], 42)
        self.assertEqual(payload["tag"]["node_id"], "ns=2;s=Line.Device.Registered")
        self.assertEqual(payload["alarm"], alarm)
        get_alarm.assert_called_once_with(42)
        sync.assert_not_awaited()

    @patch.object(OpcTagManager, "get_conn", return_value=FakeConnection())
    def test_runtime_status_is_read_only_and_separates_development_from_production_ownership(self, _get_conn):
        supervisor_status = {
            "historian_ownership": "legacy_opc_service",
            "supervisor_enabled": False,
            "development_historian_runtime": "disabled",
            "production_historian_owner": "legacy_opc_service",
            "legacy_historian_process_state": "unknown",
        }
        with patch.object(OpcTagManager.runtime_supervisor, "status", return_value=supervisor_status):
            status, body = self.request("GET", "/api/runtime/status")
        payload = json.loads(body)
        self.assertEqual(status, 200)
        self.assertEqual(payload["historian_ownership"], "legacy_opc_service")
        self.assertFalse(payload["supervisor_enabled"])
        self.assertEqual(payload["development_historian_runtime"], "disabled")
        self.assertEqual(payload["production_historian_owner"], "legacy_opc_service")
        self.assertEqual(payload["legacy_historian_process_state"], "unknown")

    def test_runtime_activity_returns_bounded_supervisor_diagnostics(self):
        runtime = {"worker_state": "running", "opc_state": "connected"}
        activity = {
            "subscription": [{"event": "subscriptions_ready"}],
            "influx": [{"event": "influx_write", "success": True}],
            "alarm": [{"event": "alarm_activity", "state": "ACTIVE"}],
            "summary": {"active_alarms": 1},
        }
        with patch.object(OpcTagManager.runtime_supervisor, "status", return_value=runtime), \
             patch.object(OpcTagManager.runtime_supervisor, "activity", return_value=activity):
            status, body = self.request("GET", "/api/runtime/activity")
        payload = json.loads(body)
        self.assertEqual(status, 200)
        self.assertTrue(payload["success"])
        self.assertEqual(payload["runtime"], runtime)
        self.assertEqual(payload["summary"]["active_alarms"], 1)

    def test_cutover_preflight_endpoint_is_read_only_and_never_claims_live_ready(self):
        expected = {
            "mode": "READ-ONLY",
            "production_historian_ownership": "legacy_opc_service",
            "ready_for_live_cutover": False,
        }
        with patch.object(OpcTagManager.historian_cutover_preflight, "run", return_value=expected) as run:
            status, body = self.request("GET", "/api/runtime/historian-cutover-preflight")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), expected)
        run.assert_called_once_with()

    def test_alarm_readiness_endpoint_never_calls_kepware_write_methods(self):
        expected = {"read_only": True, "ready": True, "reload_ready": True}
        preflight = MagicMock()
        preflight.run.return_value = expected
        with (
            patch.object(OpcTagManager, "alarm_preflight", preflight),
            patch.object(OpcTagManager.kepware_config_api.session, "post") as post,
            patch.object(OpcTagManager.kepware_config_api.session, "put") as put,
            patch.object(OpcTagManager.kepware_config_api.session, "delete") as delete,
        ):
            status, body = self.request("GET", "/api/runtime/alarm-readiness")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), expected)
        preflight.run.assert_called_once_with()
        post.assert_not_called()
        put.assert_not_called()
        delete.assert_not_called()

    def test_create_route_requires_all_explicit_operational_properties(self):
        status, body = self.request(
            "POST",
            "/api/kepware/tags",
            {
                "channel": "Line 1",
                "device": "Device 1",
                "tag_name": "New Tag",
                "address": "DB1.X0",
            },
        )
        self.assertEqual(status, 422)
        missing = {item["loc"][-1] for item in json.loads(body)["detail"]}
        self.assertEqual(missing, {"data_type", "scan_rate", "access"})

    @staticmethod
    def create_payload():
        return {
            "channel": "Line",
            "device": "Device",
            "group_path": ["Group"],
            "tag_name": "NewTag",
            "address": "DB1.X0",
            "data_type": 1,
            "scan_rate": 100,
            "access": 1,
            "description": "",
        }

    @staticmethod
    def created_tag_result():
        return {
            "destination_path": "Line/Device/Group",
            "endpoint": "/configured/tags",
            "tag": {"name": "NewTag", "full_path": "Line.Device.Group.NewTag"},
            "requested_properties": {},
            "differences": [],
        }

    def test_create_success_fast_syncs_exact_path_without_full_reconcile(self):
        synced = FastSyncResult(
            path="Line/Device/Group/NewTag", node_id="ns=2;s=Line.Device.Group.NewTag",
            data_type="Boolean", tag_id=22, registry_state="added", run_id=8,
            attempts=2, duration=0.1, historian_rebuild_requested=False,
        )
        runtime = {
            "supervisor_enabled": False,
            "rebuild_pending": True,
            "registry_generation": 3,
        }
        with (
            patch.object(OpcTagManager.kepware_config_api, "create_tag", return_value=self.created_tag_result()) as create,
            patch.object(OpcTagManager.tag_fast_sync_service, "sync", new=AsyncMock(return_value=synced)) as sync,
            patch.object(OpcTagManager.tag_reconcile_service, "reconcile", new=AsyncMock()) as reconcile,
            patch.object(OpcTagManager.runtime_supervisor, "status", return_value=runtime),
        ):
            status, body = self.request("POST", "/api/kepware/tags", self.create_payload())
        payload = json.loads(body)
        self.assertEqual(status, 200)
        self.assertTrue(payload["success"])
        self.assertEqual(payload["kepware_create"]["status"], "succeeded")
        self.assertEqual(payload["runtime_registry_sync"]["status"], "succeeded")
        self.assertEqual(payload["runtime_registry_sync"]["path"], "Line/Device/Group/NewTag")
        self.assertEqual(payload["historian_subscription_sync"]["status"], "pending_disabled")
        create.assert_called_once()
        sync.assert_awaited_once_with("Line/Device/Group/NewTag")
        reconcile.assert_not_awaited()

    def test_kepware_success_fast_sync_failure_is_explicit_and_not_compensated(self):
        with (
            patch.object(OpcTagManager.kepware_config_api, "create_tag", return_value=self.created_tag_result()) as create,
            patch.object(OpcTagManager.tag_fast_sync_service, "sync", new=AsyncMock(side_effect=FastSyncError("not visible"))) as sync,
            patch.object(OpcTagManager.tag_reconcile_service, "reconcile", new=AsyncMock()) as reconcile,
        ):
            status, body = self.request("POST", "/api/kepware/tags", self.create_payload())
        payload = json.loads(body)
        self.assertEqual(status, 200)
        self.assertTrue(payload["success"])
        self.assertEqual(payload["kepware_create"]["status"], "succeeded")
        self.assertEqual(payload["runtime_registry_sync"]["status"], "failed")
        self.assertTrue(payload["runtime_registry_sync"]["full_reconcile_available"])
        self.assertEqual(payload["historian_subscription_sync"]["status"], "not_requested")
        create.assert_called_once()
        sync.assert_awaited_once()
        reconcile.assert_not_awaited()

    def test_normal_kepware_tag_creation_never_notifies_alarm_reload(self):
        synced = type("Synced", (), {
            "historian_rebuild_requested": False,
            "to_dict": lambda self: {"path": "Line/Device/Group/NewTag"},
        })()
        runtime = {
            "supervisor_enabled": False,
            "rebuild_pending": True,
            "registry_generation": 3,
        }
        with (
            patch.object(OpcTagManager.kepware_config_api, "create_tag", return_value=self.created_tag_result()),
            patch.object(OpcTagManager.tag_fast_sync_service, "sync", new=AsyncMock(return_value=synced)),
            patch.object(OpcTagManager.runtime_supervisor, "status", return_value=runtime),
            patch.object(OpcTagManager.alarm_reload_notifier, "notify") as notify,
        ):
            status, _body = self.request("POST", "/api/kepware/tags", self.create_payload())
        self.assertEqual(status, 200)
        notify.assert_not_called()

    @patch.object(OpcTagManager.tag_knowledge_store, "save")
    @patch.object(OpcTagManager, "KM_TAG_WRITE_ENABLED", False)
    @patch.object(
        OpcTagManager.kepware_config_api,
        "get_tag",
        side_effect=KepwareConfigError("The selected Kepware Tag no longer exists."),
    )
    def test_knowledge_save_validates_tag_exists_before_storage(self, get_tag, save):
        status, body = self.request(
            "POST",
            "/api/tag-knowledge/save",
            {
                "channel": "LP2",
                "device": "MIX",
                "group_path": [],
                "tag_name": "Missing",
                "description": "No write should occur",
            },
        )
        self.assertEqual(status, 403)
        self.assertIn("no longer exists", json.loads(body)["error"])
        get_tag.assert_called_once()
        save.assert_not_called()

    def test_knowledge_image_upload_passes_only_validated_identity_and_bounded_content_to_store(self):
        identity = TagIdentity("LP2", "MIX", [], "Tag", "LP2.MIX.Tag", "1", 5, 100, 1)
        upload = UploadFile(
            file=io.BytesIO(b"\x89PNG\r\n\x1a\nimage"), filename="sensor.png",
            headers=Headers({"content-type": "image/png"}),
        )
        expected = {"section": "how_to_check", "relative_path": "attachments/how_to_check/generated.png"}
        with patch.object(OpcTagManager, "_validated_knowledge_identity", return_value=(identity, {})), \
             patch.object(OpcTagManager.tag_knowledge_store, "store_attachment", return_value=expected) as store:
            result = asyncio.run(OpcTagManager.upload_tag_knowledge_attachment(
                channel="LP2", device="MIX", group_path="[]", tag_name="Tag",
                section="how_to_check", file=upload,
            ))
        self.assertEqual(result, {"success": True, "attachment": expected})
        args = store.call_args.args
        self.assertEqual(args[:4], (identity, "how_to_check", "sensor.png", "image/png"))
        self.assertEqual(args[4], b"\x89PNG\r\n\x1a\nimage")

    def test_current_knowledge_returns_flat_grafana_contract_with_guarded_image_urls(self):
        identity = TagIdentity("LP2", "MIX", ["Faults"], "Cement_FML", "LP2.MIX.Faults.Cement_FML", "1", 5, 100, 1)
        knowledge = {
            "exists": True, "version": 3, "updated_at": "2026-08-25T18:53:39+07:00",
            "fields": {
                "description": "Meaning", "possible_cause": "Cause", "how_to_check": "Check",
                "corrective_action": "Correct", "safety_warning": "Safe", "additional_notes": "Notes",
            },
            "attachments": {
                "description": [{"caption": "Sensor", "relative_path": "attachments/description/image one.png"}],
                "possible_cause": [], "how_to_check": [], "corrective_action": [],
                "safety_warning": [], "additional_notes": [],
            },
        }
        with patch.object(OpcTagManager, "_validated_knowledge_identity", return_value=(identity, {})) as validate, \
             patch.object(OpcTagManager.tag_knowledge_store, "load", return_value=knowledge) as load:
            status, body = self.request("GET", "/api/tag-knowledge/current?kepware_path=LP2.MIX.Faults.Cement_FML")
        payload = json.loads(body)
        self.assertEqual(status, 200)
        self.assertEqual(payload["kepware_path"], identity.full_path)
        self.assertEqual(payload["tag_name"], "Cement_FML")
        self.assertTrue(payload["has_knowledge"])
        self.assertEqual(payload["version"], 3)
        self.assertEqual(payload["updated_at"], "2026-08-25T18:53:39+07:00")
        self.assertEqual(list(payload["sections"]), [
            "description", "possible_cause", "how_to_check", "corrective_action",
            "safety_warning", "additional_notes",
        ])
        image = payload["sections"]["description"]["images"][0]
        self.assertEqual(image["caption"], "Sensor")
        self.assertTrue(image["url"].startswith("/api/tag-knowledge/attachment?"))
        self.assertIn("relative_path=attachments%2Fdescription%2Fimage+one.png", image["url"])
        self.assertNotIn("relative_path", image)
        self.assertNotIn("km_directory", json.dumps(payload))
        validate.assert_called_once()
        validated_payload = validate.call_args.args[0]
        self.assertEqual((validated_payload.channel, validated_payload.device), ("LP2", "MIX"))
        self.assertEqual(validated_payload.group_path, ["Faults"])
        self.assertEqual(validated_payload.tag_name, "Cement_FML")
        load.assert_called_once_with(identity)

    def test_current_knowledge_returns_empty_sections_for_valid_tag_without_knowledge(self):
        identity = TagIdentity("LP2", "MIX", [], "Cement_FML", "LP2.MIX.Cement_FML", "1", 5, 100, 1)
        empty_fields = {key: "" for key in (
            "description", "possible_cause", "how_to_check", "corrective_action",
            "safety_warning", "additional_notes",
        )}
        knowledge = {
            "exists": False, "version": 0, "updated_at": None,
            "fields": empty_fields, "attachments": {key: [] for key in empty_fields},
        }
        with patch.object(OpcTagManager, "_validated_knowledge_identity", return_value=(identity, {})), \
             patch.object(OpcTagManager.tag_knowledge_store, "load", return_value=knowledge):
            status, body = self.request("GET", "/api/tag-knowledge/current?kepware_path=LP2.MIX.Cement_FML")
        payload = json.loads(body)
        self.assertEqual(status, 200)
        self.assertFalse(payload["has_knowledge"])
        self.assertIsNone(payload["version"])
        self.assertIsNone(payload["updated_at"])
        self.assertTrue(all(section == {"text": "", "images": []} for section in payload["sections"].values()))

    def test_current_knowledge_rejects_malformed_path_without_kepware_or_storage_read(self):
        with patch.object(OpcTagManager, "_validated_knowledge_identity") as validate, \
             patch.object(OpcTagManager.tag_knowledge_store, "load") as load:
            status, body = self.request("GET", "/api/tag-knowledge/current?kepware_path=LP2..Tag")
        self.assertEqual(status, 422)
        self.assertIn("channel, device, and tag", json.loads(body)["error"])
        validate.assert_not_called()
        load.assert_not_called()

    def test_current_knowledge_returns_404_for_unknown_kepware_path_without_storage_read(self):
        with patch.object(
            OpcTagManager, "_validated_knowledge_identity",
            side_effect=KepwareConfigError("Kepware Configuration API returned HTTP 404."),
        ), patch.object(OpcTagManager.tag_knowledge_store, "load") as load:
            status, body = self.request("GET", "/api/tag-knowledge/current?kepware_path=LP2.MIX.Missing")
        self.assertEqual(status, 404)
        self.assertEqual(json.loads(body)["kepware_path"], "LP2.MIX.Missing")
        load.assert_not_called()

    def test_current_knowledge_returns_500_for_corrupt_active_knowledge(self):
        identity = TagIdentity("LP2", "MIX", [], "Cement_FML", "LP2.MIX.Cement_FML", "1", 5, 100, 1)
        with patch.object(OpcTagManager, "_validated_knowledge_identity", return_value=(identity, {})), \
             patch.object(
                 OpcTagManager.tag_knowledge_store, "load",
                 side_effect=OpcTagManager.TagKnowledgeError("The active Tag Knowledge index or Markdown file is invalid."),
             ):
            status, body = self.request("GET", "/api/tag-knowledge/current?kepware_path=LP2.MIX.Cement_FML")
        payload = json.loads(body)
        self.assertEqual(status, 500)
        self.assertEqual(payload["error"], "The active Tag Knowledge record is invalid.")
        self.assertNotIn("has_knowledge", payload)

    def test_missing_knowledge_attachment_read_returns_404(self):
        identity = TagIdentity("LP2", "MIX", [], "Cement_FML", "LP2.MIX.Cement_FML", "1", 5, 100, 1)
        with patch.object(OpcTagManager, "_validated_knowledge_identity", return_value=(identity, {})), \
             patch.object(
                 OpcTagManager.tag_knowledge_store, "attachment_path",
                 side_effect=OpcTagManager.TagKnowledgeError("The Tag Knowledge attachment does not exist."),
             ):
            result = OpcTagManager.read_tag_knowledge_attachment(
                "LP2", "MIX", "Cement_FML", "attachments/description/missing.png",
            )
        self.assertEqual(result.status_code, 404)

    def test_alarm_help_returns_no_alarm_contract_when_runtime_is_ready_and_empty(self):
        with patch.object(OpcTagManager.runtime_supervisor, "status", return_value={"alarm_activity_state": "ready"}), \
             patch.object(OpcTagManager.runtime_supervisor, "active_alarm_activity", return_value=[]):
            status, body = self.request("GET", "/api/alarm-help/current")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), {"has_alarm": False, "alarm": None, "knowledge": None})

    def test_alarm_help_selects_highest_priority_then_newest_and_returns_knowledge(self):
        identity = TagIdentity("LP2", "MIX", [], "Newest", "LP2.MIX.Newest", "1", 5, 100, 1)
        alarms = [
            {"alarm_id": 1, "path": "LP2/MIX/Lower", "priority": 2, "state": "ACTIVE", "value": 1,
             "activated_at": "2026-08-25T10:00:00+00:00", "active_order_time": "2026-08-25T10:00:00+00:00"},
            {"alarm_id": 2, "path": "LP2/MIX/Older", "priority": 3, "state": "ACTIVE", "value": 2,
             "activated_at": "2026-08-25T10:01:00+00:00", "active_order_time": "2026-08-25T10:01:00+00:00"},
            {"alarm_id": 3, "path": "LP2/MIX/Newest", "priority": 3, "state": "ACTIVE", "value": 3,
             "activated_at": "2026-08-25T10:02:00+00:00", "active_order_time": "2026-08-25T10:02:00+00:00"},
            {"alarm_id": 4, "path": "LP2/MIX/Cleared", "priority": 99, "state": "CLEARED", "value": 0,
             "activated_at": "2026-08-25T10:03:00+00:00", "active_order_time": "2026-08-25T10:03:00+00:00"},
        ]
        empty_fields = {key: "" for key in (
            "description", "possible_cause", "how_to_check", "corrective_action",
            "safety_warning", "additional_notes",
        )}
        knowledge = {
            "exists": True, "version": 4, "updated_at": "2026-08-25T18:00:00+07:00",
            "fields": {**empty_fields, "description": "Alarm help"},
            "attachments": {key: [] for key in empty_fields},
        }
        with patch.object(OpcTagManager.runtime_supervisor, "status", return_value={"alarm_activity_state": "ready"}), \
             patch.object(OpcTagManager.runtime_supervisor, "active_alarm_activity", return_value=alarms), \
             patch.object(OpcTagManager, "_validated_knowledge_identity_from_path", return_value=(identity, {})) as validate, \
             patch.object(OpcTagManager.tag_knowledge_store, "load", return_value=knowledge) as load:
            status, body = self.request("GET", "/api/alarm-help/current")
        payload = json.loads(body)
        self.assertEqual(status, 200)
        self.assertTrue(payload["has_alarm"])
        self.assertEqual(payload["alarm"], {
            "alarm_id": 3, "kepware_path": "LP2.MIX.Newest", "tag_name": "Newest",
            "priority": 3, "state": "ACTIVE", "value": 3,
            "activated_at": "2026-08-25T10:02:00+00:00",
        })
        self.assertEqual(payload["knowledge"]["version"], 4)
        self.assertEqual(payload["knowledge"]["sections"]["description"]["text"], "Alarm help")
        self.assertNotIn("kepware_path", payload["knowledge"])
        validate.assert_called_once_with("LP2.MIX.Newest")
        load.assert_called_once_with(identity)

    def test_alarm_help_returns_empty_knowledge_for_selected_alarm_without_knowledge(self):
        identity = TagIdentity("LP2", "MIX", [], "Alarm", "LP2.MIX.Alarm", "1", 5, 100, 1)
        sections = ("description", "possible_cause", "how_to_check", "corrective_action", "safety_warning", "additional_notes")
        knowledge = {
            "exists": False, "version": 0, "updated_at": None,
            "fields": {key: "" for key in sections}, "attachments": {key: [] for key in sections},
        }
        alarm = {"alarm_id": 7, "path": "LP2/MIX/Alarm", "priority": 1, "state": "ACTIVE",
                 "value": True, "activated_at": None, "active_order_time": "2026-08-25T10:00:00+00:00"}
        with patch.object(OpcTagManager.runtime_supervisor, "status", return_value={"alarm_activity_state": "ready"}), \
             patch.object(OpcTagManager.runtime_supervisor, "active_alarm_activity", return_value=[alarm]), \
             patch.object(OpcTagManager, "_validated_knowledge_identity_from_path", return_value=(identity, {})), \
             patch.object(OpcTagManager.tag_knowledge_store, "load", return_value=knowledge):
            status, body = self.request("GET", "/api/alarm-help/current")
        payload = json.loads(body)
        self.assertEqual(status, 200)
        self.assertFalse(payload["knowledge"]["has_knowledge"])
        self.assertIsNone(payload["knowledge"]["version"])
        self.assertTrue(all(value == {"text": "", "images": []} for value in payload["knowledge"]["sections"].values()))

    def test_alarm_help_returns_503_when_runtime_state_is_unavailable(self):
        with patch.object(OpcTagManager.runtime_supervisor, "status", return_value={"alarm_activity_state": "unknown"}), \
             patch.object(OpcTagManager.runtime_supervisor, "active_alarm_activity") as active:
            status, body = self.request("GET", "/api/alarm-help/current")
        self.assertEqual(status, 503)
        self.assertIn("unavailable", json.loads(body)["error"])
        active.assert_not_called()

    def test_alarm_help_returns_500_for_corrupt_knowledge(self):
        identity = TagIdentity("LP2", "MIX", [], "Alarm", "LP2.MIX.Alarm", "1", 5, 100, 1)
        alarm = {"alarm_id": 7, "path": "LP2/MIX/Alarm", "priority": 1, "state": "ACTIVE",
                 "active_order_time": "2026-08-25T10:00:00+00:00"}
        with patch.object(OpcTagManager.runtime_supervisor, "status", return_value={"alarm_activity_state": "ready"}), \
             patch.object(OpcTagManager.runtime_supervisor, "active_alarm_activity", return_value=[alarm]), \
             patch.object(OpcTagManager, "_validated_knowledge_identity_from_path", return_value=(identity, {})), \
             patch.object(OpcTagManager.tag_knowledge_store, "load", side_effect=OpcTagManager.TagKnowledgeError("bad")):
            status, body = self.request("GET", "/api/alarm-help/current")
        self.assertEqual(status, 500)
        self.assertEqual(json.loads(body)["error"], "The active Tag Knowledge record is invalid.")

    @patch.object(OpcTagManager.shared_resource_store, "link")
    @patch.object(OpcTagManager, "KM_RESOURCE_WRITE_ENABLED", False)
    @patch.object(OpcTagManager.kepware_config_api, "get_tag", return_value={
        "name": "Cement_FML", "full_path": "LP2.MIX.Cement_FML",
        "context": {"channel": "LP2", "device": "MIX", "group_path": []},
        "tag_details": {},
    })
    def test_resource_link_write_gate_is_independent_and_disabled(self, _get_tag, link):
        link.side_effect = OpcTagManager.SharedResourceError("Shared Resource write mode is disabled.")
        status, body = self.request("POST", "/api/tag-resources/link", {
            "channel": "LP2", "device": "MIX", "tag_name": "Cement_FML",
            "resource_id": "MAN_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
        })
        self.assertEqual(status, 403)
        self.assertIn("write mode is disabled", json.loads(body)["error"])

    def test_resource_link_rejects_client_filesystem_path(self):
        status, body = self.request("POST", "/api/tag-resources/link", {
            "channel": "LP2", "device": "MIX", "tag_name": "Cement_FML",
            "resource_id": "MAN_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
            "filesystem_path": "D:\\KM\\Vault\\Tags\\other",
        })
        self.assertEqual(status, 422)
        self.assertEqual(json.loads(body)["detail"][0]["type"], "extra_forbidden")

    def test_physical_upload_routes_reject_while_gate_disabled(self):
        with tempfile.TemporaryDirectory() as temporary:
            disabled = SharedResourceStore(Path(temporary) / "Tags", "Asia/Bangkok", False)
            with patch.object(OpcTagManager, "shared_resource_store", disabled), patch.object(OpcTagManager, "KM_RESOURCE_WRITE_ENABLED", False):
                response = OpcTagManager.upload_resource("Manual", "Manual", UploadFile(io.BytesIO(b"data"), filename="manual.pdf"))
                self.assertEqual(response.status_code, 403)
                response = OpcTagManager.upload_resource_version("MAN_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA", UploadFile(io.BytesIO(b"data"), filename="v2.pdf"))
                self.assertEqual(response.status_code, 403)

    def test_upload_ignores_injected_creation_identity_and_generates_resource_id(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = SharedResourceStore(Path(temporary) / "Tags", "Asia/Bangkok", True)
            with patch.object(OpcTagManager, "shared_resource_store", store), patch.object(OpcTagManager, "KM_RESOURCE_WRITE_ENABLED", True):
                response = OpcTagManager.upload_resource("Manual", "Safe Manual", UploadFile(io.BytesIO(b"safe"), filename="manual.pdf"), None, None, None, None)
            resource_id = response["resource"]["resource_id"]
            self.assertNotEqual(resource_id, "MAN_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA")
            self.assertTrue(resource_id.startswith("MAN_"))
            parameters = inspect.signature(OpcTagManager.upload_resource).parameters
            self.assertNotIn("resource_id", parameters)
            self.assertNotIn("filesystem_path", parameters)
            self.assertIn("confirm_separate_token", parameters)

    def test_batch_validates_every_tag_before_any_link_mutation(self):
        payload = {"resource_id": "MAN_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA", "tags": [
            {"channel": "LP2", "device": "MIX", "tag_groups": [], "tag": "One"},
            {"channel": "LP2", "device": "MIX", "tag_groups": [], "tag": "Missing"},
        ]}
        with patch.object(OpcTagManager, "KM_RESOURCE_WRITE_ENABLED", True), \
             patch.object(OpcTagManager.shared_resource_store, "read_index", return_value={}), \
             patch.object(OpcTagManager.shared_resource_store, "link") as link, \
             patch.object(OpcTagManager.kepware_config_api, "get_tag", side_effect=[{
                 "name": "One", "full_path": "LP2.MIX.One", "context": {"channel": "LP2", "device": "MIX", "group_path": []}, "tag_details": {}
             }, KepwareConfigError("missing")]) as get_tag:
            status, _body = self.request("POST", "/api/tag-resources/link-many", payload)
        self.assertEqual(status, 400)
        self.assertEqual(get_tag.call_count, 2)
        link.assert_not_called()

    def test_batch_reports_partial_failure_and_retry_safe_statuses(self):
        payload = {"resource_id": "MAN_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA", "tags": [
            {"channel": "LP2", "device": "MIX", "tag_groups": [], "tag": "One"},
            {"channel": "LP2", "device": "MIX", "tag_groups": [], "tag": "Two"},
        ]}
        nodes = [{"name": name, "full_path": f"LP2.MIX.{name}", "context": {"channel": "LP2", "device": "MIX", "group_path": []}, "tag_details": {}} for name in ("One", "Two")]
        with patch.object(OpcTagManager, "KM_RESOURCE_WRITE_ENABLED", True), patch.object(OpcTagManager.shared_resource_store, "read_index", return_value={}), \
             patch.object(OpcTagManager.kepware_config_api, "get_tag", side_effect=nodes), \
             patch.object(OpcTagManager.shared_resource_store, "link", side_effect=[{"status": "already_linked"}, OpcTagManager.SharedResourceError("disk failure")]):
            status, body = self.request("POST", "/api/tag-resources/link-many", payload)
        self.assertEqual(status, 200)
        self.assertEqual([item["status"] for item in json.loads(body)["results"]], ["already_linked", "failed"])

    def test_active_and_historical_pdf_files_are_inline(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = SharedResourceStore(Path(temporary) / "Tags", "Asia/Bangkok", True)
            created = store.upload_new("Manual", "AS550 Manual", "manual.pdf", io.BytesIO(b"pdf-v1"))["resource"]
            store.upload_version(created["resource_id"], "manual-v2.pdf", io.BytesIO(b"pdf-v2"))
            with patch.object(OpcTagManager, "shared_resource_store", store):
                active = OpcTagManager.open_resource_file(created["resource_id"], None)
                historical = OpcTagManager.open_resource_file(created["resource_id"], 1)
            for response in (active, historical):
                self.assertEqual(response.media_type, "application/pdf")
                self.assertTrue(response.headers["content-disposition"].startswith('inline; filename="AS550_Manual_v'))

    def test_supported_image_file_is_inline_with_correct_content_type(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = SharedResourceStore(Path(temporary) / "Tags", "Asia/Bangkok", True)
            created = store.upload_new("Photo", "Motor Photo", "motor.webp", io.BytesIO(b"image"))["resource"]
            with patch.object(OpcTagManager, "shared_resource_store", store):
                response = OpcTagManager.open_resource_file(created["resource_id"], None)
            self.assertEqual(response.media_type, "image/webp")
            self.assertTrue(response.headers["content-disposition"].startswith('inline; filename="Motor_Photo_v001_'))

    def test_file_route_keeps_invalid_resource_and_version_protected(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = SharedResourceStore(Path(temporary) / "Tags", "Asia/Bangkok", True)
            created = store.upload_new("Manual", "Manual", "manual.pdf", io.BytesIO(b"pdf"))["resource"]
            with patch.object(OpcTagManager, "shared_resource_store", store):
                bad_id = OpcTagManager.open_resource_file("../escape", None)
                bad_version = OpcTagManager.open_resource_file(created["resource_id"], 99)
            self.assertEqual(bad_id.status_code, 400)
            self.assertEqual(bad_version.status_code, 400)

    def test_supplier_create_rejects_client_resource_id_and_filesystem_path(self):
        base = {"supplier_name": "Safe Supplier", "contacts": []}
        for injected in ({"resource_id": "SUP_" + "A" * 32}, {"filesystem_path": "D:\\KM\\Vault\\outside"}):
            status, body = self.request("POST", "/api/suppliers", {**base, **injected})
            self.assertEqual(status, 422)
            self.assertEqual(json.loads(body)["detail"][0]["type"], "extra_forbidden")

    def test_supplier_routes_create_read_edit_search_and_respect_gate(self):
        supplier_payload = {"supplier_name": "API Supplier", "supplier_code": "API-1", "tax_id": "001-22-333", "contacts": [{
            "contact_name": "Support Person", "contact_type": "Support", "phone": "+66 1", "email": "support@example.com"
        }]}
        with tempfile.TemporaryDirectory() as temporary:
            resources = SharedResourceStore(Path(temporary) / "Tags", "Asia/Bangkok", True)
            suppliers = SupplierProfileStore(resources)
            with patch.object(OpcTagManager, "supplier_profile_store", suppliers), patch.object(OpcTagManager, "KM_RESOURCE_WRITE_ENABLED", True):
                status, body = self.request("POST", "/api/suppliers", supplier_payload)
                self.assertEqual(status, 200); created = json.loads(body); resource_id = created["supplier"]["resource_id"]
                self.assertTrue(resource_id.startswith("SUP_"))
                self.assertEqual(self.request("GET", f"/api/suppliers/{resource_id}")[0], 200)
                status, body = self.request("GET", "/api/suppliers/matches?tax_id=00122333")
                self.assertEqual(status, 200)
                self.assertEqual(json.loads(body)["suppliers"][0]["resource_id"], resource_id)
                self.assertEqual(len(suppliers.list("Support")), 1)
                edited = dict(supplier_payload); edited["general_phone"] = "+66 2"
                edited["contacts"] = created["supplier"]["contacts"]
                status, body = self.request("PUT", f"/api/suppliers/{resource_id}", edited)
                self.assertEqual(status, 200); self.assertEqual(json.loads(body)["resource"]["active_version"], 2)
            resources.write_enabled = False
            with patch.object(OpcTagManager, "supplier_profile_store", suppliers), patch.object(OpcTagManager, "KM_RESOURCE_WRITE_ENABLED", False):
                status, body = self.request("POST", "/api/suppliers", supplier_payload)
                self.assertEqual(status, 403); self.assertIn("write mode is disabled", json.loads(body)["error"])

    def test_equipment_part_api_rejects_identity_path_and_runs_temp_root_crud(self):
        base = {"display_name": "SKF Bearing", "item_kind": "Spare Part", "manufacturer": "SKF",
                "model": "6205", "part_no": "6205-2RS", "material_code": "0006205", "aliases": ["Bearing"], "supplier_links": []}
        for injected in ({"resource_id": "EPT_" + "A" * 32}, {"filesystem_path": "D:\\KM\\Vault\\outside"}, {"final_filename": "outside.md"}):
            status, body = self.request("POST", "/api/equipment-parts", {**base, **injected})
            self.assertEqual(status, 422); self.assertEqual(json.loads(body)["detail"][0]["type"], "extra_forbidden")
        with tempfile.TemporaryDirectory() as temporary:
            resources = SharedResourceStore(Path(temporary) / "Tags", "Asia/Bangkok", True); catalog = EquipmentPartStore(resources)
            with patch.object(OpcTagManager, "equipment_part_store", catalog), patch.object(OpcTagManager, "KM_RESOURCE_WRITE_ENABLED", True):
                status, body = self.request("POST", "/api/equipment-parts", base); self.assertEqual(status, 200)
                created = json.loads(body); resource_id = created["equipment_part"]["resource_id"]
                self.assertTrue(resource_id.startswith("EPT_")); self.assertEqual(self.request("GET", f"/api/equipment-parts/{resource_id}")[0], 200)
                edited = dict(base); edited["description"] = "Updated"
                status, body = self.request("PUT", f"/api/equipment-parts/{resource_id}", edited)
                self.assertEqual(status, 200); self.assertEqual(json.loads(body)["resource"]["active_version"], 2)
            resources.write_enabled = False
            with patch.object(OpcTagManager, "equipment_part_store", catalog), patch.object(OpcTagManager, "KM_RESOURCE_WRITE_ENABLED", False):
                status, body = self.request("POST", "/api/equipment-parts", base)
                self.assertEqual(status, 403); self.assertIn("write mode is disabled", json.loads(body)["error"])


    def test_resource_relationship_api_uses_logical_ids_and_temp_root(self):
        with tempfile.TemporaryDirectory() as temporary:
            resources = SharedResourceStore(Path(temporary) / "Tags", "Asia/Bangkok", True)
            graph = ResourceRelationshipStore(resources)
            ept = resources.upload_new("EquipmentPart", "Drive", "drive.pdf", io.BytesIO(b"ept"))["resource"]
            manual = resources.upload_new("Manual", "Drive Manual", "manual.pdf", io.BytesIO(b"manual"))["resource"]
            payload = {"source_resource_id": ept["resource_id"], "target_resource_id": manual["resource_id"]}
            with patch.object(OpcTagManager, "resource_relationship_store", graph), patch.object(OpcTagManager, "KM_RESOURCE_WRITE_ENABLED", True):
                status, body = self.request("POST", "/api/resource-relationships/link", payload)
                self.assertEqual(status, 200); self.assertEqual(json.loads(body)["status"], "linked")
                status, body = self.request("GET", f"/api/resource-relationships/{ept['resource_id']}")
                self.assertEqual(status, 200); self.assertEqual(json.loads(body)["relationships"][0]["target_resource_id"], manual["resource_id"])
                status, body = self.request("POST", "/api/resource-relationships/unlink", payload)
                self.assertEqual(status, 200); self.assertEqual(json.loads(body)["status"], "unlinked")
            bad = {"source_resource_id": ept["resource_id"], "target_resource_id": r"D:\KM\Vault\manual.pdf"}
            with patch.object(OpcTagManager, "resource_relationship_store", graph), patch.object(OpcTagManager, "KM_RESOURCE_WRITE_ENABLED", True):
                status, _body = self.request("POST", "/api/resource-relationships/link", bad)
                self.assertEqual(status, 400)

    def test_candidate_apis_are_read_only_evidence_contracts_without_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            resources = SharedResourceStore(Path(temporary) / "Tags", "Asia/Bangkok", True)
            suppliers = SupplierProfileStore(resources); catalog = EquipmentPartStore(resources)
            supplier = suppliers.create({"supplier_name": "ABC Co", "supplier_code": "ABC", "tax_id": "001-22",
                "website": "https://abc.example.com", "general_phone": "+66 123", "contacts": [{"contact_name": "Jane Doe", "contact_type": "Sales", "email": "jane@example.com", "phone": "+66 999"}]})["supplier"]
            part = catalog.create({"display_name": "ABC Motor", "item_kind": "Equipment", "manufacturer": "ABC", "model": "M1",
                "part_no": "P1", "material_code": "0007", "aliases": ["Main Motor"], "supplier_links": [{"supplier_resource_id": supplier["resource_id"], "relationship": "Manufacturer"}]})["equipment_part"]
            patches = (patch.object(OpcTagManager, "supplier_profile_store", suppliers), patch.object(OpcTagManager, "equipment_part_store", catalog))
            with patches[0], patches[1]:
                calls = [
                    "/api/suppliers/candidates?tax_id=00122&supplier_code=ABC",
                    f"/api/contacts/candidates?supplier_resource_id={supplier['resource_id']}&email=jane%40example.com",
                    "/api/equipment-parts/candidates?material_code=0007&manufacturer=ABC&part_no=P1",
                    f"/api/suppliers/{supplier['resource_id']}/equipment-parts",
                ]
                bodies = []
                for url in calls:
                    status, body = self.request("GET", url); self.assertEqual(status, 200); bodies.append(json.loads(body))
                self.assertEqual(bodies[0]["auto_selected_resource_id"], None)
                self.assertEqual(bodies[1]["candidates"][0]["contact_id"], supplier["contacts"][0]["contact_id"])
                self.assertEqual(bodies[2]["candidates"][0]["resource_id"], part["resource_id"])
                self.assertEqual(bodies[3]["equipment_parts"][0]["resource_id"], part["resource_id"])
                self.assertNotIn(str(Path(temporary)), json.dumps(bodies))
                self.assertNotIn("filesystem_path", json.dumps(bodies))
            self.assertEqual(suppliers.read(supplier["resource_id"])["resource"]["active_version"], 1)
            self.assertEqual(catalog.read(part["resource_id"])["resource"]["active_version"], 1)

    def test_alarm_mp3_search_and_preview_preserve_safe_special_filename(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            filename = "Long Name_(Zone 1)_เสียง.mp3"
            payload = b"ID3-test-audio"
            (root / filename).write_bytes(payload)
            with patch.object(OpcTagManager.alarm_audio_repository, "root", root):
                status, body = self.request("GET", "/api/alarm-mp3?search=zone%201")
                result = json.loads(body)
                self.assertEqual(status, 200)
                self.assertEqual(result["files"], [{"filename": filename, "size": len(payload)}])
                self.assertNotIn(temporary, body.decode())

                status, body = self.request("GET", f"/api/alarm-mp3/{filename}/preview")
                self.assertEqual(status, 200)
                self.assertEqual(body, payload)
                status, _body = self.request("GET", "/api/alarm-mp3/missing.mp3/preview")
                self.assertEqual(status, 404)


if __name__ == "__main__":
    unittest.main()
