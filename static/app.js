let selectedRuntimeTag = null;
let selectedAlarm = null;
let alarmMp3Loaded = false;
let alarmMp3Files = [];
let usedAlarmMp3 = new Map();
let selectedMp3 = "";

const themeStorageKey = "opcTagManagerTheme";
const themeToggle = document.getElementById("theme-toggle");

function validTheme(value) {
    return value === "dark" || value === "light" ? value : "dark";
}

function updateThemeControl(theme) {
    const nextTheme = theme === "dark" ? "Light" : "Dark";
    themeToggle.textContent = theme === "dark" ? "☀ Light" : "🌙 Dark";
    themeToggle.setAttribute("aria-label", `Switch to ${nextTheme} theme`);
}

function applyTheme(theme, persist = false) {
    const safeTheme = validTheme(theme);
    document.documentElement.dataset.theme = safeTheme;
    updateThemeControl(safeTheme);
    if (persist) {
        try {
            localStorage.setItem(themeStorageKey, safeTheme);
        } catch (_error) {
            // The selected theme still applies when browser storage is unavailable.
        }
    }
}

applyTheme(document.documentElement.dataset.theme);
themeToggle.addEventListener("click", () => {
    applyTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark", true);
});

const splitterStorageKey = "opcTagManager.mainPanelRatio";
const minimumPanelWidth = 350;
const workspace = document.querySelector(".workspace");
const alarmTopWorkspace = document.getElementById("opc-tag-list-workspace");
const tagConfigurationWorkspace = document.getElementById("tag-configuration-workspace");
const treePanel = document.querySelector(".tree-panel");
const detailsPanel = document.querySelector(".details-panel");
const alarmLeftCenterWorkspace = document.getElementById("alarm-left-center-workspace");
const alarmUpperWorkspace = document.getElementById("alarm-upper-workspace");
const mainPanelSplitter = document.getElementById("main-panel-splitter");
const alarmCenterSplitter = document.getElementById("alarm-center-splitter");
const alarmLeftWidthKey = "opcTagManager.alarmPane.leftWidth";
const alarmCenterWidthKey = "opcTagManager.alarmPane.centerWidth";
const alarmTopHeightKey = "opcTagManager.alarmPane.topHeight";
const alarmMinimumWidths = { left: 260, center: 240, right: 320 };
const alarmMinimumHeights = { top: 280, mapping: 160 };
const alarmHorizontalSplitter = document.getElementById("alarm-horizontal-splitter");
const alarmMappingWorkspace = document.getElementById("alarm-summary");
const initialAlarmTopHeight = alarmUpperWorkspace.getBoundingClientRect().height;
let mainPanelRatio = readSavedPanelRatio();
let resizeFrame = null;

function readSavedPanelRatio() {
    try {
        const saved = Number.parseFloat(localStorage.getItem(splitterStorageKey));
        return Number.isFinite(saved) && saved > 0 && saved < 1 ? saved : 0.5;
    } catch (_error) {
        return 0.5;
    }
}

function savePanelRatio() {
    try {
        localStorage.setItem(splitterStorageKey, String(mainPanelRatio));
    } catch (_error) {
        // Storage may be unavailable in privacy-restricted browser contexts.
    }
}

function splitterSpace() {
    const style = getComputedStyle(alarmCenterSplitter);
    return (
        alarmCenterSplitter.getBoundingClientRect().width +
        Number.parseFloat(style.marginLeft || "0") +
        Number.parseFloat(style.marginRight || "0")
    );
}

function applyMainPanelRatio() {
    const available = Math.max(0, workspace.clientWidth - splitterSpace());
    const effectiveMinimum = Math.min(minimumPanelWidth, available / 2);
    const desiredLeft = available * mainPanelRatio;
    const leftWidth = Math.max(
        effectiveMinimum,
        Math.min(desiredLeft, available - effectiveMinimum),
    );
    const rightWidth = Math.max(0, available - leftWidth);

    alarmLeftCenterWorkspace.style.flex = `0 0 ${leftWidth}px`;
    detailsPanel.style.flex = `0 0 ${rightWidth}px`;
    alarmCenterSplitter.setAttribute("aria-valuenow", String(Math.round(mainPanelRatio * 100)));
}

function ratioFromPointer(clientX) {
    const workspaceRect = workspace.getBoundingClientRect();
    const splitterRect = alarmCenterSplitter.getBoundingClientRect();
    const style = getComputedStyle(alarmCenterSplitter);
    const available = Math.max(1, workspace.clientWidth - splitterSpace());
    const pointerOffset =
        Number.parseFloat(style.marginLeft || "0") + splitterRect.width / 2;
    const requestedLeft = clientX - workspaceRect.left - pointerOffset;
    const effectiveMinimum = Math.min(minimumPanelWidth, available / 2);
    const clampedLeft = Math.max(
        effectiveMinimum,
        Math.min(requestedLeft, available - effectiveMinimum),
    );
    return clampedLeft / available;
}

alarmCenterSplitter.addEventListener("pointerdown", (event) => {
    if (workspace.classList.contains("runtime-mode")) return;
    if (event.button !== 0) return;
    alarmCenterSplitter.classList.add("dragging");
    document.body.style.userSelect = "none";

    const onPointerMove = (moveEvent) => {
        mainPanelRatio = ratioFromPointer(moveEvent.clientX);
        applyMainPanelRatio();
    };
    const onPointerUp = () => {
        alarmCenterSplitter.classList.remove("dragging");
        document.body.style.userSelect = "";
        document.removeEventListener("pointermove", onPointerMove);
        document.removeEventListener("pointerup", onPointerUp);
        savePanelRatio();
    };

    document.addEventListener("pointermove", onPointerMove);
    document.addEventListener("pointerup", onPointerUp);
    event.preventDefault();
});

alarmCenterSplitter.addEventListener("keydown", (event) => {
    if (workspace.classList.contains("runtime-mode")) return;
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    mainPanelRatio += event.key === "ArrowLeft" ? -0.02 : 0.02;
    mainPanelRatio = Math.max(0.05, Math.min(0.95, mainPanelRatio));
    applyMainPanelRatio();
    savePanelRatio();
    event.preventDefault();
});

window.addEventListener("resize", () => {
    if (resizeFrame !== null) cancelAnimationFrame(resizeFrame);
    resizeFrame = requestAnimationFrame(() => {
        resizeFrame = null;
        applyMainPanelRatio();
        if (workspace.classList.contains("runtime-mode")) {
            applyAlarmPaneWidths();
            applyAlarmTopHeight();
        }
    });
});

applyMainPanelRatio();

function splitterSpaceFor(splitter) {
    const style = getComputedStyle(splitter);
    return splitter.getBoundingClientRect().width
        + Number.parseFloat(style.marginLeft || "0")
        + Number.parseFloat(style.marginRight || "0");
}

function alarmAvailableWidth() {
    return Math.max(0, workspace.clientWidth - splitterSpaceFor(alarmCenterSplitter));
}

function savedAlarmWidth(key) {
    try {
        const value = Number.parseFloat(localStorage.getItem(key));
        return Number.isFinite(value) && value > 0 ? value : null;
    } catch (_error) {
        return null;
    }
}

function normalizedAlarmWidths(left, center) {
    const total = alarmAvailableWidth();
    const maximumLeft = Math.max(alarmMinimumWidths.left, total - alarmMinimumWidths.right);
    const safeLeft = Math.max(alarmMinimumWidths.left, Math.min(left, maximumLeft));
    return { left: safeLeft, center: 0 };
}

function defaultAlarmWidths() {
    const total = alarmAvailableWidth();
    return normalizedAlarmWidths(total * 0.55, 0);
}

function applyAlarmPaneWidths(useDefaults = false) {
    if (workspace.clientWidth <= 980) {
        workspace.style.removeProperty("--alarm-left-width");
        workspace.style.removeProperty("--alarm-center-width");
        alarmLeftCenterWorkspace.style.removeProperty("flex");
        return;
    }
    const defaults = defaultAlarmWidths();
    const widths = useDefaults ? defaults : normalizedAlarmWidths(
        savedAlarmWidth(alarmLeftWidthKey) ?? defaults.left,
        savedAlarmWidth(alarmCenterWidthKey) ?? defaults.center,
    );
    workspace.style.setProperty("--alarm-left-width", `${widths.left}px`);
    workspace.style.setProperty("--alarm-center-width", `${widths.center}px`);
    alarmLeftCenterWorkspace.style.flex = `0 0 ${widths.left}px`;
    mainPanelSplitter.setAttribute("aria-valuenow", String(Math.round(widths.left)));
    alarmCenterSplitter.setAttribute("aria-valuenow", String(Math.round(widths.left)));
}

function persistAlarmPaneWidths() {
    try {
        localStorage.setItem(alarmLeftWidthKey, String(alarmLeftCenterWorkspace.getBoundingClientRect().width));
    } catch (_error) {
        // Pane resizing remains available when browser storage is unavailable.
    }
}

function alarmVerticalTotalHeight() {
    const style = getComputedStyle(alarmHorizontalSplitter);
    const splitterHeight = alarmHorizontalSplitter.getBoundingClientRect().height
        + Number.parseFloat(style.marginTop || "0")
        + Number.parseFloat(style.marginBottom || "0");
    return Math.max(
        alarmMinimumHeights.top + alarmMinimumHeights.mapping,
        alarmLeftCenterWorkspace.clientHeight - splitterHeight,
    );
}

function clampAlarmTopHeight(height) {
    const total = alarmVerticalTotalHeight();
    return Math.max(alarmMinimumHeights.top, Math.min(height, total - alarmMinimumHeights.mapping));
}

function savedAlarmTopHeight() {
    try {
        const value = Number.parseFloat(localStorage.getItem(alarmTopHeightKey));
        return Number.isFinite(value) && value > 0 ? value : null;
    } catch (_error) {
        return null;
    }
}

function applyAlarmTopHeight(useDefault = false) {
    if (!workspace.classList.contains("runtime-mode") || workspace.clientWidth <= 980) {
        alarmUpperWorkspace.style.removeProperty("height");
        alarmMappingWorkspace.style.removeProperty("height");
        return;
    }
    const requested = useDefault ? initialAlarmTopHeight : (savedAlarmTopHeight() ?? initialAlarmTopHeight);
    const topHeight = clampAlarmTopHeight(requested);
    alarmUpperWorkspace.style.height = `${topHeight}px`;
    alarmMappingWorkspace.style.height = `${alarmVerticalTotalHeight() - topHeight}px`;
    alarmHorizontalSplitter.setAttribute("aria-valuenow", String(Math.round(topHeight)));
}

function persistAlarmTopHeight() {
    try {
        localStorage.setItem(alarmTopHeightKey, String(alarmUpperWorkspace.getBoundingClientRect().height));
    } catch (_error) {
        // Horizontal resizing remains available when browser storage is unavailable.
    }
}

function beginAlarmHorizontalResize(event) {
    if (!workspace.classList.contains("runtime-mode") || workspace.clientWidth <= 980 || event.button !== 0) return;
    const startY = event.clientY;
    const startTopHeight = alarmUpperWorkspace.getBoundingClientRect().height;
    alarmHorizontalSplitter.classList.add("dragging");
    document.body.style.userSelect = "none";
    alarmHorizontalSplitter.setPointerCapture?.(event.pointerId);

    const onPointerMove = (moveEvent) => {
        const topHeight = clampAlarmTopHeight(startTopHeight + moveEvent.clientY - startY);
        alarmUpperWorkspace.style.height = `${topHeight}px`;
        alarmMappingWorkspace.style.height = `${alarmVerticalTotalHeight() - topHeight}px`;
        alarmHorizontalSplitter.setAttribute("aria-valuenow", String(Math.round(topHeight)));
    };
    const finishResize = (finishEvent) => {
        alarmHorizontalSplitter.classList.remove("dragging");
        document.body.style.userSelect = "";
        alarmHorizontalSplitter.removeEventListener("pointermove", onPointerMove);
        alarmHorizontalSplitter.removeEventListener("pointerup", finishResize);
        alarmHorizontalSplitter.removeEventListener("pointercancel", finishResize);
        if (alarmHorizontalSplitter.hasPointerCapture?.(finishEvent.pointerId)) {
            alarmHorizontalSplitter.releasePointerCapture(finishEvent.pointerId);
        }
        persistAlarmTopHeight();
    };
    alarmHorizontalSplitter.addEventListener("pointermove", onPointerMove);
    alarmHorizontalSplitter.addEventListener("pointerup", finishResize);
    alarmHorizontalSplitter.addEventListener("pointercancel", finishResize);
    event.preventDefault();
}

alarmHorizontalSplitter.addEventListener("pointerdown", beginAlarmHorizontalResize);
alarmHorizontalSplitter.addEventListener("dblclick", () => {
    try {
        localStorage.removeItem(alarmTopHeightKey);
    } catch (_error) {
        // Reset still applies for this page load.
    }
    applyAlarmTopHeight(true);
});

function beginAlarmPaneResize(splitter, event, side) {
    if (!workspace.classList.contains("runtime-mode") || workspace.clientWidth <= 980 || event.button !== 0) return;
    const startX = event.clientX;
    const startLeft = alarmLeftCenterWorkspace.getBoundingClientRect().width;
    const startCenter = 0;
    const startRight = detailsPanel.getBoundingClientRect().width;
    splitter.classList.add("dragging");
    document.body.style.userSelect = "none";
    splitter.setPointerCapture?.(event.pointerId);

    const onPointerMove = (moveEvent) => {
        const delta = moveEvent.clientX - startX;
        let left = startLeft;
        let center = 0;
        left = Math.max(alarmMinimumWidths.left, Math.min(startLeft + delta, startLeft + startRight - alarmMinimumWidths.right));
        workspace.style.setProperty("--alarm-left-width", `${left}px`);
        workspace.style.setProperty("--alarm-center-width", `${center}px`);
        alarmLeftCenterWorkspace.style.flex = `0 0 ${left}px`;
    };
    const finishResize = (finishEvent) => {
        splitter.classList.remove("dragging");
        document.body.style.userSelect = "";
        splitter.removeEventListener("pointermove", onPointerMove);
        splitter.removeEventListener("pointerup", finishResize);
        splitter.removeEventListener("pointercancel", finishResize);
        if (splitter.hasPointerCapture?.(finishEvent.pointerId)) splitter.releasePointerCapture(finishEvent.pointerId);
        persistAlarmPaneWidths();
    };
    splitter.addEventListener("pointermove", onPointerMove);
    splitter.addEventListener("pointerup", finishResize);
    splitter.addEventListener("pointercancel", finishResize);
    event.preventDefault();
}

function bindAlarmPaneSplitter(splitter, side) {
    if (splitter.dataset.alarmResizeBound === "true") return;
    splitter.dataset.alarmResizeBound = "true";
    splitter.addEventListener("pointerdown", (event) => beginAlarmPaneResize(splitter, event, side));
}

bindAlarmPaneSplitter(alarmCenterSplitter, "center");
[mainPanelSplitter, alarmCenterSplitter].forEach((splitter) => {
    splitter.addEventListener("dblclick", () => {
        if (!workspace.classList.contains("runtime-mode")) return;
        try {
            localStorage.removeItem(alarmLeftWidthKey);
            localStorage.removeItem(alarmCenterWidthKey);
        } catch (_error) {
            // Reset still applies for this page load.
        }
        applyAlarmPaneWidths(true);
    });
});

async function loadAlarmSummary() {
    const summary = document.getElementById("alarm-summary");
    const body = document.getElementById("alarm-summary-body");
    summary.classList.remove("hidden");
    body.replaceChildren();
    const response = await fetch("/api/alarms");
    const data = await response.json();
    if (!response.ok || !data.success) {
        document.getElementById("alarm-summary-count").textContent = "Unavailable";
        return;
    }
    document.getElementById("alarm-summary-count").textContent = `${data.alarms.length} alarms`;
    usedAlarmMp3 = new Map();
    data.alarms.filter((alarm) => alarm.mp3_file).forEach((alarm) => {
        const key = alarm.mp3_file.toLocaleLowerCase();
        const alarmIds = usedAlarmMp3.get(key) || new Set();
        alarmIds.add(Number(alarm.alarm_id));
        usedAlarmMp3.set(key, alarmIds);
    });
    if (alarmMp3Loaded) renderAlarmMp3Options();
    data.alarms.forEach((alarm) => {
        const row = document.createElement("tr");
        row.dataset.tagid = alarm.tag_id;
        row.dataset.alarmId = String(alarm.alarm_id);
        row.className = alarm.enable_alarm ? "alarm-enabled" : "alarm-disabled";
        row.classList.toggle("selected-mapping", Number(selectedAlarm?.alarm_id) === Number(alarm.alarm_id));
        row.tabIndex = 0;
        row.setAttribute("role", "button");
        row.setAttribute("aria-label", `Open alarm mapping for ${alarm.tag_path}`);
        const tag = document.createElement("td");
        const tagName = document.createElement("strong");
        tagName.textContent = String(alarm.tag_path || "").split("/").filter(Boolean).pop() || alarm.tag_path;
        const tagPath = document.createElement("span");
        tagPath.className = "mapping-tag-path";
        tagPath.textContent = alarm.tag_path;
        tag.append(tagName, tagPath);
        row.appendChild(tag);
        row.addEventListener("click", () => selectMappedAlarm(alarm));
        row.addEventListener("keydown", (event) => {
            if (event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                selectMappedAlarm(alarm);
            }
        });
        body.appendChild(row);
    });
}

document.querySelectorAll(".alarm-filter-button").forEach((button) => {
    button.addEventListener("click", async () => {
        document.querySelectorAll(".alarm-filter-button").forEach((item) => item.classList.toggle("active", item === button));
        const alarmOnly = button.dataset.alarmFilter === "alarm";
        document.getElementById("runtime-kepware-tree-host").classList.toggle("hidden", alarmOnly);
        if (alarmOnly) await loadAlarmSummary();
    });
});

function selectMappedAlarm(alarm) {
    selectedRuntimeTag = {
        path: alarm.tag_path,
        tagId: Number(alarm.tag_id),
        nodeId: alarm.node_id || "",
        dataType: alarm.data_type || "",
    };
    document.getElementById("selected-tag-path").value = selectedRuntimeTag.path;
    document.getElementById("selected-tag-node-id").value = selectedRuntimeTag.nodeId;
    document.querySelectorAll("#alarm-summary-body tr").forEach((row) => {
        row.classList.toggle("selected-mapping", Number(row.dataset.alarmId) === Number(alarm.alarm_id));
    });
    const loadedTag = document.querySelector(`.kepware-object[data-canonical-path="${CSS.escape(alarm.tag_path)}"]`);
    if (loadedTag) {
        document.querySelectorAll(".kepware-object").forEach((item) => item.classList.remove("selected-object"));
        loadedTag.classList.add("selected-object");
        loadedTag.scrollIntoView({ block: "nearest" });
    }
    showAlarmForm(alarm);
    loadOperationalTagContext(knowledgeNodeFromAlarm(alarm));
}

function alarmNumber(id) {
    const value = document.getElementById(id).value;
    return value === "" ? null : Number(value);
}

function selectedAlarmMp3() {
    return selectedMp3;
}

function updateAlarmSaveReadiness() {
    const ready = Boolean(selectedRuntimeTag?.path);
    document.getElementById("save-alarm").disabled = !ready;
    document.getElementById("alarm-selected-mp3").value = selectedMp3;
    document.getElementById("alarm-audio-options").classList.toggle("hidden", !selectedMp3);
}

async function loadAlarmMp3(selected = "") {
    const response = await fetch("/api/alarm-mp3");
    const data = await response.json();
    alarmMp3Files = data.files || [];
    alarmMp3Loaded = true;
    renderAlarmMp3Options(selected);
}

function renderAlarmMp3Options(selected = selectedMp3) {
    const list = document.getElementById("alarm-selected-mp3");
    const currentAlarmId = Number(selectedAlarm?.alarm_id || 0);
    const rows = alarmMp3Files.map((file) => {
        const row = document.createElement("option");
        row.value = file.filename;
        const usedByAlarmIds = usedAlarmMp3.get(file.filename.toLocaleLowerCase()) || new Set();
        const usedByAnotherAlarm = [...usedByAlarmIds].some((alarmId) => alarmId !== currentAlarmId);
        row.disabled = usedByAnotherAlarm;
        row.textContent = usedByAnotherAlarm ? `${file.filename} - already used by an alarm` : file.filename;
        return row;
    });
    const exists = alarmMp3Files.some((file) => file.filename === selected);
    const selectedUsedByIds = usedAlarmMp3.get(selected.toLocaleLowerCase()) || new Set();
    const selectedUsedByAnotherAlarm = [...selectedUsedByIds].some((alarmId) => alarmId !== currentAlarmId);
    if (selectedUsedByAnotherAlarm) selectedMp3 = "";
    else selectedMp3 = selected || "";
    if (selected && !exists && selectedAlarm) {
        const missing = document.createElement("option");
        missing.value = selected;
        missing.textContent = `${selected} (missing — retained legacy value)`;
        rows.push(missing);
        selectedMp3 = selected;
    }
    const blank = document.createElement("option");
    blank.value = "";
    blank.textContent = "- Sound not selected -";
    list.replaceChildren(blank, ...rows);
    list.value = selectedMp3;
    updateAlarmSaveReadiness();
    const warning = document.getElementById("alarm-mp3-warning");
    warning.classList.toggle("hidden", !selected || exists);
    warning.textContent = selected && !exists
        ? `Mapped file “${selected}” is missing from this browse repository. It remains unchanged unless you select another file.`
        : "";
}

document.getElementById("alarm-selected-mp3").addEventListener("change", (event) => {
    selectedMp3 = event.target.value;
    updateAlarmSaveReadiness();
});
function showAlarmForm(alarm) {
    const pendingMp3 = selectedMp3;
    selectedAlarm = alarm;
    document.getElementById("use-tag-as-alarm").classList.add("hidden");
    document.getElementById("alarm-form").classList.remove("hidden");
    document.getElementById("alarm-id").value = alarm?.alarm_id || "";
    document.getElementById("alarm-enable").checked = alarm?.enable_alarm ?? true;
    const modeSelect = document.getElementById("alarm-mode");
    modeSelect.querySelectorAll("option[data-unsupported='true']").forEach((option) => option.remove());
    if (alarm && alarm.runtime_supported === false) {
        const unsupported = document.createElement("option");
        unsupported.value = alarm.alarm_mode;
        unsupported.textContent = `${alarm.alarm_mode} (unsupported by current alarm_sound)`;
        unsupported.dataset.unsupported = "true";
        unsupported.selected = true;
        unsupported.disabled = true;
        modeSelect.appendChild(unsupported);
    } else {
        modeSelect.value = alarm?.alarm_mode || "HIGH";
    }
    document.getElementById("alarm-threshold-high").value = alarm?.threshold_high ?? "";
    document.getElementById("alarm-threshold-low").value = alarm?.threshold_low ?? "";
    document.getElementById("alarm-priority").value = alarm?.priority ?? 1;
    document.getElementById("alarm-repeat").value = alarm?.repeat ?? 3;
    document.getElementById("delete-alarm").classList.toggle("hidden", !alarm);
    loadAlarmMp3(alarm?.mp3_file ?? pendingMp3);
    updateAlarmSaveReadiness();
}

async function loadTagAlarm(tagId) {
    const status = document.getElementById("alarm-status");
    status.textContent = "Loading Alarm configuration…";
    document.getElementById("alarm-form").classList.add("hidden");
    document.getElementById("use-tag-as-alarm").classList.add("hidden");
    try {
        const response = await fetch(`/api/opc-tags/${encodeURIComponent(tagId)}/alarm`);
        const data = await response.json();
        if (!response.ok || !data.success) throw new Error(data.error || "Alarm read failed");
        if (!data.alarm) {
            selectedAlarm = null;
            status.textContent = "Not configured";
            document.getElementById("use-tag-as-alarm").classList.remove("hidden");
            return;
        }
        status.textContent = data.alarm.tag_path_consistent
            ? "🔔 Alarm configured"
            : "🔔 Alarm configured — stored TagPath differs from canonical TagMaster Path";
        showAlarmForm(data.alarm);
    } catch (_error) {
        status.textContent = "Alarm configuration could not be loaded.";
    }
}

async function selectKepwareAlarmTag(node) {
    const tagDetails = node.tag_details || {};
    const canonicalPath = [
        node.context.channel,
        node.context.device,
        ...(node.context.group_path || []),
        node.name,
    ].join("/");
    selectedRuntimeTag = {
        path: canonicalPath,
        tagId: null,
        nodeId: tagDetails.node_id || "",
        dataType: tagDetails.data_type ?? "",
    };
    loadOperationalTagContext(node);
    showAlarmForm(null);
    document.getElementById("selected-tag-path").value = canonicalPath;
    document.getElementById("selected-tag-node-id").value = selectedRuntimeTag.nodeId || "Available after registration";
    const status = document.getElementById("alarm-status");
    status.textContent = "Checking TagMaster registration...";
    document.getElementById("use-tag-as-alarm").classList.add("hidden");
    try {
        const response = await fetch(`/api/opc-tags/resolve/by-path?path=${encodeURIComponent(canonicalPath)}`);
        const data = await response.json();
        if (!response.ok || !data.success) throw new Error("Tag lookup failed");
        if (!data.registered) {
            selectedAlarm = null;
            status.textContent = "Not registered - it will be registered when the Alarm is saved.";
            showAlarmForm(null);
            return;
        }
        selectedRuntimeTag.tagId = Number(data.tag.tag_id);
        selectedRuntimeTag.nodeId = data.tag.node_id || selectedRuntimeTag.nodeId;
        selectedRuntimeTag.dataType = data.tag.data_type ?? selectedRuntimeTag.dataType;
        document.getElementById("selected-tag-node-id").value = selectedRuntimeTag.nodeId || "Unknown";
        if (data.alarm) {
            status.textContent = "Alarm configured";
            showAlarmForm(data.alarm);
        } else {
            selectedAlarm = null;
            status.textContent = "Registered - no Alarm configured";
            showAlarmForm(null);
        }
    } catch (_error) {
        status.textContent = "Tag registration status unavailable.";
    }
}

document.getElementById("use-tag-as-alarm").addEventListener("click", () => showAlarmForm(null));

document.getElementById("alarm-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!selectedRuntimeTag?.path) return;
    const result = document.getElementById("alarm-result");
    const payload = {
        alarm_mode: document.getElementById("alarm-mode").value || "HIGH",
        threshold_high: alarmNumber("alarm-threshold-high"),
        threshold_low: alarmNumber("alarm-threshold-low"),
        mp3_file: selectedAlarmMp3(),
        priority: Number(document.getElementById("alarm-priority").value || "1"),
        repeat: Number(document.getElementById("alarm-repeat").value || "3"),
        enable_alarm: document.getElementById("alarm-enable").checked,
    };
    const alarmId = document.getElementById("alarm-id").value;
    if (!alarmId && !selectedRuntimeTag.tagId) {
        const syncResponse = await fetch("/api/opc-tags/sync-one", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ path: selectedRuntimeTag.path, confirm: "SYNC_ONE_EXISTING_TAG" }),
        });
        const syncData = await syncResponse.json();
        if (!syncResponse.ok || !syncData.success) {
            result.className = "create-result error-message";
            result.classList.remove("hidden");
            result.textContent = `Exact Tag Registration Failed\n${syncData.error || "Tag registration failed."}`;
            return;
        }
        selectedRuntimeTag.tagId = Number(syncData.tag_id);
        selectedRuntimeTag.nodeId = syncData.node_id || "";
        selectedRuntimeTag.dataType = syncData.data_type ?? "";
        document.getElementById("selected-tag-node-id").value = selectedRuntimeTag.nodeId || "Unknown";
    }
    if (!alarmId) payload.tag_id = selectedRuntimeTag.tagId;
    const response = await fetch(alarmId ? `/api/alarms/${alarmId}` : "/api/alarms", {
        method: alarmId ? "PUT" : "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
    });
    const data = await response.json();
    result.classList.remove("hidden");
    if (!response.ok || !data.success) {
        result.className = "create-result error-message";
        result.textContent = `Mapping Save          Failed\nAlarm Reload         Not attempted\n${data.error || "Alarm save failed."}`;
        return;
    }
    result.className = data.reload_notified ? "create-result success-message" : "create-result warning-message";
    result.textContent = data.reload_notified
        ? "Mapping Save          Succeeded\nAlarm Reload         Succeeded"
        : `Mapping Save          Succeeded\nAlarm Reload         ${data.reload_error === "disabled" ? "Disabled" : `Failed (${data.reload_error || "unknown"})`}`;
    await loadAlarmSummary();
    await loadTagAlarm(selectedRuntimeTag.tagId);
});

async function deleteAlarmMapping(alarm) {
    const result = document.getElementById("alarm-result");
    result.classList.remove("hidden");
    if (!alarm?.alarm_id || !window.confirm(`Delete Alarm mapping for ${alarm.tag_path}?`)) return;
    const alarmId = Number(alarm.alarm_id);
    try {
        const response = await fetch(`/api/alarms/${encodeURIComponent(alarmId)}`, { method: "DELETE" });
        const data = await response.json();
        if (!response.ok || !data.success) {
            throw new Error(data.error || `Delete request failed with HTTP ${response.status}.`);
        }
        const deletingSelectedAlarm = Number(selectedAlarm?.alarm_id) === alarmId;
        if (deletingSelectedAlarm) {
            selectedAlarm = null;
            selectedMp3 = "";
            document.getElementById("alarm-form").classList.add("hidden");
            document.getElementById("alarm-status").textContent = "Not configured";
            document.getElementById("alarm-selected-mp3").value = "";
            document.getElementById("use-tag-as-alarm").classList.remove("hidden");
            updateAlarmSaveReadiness();
        }
        result.className = data.reload_notified ? "create-result success-message" : "create-result warning-message";
        result.textContent = data.reload_notified
            ? "Mapping Delete        Succeeded\nAlarm Reload         Succeeded"
            : `Mapping Delete        Succeeded\nAlarm Reload         ${data.reload_error === "disabled" ? "Disabled" : `Failed (${data.reload_error || "unknown"})`}`;
        await loadAlarmSummary();
    } catch (error) {
        result.className = "create-result error-message";
        result.textContent = `Mapping Delete        Failed\n${error.message || "Alarm delete failed."}`;
    }
}

document.getElementById("delete-alarm").addEventListener("click", () => deleteAlarmMapping(selectedAlarm));
document.getElementById("test-alarm").addEventListener("click", () => {
    previewAlarmMp3(selectedMp3);
});

function previewAlarmMp3(filename) {
    if (!filename) return;
    const audio = document.getElementById("alarm-preview-audio");
    audio.src = `/api/alarm-mp3/${encodeURIComponent(filename)}/preview`;
    audio.classList.remove("hidden");
    audio.play();
}

document.getElementById("preview-alarm-mp3").addEventListener("click", () => {
    previewAlarmMp3(selectedMp3);
});

const viewTabs = document.querySelectorAll(".view-tab");
let kepwareLoaded = false;
let loadedCounts = { channels: 0, devices: 0, tag_groups: 0, tags: 0 };
const kepwareWriteEnabled =
    document.getElementById("kepware-tree-view").dataset.writeEnabled === "true";
const kepwareTreeView = document.getElementById("kepware-tree-view");
const kepwareTree = document.getElementById("kepware-tree");
const configurationKepwareTreeHost = document.getElementById("configuration-kepware-tree-host");
const runtimeKepwareTreeHost = document.getElementById("runtime-kepware-tree-host");
const runtimeSecondaryHost = document.getElementById("runtime-secondary-host");
const operatorHealth = document.querySelector(".operator-health");
const diagnosticsPanel = document.querySelector(".diagnostics-panel");
const runtimeKnowledgeHost = document.getElementById("runtime-knowledge-host");
const opcRuntimeWorkspace = document.getElementById("opc-runtime-workspace");
const alarmHelpWorkspace = document.getElementById("alarm-help-workspace");
let opcRuntimePollTimer = null;
let opcRuntimeRequestPending = false;
runtimeKnowledgeHost.append(
    document.getElementById("tag-knowledge-panel"),
    document.getElementById("tag-resources-panel"),
);
const kmTagWriteEnabled = kepwareTreeView.dataset.kmWriteEnabled === "true";
const kmResourceWriteEnabled = kepwareTreeView.dataset.kmResourceWriteEnabled === "true";
const configuredTagDefaults = {
    dataType: Number.parseInt(kepwareTreeView.dataset.defaultDataType, 10),
    scanRate: Number.parseInt(kepwareTreeView.dataset.defaultScanRate, 10),
    access: Number.parseInt(kepwareTreeView.dataset.defaultAccess, 10),
};
let selectedDestinationNode = null;
let selectedDestinationDetails = null;
let selectedDestinationChildren = null;
let selectedTemplateCandidate = null;
let templateSourcePath = "";
let selectedKnowledgeTag = null;
let pendingKnowledgePayload = null;
const knowledgeSectionLabels = {
    description: "Description / Meaning", possible_cause: "Possible Cause",
    how_to_check: "How to Check / Troubleshooting", corrective_action: "Corrective Action",
    safety_warning: "Safety / Warning", additional_notes: "Additional Notes",
};
const visibleKnowledgeSections = ["how_to_check", "corrective_action", "safety_warning", "additional_notes"];
let knowledgeAttachments = Object.fromEntries(Object.keys(knowledgeSectionLabels).map((key) => [key, []]));
let resourceForLinking = null;
let resourceTargetTags = new Map();
let resourceTagSelectionMode = false;
let pendingSimilarUpload = null;

viewTabs.forEach((tab) => {
    tab.addEventListener("click", () => {
        const isKepware = tab.dataset.view === "kepware";
        const isOpcRuntime = tab.dataset.view === "opc-runtime";
        const isAlarmHelp = tab.dataset.view === "alarm-help";
        viewTabs.forEach((item) => item.classList.toggle("active", item === tab));
        document.getElementById("runtime-tree-view").classList.toggle("hidden", isKepware);
        document.getElementById("kepware-tree-view").classList.toggle("hidden", !isKepware);
        document.getElementById("runtime-details-view").classList.toggle("hidden", isKepware);
        document.getElementById("kepware-details-view").classList.toggle("hidden", !isKepware);
        document.getElementById("full-reconcile").classList.toggle("hidden", isKepware);
        workspace.classList.toggle("runtime-mode", !isKepware);
        alarmTopWorkspace.classList.toggle("hidden", isKepware || isOpcRuntime || isAlarmHelp);
        tagConfigurationWorkspace.classList.toggle("hidden", !isKepware);
        opcRuntimeWorkspace.classList.toggle("hidden", !isOpcRuntime);
        alarmHelpWorkspace.classList.toggle("hidden", !isAlarmHelp);
        if (!isOpcRuntime && !isAlarmHelp) {
            (isKepware ? tagConfigurationWorkspace : alarmTopWorkspace).appendChild(workspace);
        }
        mainPanelSplitter.classList.toggle("hidden", isKepware);
        alarmCenterSplitter.classList.toggle("hidden", isOpcRuntime || isAlarmHelp);
        document.getElementById("alarm-summary").classList.toggle("hidden", isKepware || isOpcRuntime || isAlarmHelp);
        alarmHorizontalSplitter.classList.toggle("hidden", isKepware || isOpcRuntime || isAlarmHelp);
        runtimeSecondaryHost.classList.toggle("hidden", isKepware || isOpcRuntime || isAlarmHelp);
        (isKepware ? configurationKepwareTreeHost : runtimeKepwareTreeHost).appendChild(kepwareTree);

        if (!kepwareLoaded && !isAlarmHelp) {
            kepwareLoaded = true;
            loadKepwareChannels();
        }
        if (isKepware) {
            applyAlarmTopHeight();
            applyMainPanelRatio();
        }
        if (!isKepware && !isOpcRuntime && !isAlarmHelp) {
            applyAlarmPaneWidths();
            applyAlarmTopHeight();
            runtimeSecondaryHost.append(operatorHealth, diagnosticsPanel);
            loadRuntimeStatus();
            loadAlarmMp3();
            loadAlarmSummary();
        }
        if (isOpcRuntime) {
            startOpcRuntimePolling();
        } else {
            stopOpcRuntimePolling();
        }
        if (isAlarmHelp) startAlarmHelpPolling();
        else stopAlarmHelpPolling();
    });
});

document.getElementById("full-reconcile").addEventListener("click", async event => {
    const button = event.currentTarget;
    const result = document.getElementById("reconcile-result");
    if (!window.confirm("Run a complete OPC browse and safely reconcile TagMaster/TagLevel?\n\nThe historian subscriber will NOT be synchronized in this slice.")) {
        return;
    }
    button.disabled = true;
    result.textContent = "Full Reconcile is running. Subscriber synchronization will not be changed.";
    try {
        const response = await fetch("/api/runtime/full-reconcile", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ confirm: "FULL_RECONCILE" }),
        });
        const data = await response.json();
        if (!response.ok || !data.success) {
            result.textContent = `Full Reconcile failed: ${data.error || "unknown error"}`;
            return;
        }
        result.textContent = `Run ${data.run_id}: ${data.total_discovered} discovered, ${data.added} added, ${data.changed} changed, ${data.unchanged} unchanged, ${data.deactivated} inactive. Subscriber not synchronized.`;
        await loadRuntimeStatus();
    } catch (_error) {
        result.textContent = "Full Reconcile request failed before a result was returned.";
    } finally {
        button.disabled = false;
    }
});

async function fetchWithTimeout(url, timeoutMs = 5000) {
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), timeoutMs);
    try {
        return await fetch(url, { signal: controller.signal });
    } finally {
        window.clearTimeout(timeout);
    }
}

async function loadRuntimeStatus() {
    try {
        const response = await fetchWithTimeout("/api/runtime/status");
        if (!response.ok) throw new Error("Runtime status unavailable");
        const data = await response.json();
        document.getElementById("development-historian-runtime").textContent =
            `${data.development_historian_runtime || "unknown"} / ${data.worker_state || "unknown"}`;
        document.getElementById("production-historian-owner").textContent = data.production_historian_owner || "unknown";
        document.getElementById("supervisor-state").textContent = data.supervisor_enabled ? "Enabled" : "Disabled";
        document.getElementById("worker-state").textContent = data.worker_state || "unknown";
        document.getElementById("worker-pid").textContent = data.worker_pid ?? "None";
        document.getElementById("runtime-opc-state").textContent = data.opc_state || "unknown";
        document.getElementById("runtime-tag-count").textContent =
            data.tagmaster_active_count == null ? "Unknown" : `${data.tagmaster_active_count} Active`;
        document.getElementById("runtime-subscriber-count").textContent =
            data.subscribed_tag_count == null ? "Unknown" : data.subscribed_tag_count;
        document.getElementById("runtime-requested-count").textContent = data.requested_subscription_count ?? "Unknown";
        document.getElementById("runtime-failed-count").textContent = data.failed_subscription_count ?? "Unknown";
        document.getElementById("runtime-subscription-complete").textContent = data.subscription_complete ? "Yes" : "No";
        document.getElementById("runtime-influx-state").textContent = data.influx_state || "unknown";
        document.getElementById("runtime-rebuild-state").textContent = data.rebuild_pending ? "Pending" : "No pending rebuild";
        document.getElementById("runtime-registry-generation").textContent = data.registry_generation ?? "Unknown";
        document.getElementById("runtime-ack-generation").textContent = data.acknowledged_generation ?? "Unknown";
        document.getElementById("runtime-last-write").textContent = data.last_write_time || "None";
        document.getElementById("runtime-restart-count").textContent = data.restart_count ?? "Unknown";
        document.getElementById("runtime-last-error").textContent = data.last_error || "None";
        document.getElementById("operator-opc-state").textContent =
            data.opc_state === "connected" ? "Connected" : "Disconnected";
        document.getElementById("operator-historian-state").textContent =
            ["running", "rebuilding", "starting"].includes(data.worker_state) ? "Running" : "Stopped";
        document.getElementById("operator-tag-count").textContent =
            data.tagmaster_active_count == null ? "Unknown" : data.tagmaster_active_count;
        document.getElementById("operator-last-error").textContent = data.last_error || "None";
    } catch (_error) {
        document.getElementById("worker-state").textContent = "status unavailable";
        document.getElementById("operator-opc-state").textContent = "Disconnected";
        document.getElementById("operator-historian-state").textContent = "Stopped";
        document.getElementById("operator-tag-count").textContent = "Unknown";
        document.getElementById("operator-last-error").textContent = "Status unavailable";
    }
}

function activityTime(value) {
    if (!value) return "--:--:--";
    const parsed = new Date(value);
    return Number.isNaN(parsed.getTime()) ? String(value) : parsed.toLocaleTimeString();
}

function activityValue(value) {
    if (value === null || value === undefined) return "null";
    if (typeof value === "string") return value;
    try { return JSON.stringify(value); } catch (_error) { return String(value); }
}

function replaceActivityList(id, entries, formatter) {
    const container = document.getElementById(id);
    const fragment = document.createDocumentFragment();
    [...(entries || [])].reverse().forEach((entry) => {
        const row = document.createElement("div");
        row.className = "runtime-activity-entry";
        const rendered = formatter(entry);
        rendered.forEach((line, index) => {
            const element = document.createElement(index === 0 ? "strong" : "span");
            element.textContent = line;
            row.appendChild(element);
        });
        fragment.appendChild(row);
    });
    if (!fragment.childNodes.length) {
        const empty = document.createElement("p");
        empty.className = "tree-counts";
        empty.textContent = "No activity received in this session.";
        fragment.appendChild(empty);
    }
    container.replaceChildren(fragment);
}

function renderOpcRuntimeActivity(data) {
    const runtime = data.runtime || {};
    const requested = Number(runtime.requested_subscription_count || 0);
    const loaded = Number(runtime.active_tag_count || 0);
    const subscribed = Number(runtime.subscribed_tag_count || 0);
    const failed = Number(runtime.failed_subscription_count || 0);
    const attempted = subscribed + failed;
    const progress = requested ? Math.min(100, Math.round((attempted / requested) * 100)) : 0;
    document.getElementById("activity-worker-state").textContent = runtime.worker_state || "Unknown";
    document.getElementById("activity-opc-state").textContent = runtime.opc_state || "Unknown";
    document.getElementById("activity-requested-count").textContent = `${loaded} / ${requested}`;
    document.getElementById("activity-subscribed-count").textContent = subscribed;
    document.getElementById("activity-failed-count").textContent = failed;
    document.getElementById("activity-subscription-progress").textContent = `${progress}%`;

    replaceActivityList("subscription-activity-list", data.subscription, (entry) => [
        `${activityTime(entry.time)}  ${String(entry.event || "runtime").replaceAll("_", " ").toUpperCase()}`,
        entry.error || [
            entry.requested_subscription_count != null ? `requested=${entry.requested_subscription_count}` : "",
            entry.subscribed_tag_count != null ? `subscribed=${entry.subscribed_tag_count}` : "",
            entry.failed_subscription_count != null ? `failed=${entry.failed_subscription_count}` : "",
            entry.state ? `state=${entry.state}` : "",
        ].filter(Boolean).join("  ") || "Historian runtime event",
    ]);

    replaceActivityList("influx-activity-list", data.influx, (entry) => [
        `${activityTime(entry.time)}  ${entry.result || (entry.success ? "WRITE OK" : "WRITE FAILED")}`,
        `Database: ${entry.database || "Unknown"}`,
        `Path: ${entry.path || "Unknown"}`,
        `Value: ${activityValue(entry.value)}`,
        ...(entry.error ? [`Error: ${entry.error}`] : []),
    ]);

    const summary = data.summary || {};
    document.getElementById("activity-alarm-configured").textContent = summary.configured_alarm_tags ?? 0;
    document.getElementById("activity-alarm-active").textContent = summary.active_alarms ?? 0;
    document.getElementById("activity-alarm-events").textContent = summary.alarm_events_session ?? 0;
    document.getElementById("activity-alarm-last-event").textContent = activityTime(summary.last_alarm_event);
    document.getElementById("activity-alarm-last-path").textContent = summary.last_alarm_path || "None";
    document.getElementById("activity-alarm-state").textContent = summary.alarm_activity_state || "Unknown";
    replaceActivityList("alarm-activity-list", data.alarm, (entry) => [
        `${activityTime(entry.time)}  ${entry.state || "NORMAL"}`,
        `Path: ${entry.path || "Unknown"}`,
        `Value: ${activityValue(entry.value)}  Mode: ${entry.alarm_mode || "Unknown"}`,
        `High: ${activityValue(entry.threshold_high)}  Low: ${activityValue(entry.threshold_low)}`,
        `Priority: ${entry.priority ?? ""}  MP3: ${entry.mp3_file || ""}`,
        `EnableAlarm: ${entry.enable_alarm ? "Yes" : "No"}`,
    ]);
}

async function loadOpcRuntimeActivity() {
    if (opcRuntimeRequestPending) return;
    opcRuntimeRequestPending = true;
    try {
        const response = await fetchWithTimeout("/api/runtime/activity");
        const data = await response.json();
        if (!response.ok || !data.success) throw new Error("Runtime activity unavailable");
        renderOpcRuntimeActivity(data);
    } catch (_error) {
        document.getElementById("activity-alarm-state").textContent = "Unavailable";
    } finally {
        opcRuntimeRequestPending = false;
    }
}

function startOpcRuntimePolling() {
    loadOpcRuntimeActivity();
    if (opcRuntimePollTimer === null) {
        opcRuntimePollTimer = window.setInterval(loadOpcRuntimeActivity, 1000);
    }
}

function stopOpcRuntimePolling() {
    if (opcRuntimePollTimer !== null) {
        window.clearInterval(opcRuntimePollTimer);
        opcRuntimePollTimer = null;
    }
}

let alarmHelpTimer = null;
let alarmHelpViewingHistory = false;
let alarmHelpSelectedHistoryId = null;
let alarmHelpLatestKey = null;
let alarmHelpRequestPending = false;

function alarmHelpEventKey(alarm) {
    if (!alarm) return null;
    return alarm.history_id != null
        ? `history:${alarm.history_id}`
        : `live:${alarm.alarm_id}:${alarm.activated_at || ""}`;
}

function alarmHelpText(value) {
    return value === null || value === undefined || value === "" ? "—" : String(value);
}

function renderAlarmHelpEndpointUrls(historyId = alarmHelpSelectedHistoryId) {
    document.querySelectorAll("[data-endpoint-path]").forEach((input) => {
        let path = input.dataset.endpointPath;
        if (input.id === "alarm-help-endpoint-history" && historyId != null) {
            path = path.replace("{history_id}", String(historyId));
        }
        input.value = `${window.location.origin}${path}`;
    });
}

function renderAlarmHelpDetail(data) {
    const status = document.getElementById("alarm-help-status");
    const content = document.getElementById("alarm-help-content");
    if (!data?.has_alarm || !data.alarm) {
        status.textContent = "No alarm event available";
        status.className = "tree-counts";
        content.classList.add("hidden");
        return;
    }
    const alarm = data.alarm;
    status.textContent = "";
    content.classList.remove("hidden");
    document.getElementById("alarm-help-name").textContent = alarmHelpText(alarm.tag_name);
    document.getElementById("alarm-help-path").textContent = alarmHelpText(alarm.kepware_path);
    document.getElementById("alarm-help-activated").textContent = alarmHelpText(alarm.activated_at);
    document.getElementById("alarm-help-priority").textContent = alarmHelpText(alarm.priority);
    document.getElementById("alarm-help-state").textContent = alarmHelpText(alarm.state);
    document.getElementById("alarm-help-value").textContent = alarmHelpText(alarm.value);
    const host = document.getElementById("alarm-help-knowledge");
    host.replaceChildren();
    if (!data.knowledge?.has_knowledge) {
        const empty = document.createElement("p");
        empty.className = "tree-counts";
        empty.textContent = "No Tag Knowledge";
        host.appendChild(empty);
    } else {
        const labels = {
            description: "Description / Meaning",
            how_to_check: "How to Check / Troubleshooting",
            corrective_action: "Corrective Action",
            safety_warning: "Safety / Warning",
            additional_notes: "Additional Notes",
        };
        Object.entries(labels).forEach(([key, label]) => {
            const section = data.knowledge.sections?.[key];
            if (!section?.text && !(section?.images || []).length) return;
            const block = document.createElement("section");
            block.className = "alarm-help-section";
            const heading = document.createElement("h3");
            heading.textContent = label;
            block.appendChild(heading);
            if (section.text) {
                const text = document.createElement("p");
                text.textContent = section.text;
                block.appendChild(text);
            }
            const images = document.createElement("div");
            images.className = "alarm-help-images";
            (section.images || []).forEach((attachment) => {
                const figure = document.createElement("figure");
                const image = document.createElement("img");
                image.src = attachment.url;
                image.alt = attachment.caption || label;
                figure.appendChild(image);
                if (attachment.caption) {
                    const caption = document.createElement("figcaption");
                    caption.textContent = attachment.caption;
                    figure.appendChild(caption);
                }
                images.appendChild(figure);
            });
            block.appendChild(images);
            host.appendChild(block);
        });
    }
    document.getElementById("alarm-help-json").textContent = JSON.stringify(data, null, 2);
}

async function loadAlarmHelpLatest() {
    try {
        const response = await fetch("/api/alarm-help/latest");
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || "Latest alarm unavailable");
        const nextKey = alarmHelpEventKey(data.alarm);
        if (alarmHelpViewingHistory) {
            if (nextKey && nextKey !== alarmHelpLatestKey) {
                document.getElementById("alarm-help-newer").classList.remove("hidden");
            }
        } else {
            renderAlarmHelpDetail(data);
        }
        alarmHelpLatestKey = nextKey;
    } catch (error) {
        if (!alarmHelpViewingHistory) {
            const status = document.getElementById("alarm-help-status");
            status.textContent = error.message || "Latest alarm unavailable";
            status.className = "error-message";
        }
    }
}

function renderAlarmHelpHistory(alarms) {
    const body = document.getElementById("alarm-help-history-body");
    const unique = new Map((alarms || []).map((alarm) => [String(alarm.history_id), alarm]));
    const rows = [...unique.values()].map((alarm) => {
        const row = document.createElement("tr");
        row.dataset.historyId = String(alarm.history_id);
        row.classList.toggle("selected-history", Number(alarmHelpSelectedHistoryId) === Number(alarm.history_id));
        [alarm.activated_at, alarm.tag_name, alarm.kepware_path, alarm.priority, alarm.state].forEach((value) => {
            const cell = document.createElement("td");
            cell.textContent = alarmHelpText(value);
            row.appendChild(cell);
        });
        row.addEventListener("click", () => loadAlarmHelpHistoryDetail(alarm.history_id));
        return row;
    });
    body.replaceChildren(...rows);
    document.getElementById("alarm-help-history-status").textContent = rows.length ? "" : "No alarm history";
}

async function loadAlarmHelpHistory() {
    try {
        const response = await fetch("/api/alarm-help/recent?limit=5");
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || "Alarm history unavailable");
        renderAlarmHelpHistory(data.alarms);
    } catch (error) {
        const status = document.getElementById("alarm-help-history-status");
        status.textContent = error.message || "Alarm history unavailable";
        status.className = "error-message";
    }
}

async function loadAlarmHelpHistoryDetail(historyId) {
    try {
        const response = await fetch(`/api/alarm-help/history/${encodeURIComponent(historyId)}`);
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || "Alarm history unavailable");
        alarmHelpViewingHistory = true;
        alarmHelpSelectedHistoryId = Number(historyId);
        renderAlarmHelpEndpointUrls(alarmHelpSelectedHistoryId);
        document.getElementById("alarm-help-back-latest").classList.remove("hidden");
        document.querySelectorAll("#alarm-help-history-body tr").forEach((row) => {
            row.classList.toggle("selected-history", Number(row.dataset.historyId) === Number(historyId));
        });
        renderAlarmHelpDetail(data);
    } catch (error) {
        const status = document.getElementById("alarm-help-status");
        status.textContent = error.message || "Alarm history unavailable";
        status.className = "error-message";
    }
}

async function refreshAlarmHelpAll() {
    if (alarmHelpRequestPending) return;
    alarmHelpRequestPending = true;
    try { await Promise.all([loadAlarmHelpLatest(), loadAlarmHelpHistory()]); }
    finally { alarmHelpRequestPending = false; }
}

function stopAlarmHelpPolling() {
    if (alarmHelpTimer !== null) window.clearInterval(alarmHelpTimer);
    alarmHelpTimer = null;
}

function startAlarmHelpPolling() {
    stopAlarmHelpPolling();
    refreshAlarmHelpAll();
    const seconds = Number(document.getElementById("alarm-help-auto-refresh").value);
    if (seconds > 0) alarmHelpTimer = window.setInterval(refreshAlarmHelpAll, seconds * 1000);
}

document.getElementById("alarm-help-refresh-latest").addEventListener("click", loadAlarmHelpLatest);
document.getElementById("alarm-help-refresh-history").addEventListener("click", loadAlarmHelpHistory);
document.getElementById("alarm-help-refresh-all").addEventListener("click", refreshAlarmHelpAll);
document.getElementById("alarm-help-auto-refresh").addEventListener("change", () => {
    if (!alarmHelpWorkspace.classList.contains("hidden")) startAlarmHelpPolling();
});
document.querySelectorAll(".alarm-help-copy-endpoint").forEach((button) => {
    button.addEventListener("click", async () => {
        const input = document.getElementById(`alarm-help-endpoint-${button.dataset.endpoint}`);
        const status = document.getElementById("alarm-help-copy-status");
        try {
            await navigator.clipboard.writeText(input.value);
            status.textContent = "API URL copied";
        } catch (_error) {
            status.textContent = "Unable to copy API URL";
        }
    });
});
document.getElementById("alarm-help-back-latest").addEventListener("click", async () => {
    alarmHelpViewingHistory = false;
    alarmHelpSelectedHistoryId = null;
    renderAlarmHelpEndpointUrls();
    document.getElementById("alarm-help-back-latest").classList.add("hidden");
    document.getElementById("alarm-help-newer").classList.add("hidden");
    document.querySelectorAll("#alarm-help-history-body tr").forEach((row) => row.classList.remove("selected-history"));
    await loadAlarmHelpLatest();
});
renderAlarmHelpEndpointUrls();

// Alarm authoring is the normal operator workflow on every full page load/refresh.
document.querySelector('.view-tab[data-view="runtime"]').click();

document.getElementById("refresh-kepware").addEventListener("click", async () => {
    await loadKepwareChannels(true);
});

async function loadKepwareChannels(refresh = false) {
    const status = document.getElementById("kepware-status");
    const error = document.getElementById("kepware-error");
    const button = document.getElementById("refresh-kepware");
    status.textContent = "Kepware API: Loading…";
    status.className = "connection-status pending";
    button.disabled = true;

    try {
        const response = await fetch(
            refresh ? "/api/kepware/refresh" : "/api/kepware/channels",
            { method: refresh ? "POST" : "GET" },
        );
        const data = await response.json();
        if (!data.connected) {
            showKepwareError(data.error);
            return;
        }

        status.textContent = "Kepware API: Connected";
        status.className = "connection-status connected";
        error.classList.add("hidden");
        loadedCounts = { channels: data.nodes.length, devices: 0, tag_groups: 0, tags: 0 };
        updateLoadedCounts();
        renderKepwareRoot(data.nodes);
        resetCreateTagPanel();
    } catch (_error) {
        showKepwareError("Unable to load Kepware Channels. You can retry.");
    } finally {
        button.disabled = false;
    }
}

function renderKepwareRoot(nodes) {
    const list = document.createElement("ul");
    list.className = "tree kepware-tree";
    nodes.forEach((node) => list.appendChild(createKepwareNode(node, null, null)));
    document.getElementById("kepware-tree").replaceChildren(list);
}

function createKepwareNode(node, parentDetails, parentChildren) {
    const item = document.createElement("li");
    const button = document.createElement("button");
    button.type = "button";
    button.className = "kepware-object";
    button.textContent = node.name;
    if (node.object_type === "Tag") {
        button.dataset.canonicalPath = [
            node.context.channel,
            node.context.device,
            ...(node.context.group_path || []),
            node.name,
        ].join("/");
        button.classList.toggle("selected-object", button.dataset.canonicalPath === selectedRuntimeTag?.path);
    }
    button.kepwareParentDetails = parentDetails;
    button.kepwareParentChildren = parentChildren;
    button.addEventListener("click", () => selectKepwareObject(button, node));

    const type = document.createElement("span");
    type.className = "object-type-label";
    type.textContent = `(${node.object_type})`;

    if (!node.expandable) {
        item.append(button, type);
        return item;
    }

    const details = document.createElement("details");
    const summary = document.createElement("summary");
    summary.append(button, type);
    details.appendChild(summary);

    const children = document.createElement("ul");
    children.className = "tree";
    details.appendChild(children);
    button.kepwareDetails = details;
    button.kepwareChildren = children;
    details.addEventListener("toggle", () => {
        if (details.open && details.dataset.loaded !== "true" && details.dataset.loading !== "true") {
            loadKepwareChildren(details, children, node);
        }
    });
    item.appendChild(details);
    return item;
}

async function loadKepwareChildren(details, container, node) {
    const wasLoaded = details.dataset.loaded === "true";
    details.dataset.loading = "true";
    const loading = document.createElement("li");
    loading.className = "loading-node";
    loading.textContent = "Loading…";
    if (!container.children.length) {
        container.appendChild(loading);
    }

    try {
        const response = await fetch(kepwareChildrenUrl(node), { method: "GET" });
        const data = await response.json();
        if (!data.connected) {
            showKepwareError(data.error);
            return;
        }

        const fragment = document.createDocumentFragment();
        data.nodes.forEach((child) => {
            fragment.appendChild(createKepwareNode(child, details, container));
        });
        container.replaceChildren(fragment);
        details.dataset.loaded = "true";
        if (!wasLoaded) addLoadedCounts(data.nodes);
        document.getElementById("kepware-error").classList.add("hidden");
        document.getElementById("kepware-status").textContent = "Kepware API: Connected";
        document.getElementById("kepware-status").className = "connection-status connected";
    } catch (_error) {
        showKepwareError("This Kepware node is temporarily unavailable. Collapse and expand it to retry.");
    } finally {
        loading.remove();
        details.dataset.loading = "false";
    }
}

function kepwareChildrenUrl(node) {
    const params = new URLSearchParams();
    params.append("channel", node.context.channel);
    if (node.object_type === "Channel") {
        return `/api/kepware/devices?${params}`;
    }

    params.append("device", node.context.device);
    if (node.object_type === "Device") {
        return `/api/kepware/device-children?${params}`;
    }

    node.context.group_path.forEach((group) => params.append("group_path", group));
    return `/api/kepware/group-children?${params}`;
}

function showKepwareError(message) {
    const status = document.getElementById("kepware-status");
    const error = document.getElementById("kepware-error");
    status.textContent = "Kepware API: Temporarily Unavailable";
    status.className = "connection-status disconnected";
    error.textContent = message || "Kepware Configuration API is unavailable.";
    error.classList.remove("hidden");
}

function addLoadedCounts(nodes) {
    nodes.forEach((node) => {
        const key = {
            Device: "devices",
            "Tag Group": "tag_groups",
            Tag: "tags",
        }[node.object_type];
        if (key) loadedCounts[key] += 1;
    });
    updateLoadedCounts();
}

function updateLoadedCounts() {
    const element = document.getElementById("kepware-counts");
    element.textContent = [
        `${loadedCounts.channels} channels loaded`,
        `${loadedCounts.devices} devices loaded`,
        `${loadedCounts.tag_groups} tag groups loaded`,
        `${loadedCounts.tags} tags loaded`,
    ].join(" · ");
    element.classList.remove("hidden");
}

function selectKepwareObject(button, node) {
    if (resourceTagSelectionMode && node.object_type === "Tag") {
        resourceTargetTags.set(node.full_path, node);
        renderResourceTargets();
    }
    document.querySelectorAll(".kepware-object").forEach((item) => {
        item.classList.remove("selected-object");
    });
    button.classList.add("selected-object");
    const runtimeViewActive = document.querySelector('.view-tab[data-view="runtime"]').classList.contains("active");
    if (runtimeViewActive) {
        if (node.object_type === "Tag") selectKepwareAlarmTag(node);
        return;
    }
    displayKepwareObject(node);

    if (node.object_type === "Device" || node.object_type === "Tag Group") {
        prepareAddTagPanel(
            node,
            button.kepwareDetails,
            button.kepwareChildren,
            null,
        );
        selectedTemplateCandidate = null;
        document.getElementById("use-tag-template").classList.add("hidden");
    } else if (node.object_type === "Tag") {
        resetCreateTagPanel();
        selectedTemplateCandidate = {
            node,
            parentDetails: button.kepwareParentDetails,
            parentChildren: button.kepwareParentChildren,
        };
        document.getElementById("use-tag-template").classList.toggle(
            "hidden",
            !kepwareWriteEnabled,
        );
    } else {
        resetCreateTagPanel();
        selectedTemplateCandidate = null;
        document.getElementById("use-tag-template").classList.add("hidden");
    }
}

function displayKepwareObject(node) {
    document.getElementById("kepware-no-selection").classList.add("hidden");
    document.getElementById("kepware-object-details").classList.remove("hidden");
    document.getElementById("kepware-object-type").textContent = node.object_type;
    document.getElementById("kepware-object-name").textContent = node.name;
    document.getElementById("kepware-object-path").textContent = node.full_path;
    document.getElementById("kepware-raw-properties").textContent = JSON.stringify(node.properties, null, 2);

    const tagDetails = node.tag_details || {};
    setTagProperty("kepware-tag-address", tagDetails.address);
    setTagProperty("kepware-tag-data-type", friendlyEnumValue("new-tag-data-type", tagDetails.data_type));
    setTagProperty("kepware-tag-scan-rate", tagDetails.scan_rate);
    setTagProperty("kepware-tag-description", tagDetails.description);
    setTagProperty("kepware-tag-access", friendlyEnumValue("new-tag-access", tagDetails.access));
}

function friendlyEnumValue(selectId, value) {
    const numeric = Number(value);
    const option = [...document.getElementById(selectId).options]
        .find((item) => Number(item.value) === numeric);
    return option ? `${option.textContent} (${numeric})` : `Unknown (${value})`;
}

function selectEnumValue(selectId, value) {
    const select = document.getElementById(selectId);
    const numeric = Number(value);
    let option = [...select.options].find((item) => Number(item.value) === numeric);
    if (!option) {
        option = new Option(`Unknown (${value})`, String(value));
        option.dataset.unknown = "true";
        select.add(option);
    }
    select.value = option.value;
}

function destinationPath(node) {
    return [
        node.context.channel,
        node.context.device,
        ...(node.context.group_path || []),
    ].join("/");
}

function resetCreateTagPanel() {
    selectedDestinationNode = null;
    selectedDestinationDetails = null;
    selectedDestinationChildren = null;
    document.getElementById("add-kepware-tag-panel").classList.add("hidden");
    document.getElementById("add-kepware-tag-form").reset();
    document.getElementById("create-tag-preview").classList.add("hidden");
    document.getElementById("tag-template-source").classList.add("hidden");
    templateSourcePath = "";
    selectedTemplateCandidate = null;
    document.getElementById("use-tag-template").classList.add("hidden");
}

function prepareAddTagPanel(node, details, children, templateTag) {
    selectedDestinationNode = node;
    selectedDestinationDetails = details;
    selectedDestinationChildren = children;
    document.getElementById("add-kepware-tag-panel").classList.remove("hidden");
    document.getElementById("add-tag-destination").textContent =
        `Destination: ${destinationPath(node)}`;
    document.getElementById("add-kepware-tag-form").reset();
    document.getElementById("new-tag-name").value = "";
    document.getElementById("new-tag-address").value = "";
    selectEnumValue("new-tag-data-type", templateTag?.tag_details?.data_type ?? configuredTagDefaults.dataType);
    document.getElementById("new-tag-scan-rate").value =
        templateTag?.tag_details?.scan_rate ?? configuredTagDefaults.scanRate;
    selectEnumValue("new-tag-access", templateTag?.tag_details?.access ?? configuredTagDefaults.access);
    document.getElementById("new-tag-description").value =
        templateTag?.properties?.["common.ALLTYPES_DESCRIPTION"] ?? "";
    templateSourcePath = templateTag?.full_path || "";
    const source = document.getElementById("tag-template-source");
    source.textContent = templateSourcePath
        ? `Template source: ${templateSourcePath}`
        : "Using visible configured defaults";
    source.classList.remove("hidden");
    document.getElementById("create-tag-preview").classList.add("hidden");
    document.getElementById("create-tag-result").classList.add("hidden");
}

document.getElementById("use-tag-template").addEventListener("click", () => {
    if (!selectedTemplateCandidate || !kepwareWriteEnabled) return;
    const source = selectedTemplateCandidate.node;
    const groups = source.context.group_path || [];
    const destination = {
        object_type: groups.length ? "Tag Group" : "Device",
        name: groups.length ? groups[groups.length - 1] : source.context.device,
        full_path: [source.context.channel, source.context.device, ...groups].join("."),
        context: source.context,
    };
    prepareAddTagPanel(
        destination,
        selectedTemplateCandidate.parentDetails,
        selectedTemplateCandidate.parentChildren,
        source,
    );
});

document.getElementById("add-kepware-tag-form").addEventListener("submit", (event) => {
    event.preventDefault();
    if (!kepwareWriteEnabled || !selectedDestinationNode) return;

    const name = document.getElementById("new-tag-name").value.trim();
    const address = document.getElementById("new-tag-address").value.trim();
    const dataType = Number(document.getElementById("new-tag-data-type").value);
    const scanRate = Number(document.getElementById("new-tag-scan-rate").value);
    const access = Number(document.getElementById("new-tag-access").value);
    const description = document.getElementById("new-tag-description").value.trim();
    const result = document.getElementById("create-tag-result");
    if (
        !name ||
        !address ||
        !Number.isInteger(dataType) ||
        !Number.isInteger(scanRate) ||
        !Number.isInteger(access)
    ) {
        result.textContent = "Tag Name, Address, Data Type, Scan Rate, and Access are required.";
        result.className = "create-result error-message";
        return;
    }

    const destination = destinationPath(selectedDestinationNode);
    document.getElementById("preview-destination").textContent = destination;
    document.getElementById("preview-tag-name").textContent = name;
    document.getElementById("preview-address").textContent = address;
    document.getElementById("preview-data-type").textContent = friendlyEnumValue("new-tag-data-type", dataType);
    document.getElementById("preview-scan-rate").textContent = `${scanRate} ms`;
    document.getElementById("preview-access").textContent = friendlyEnumValue("new-tag-access", access);
    document.getElementById("preview-description").textContent = description || "(not provided)";
    document.getElementById("preview-full-path").textContent = `${destination}/${name}`;
    document.getElementById("preview-template-source").textContent =
        templateSourcePath || "(none — configured defaults shown above)";
    document.getElementById("create-tag-preview").classList.remove("hidden");
    result.classList.add("hidden");
});

document.getElementById("cancel-create-tag").addEventListener("click", () => {
    document.getElementById("create-tag-preview").classList.add("hidden");
});

document.getElementById("confirm-create-tag").addEventListener("click", async () => {
    if (!kepwareWriteEnabled || !selectedDestinationNode) return;
    const confirm = document.getElementById("confirm-create-tag");
    const result = document.getElementById("create-tag-result");
    confirm.disabled = true;

    const payload = {
        channel: selectedDestinationNode.context.channel,
        device: selectedDestinationNode.context.device,
        group_path: selectedDestinationNode.context.group_path || [],
        tag_name: document.getElementById("new-tag-name").value.trim(),
        address: document.getElementById("new-tag-address").value.trim(),
        data_type: Number(document.getElementById("new-tag-data-type").value),
        scan_rate: Number(document.getElementById("new-tag-scan-rate").value),
        access: Number(document.getElementById("new-tag-access").value),
        description: document.getElementById("new-tag-description").value.trim(),
    };

    try {
        const response = await fetch("/api/kepware/tags", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
        });
        const data = await response.json();
        if (!data.success) {
            result.textContent = data.error || "Kepware Tag creation failed.";
            result.className = "create-result error-message";
            return;
        }

        result.textContent = creationResultMessage(data);
        result.className = data.runtime_registry_sync?.status === "succeeded"
            ? "create-result success-message"
            : "create-result error-message";
        document.getElementById("create-tag-preview").classList.add("hidden");
        displayKepwareObject(data.tag);
        if (selectedDestinationDetails && selectedDestinationChildren) {
            await loadKepwareChildren(
                selectedDestinationDetails,
                selectedDestinationChildren,
                selectedDestinationNode,
            );
        }
    } catch (_error) {
        result.textContent = "Unable to submit the Tag creation request. Click Create Tag to retry.";
        result.className = "create-result error-message";
    } finally {
        confirm.disabled = false;
    }
});

function creationResultMessage(data) {
    const registry = data.runtime_registry_sync || { status: "not_started" };
    const historian = data.historian_subscription_sync || { status: "not_requested" };
    const registryText = registry.status === "succeeded"
        ? `Runtime Registry Sync ✅ (${registry.registry_state})`
        : `Runtime Registry Sync Failed — ${registry.error || "Full Reconcile remains available."}`;
    const historianText = historian.status === "requested"
        ? "Historian Subscription Sync Requested"
        : historian.status === "pending_disabled"
            ? "Historian Subscription Sync Pending (supervisor disabled)"
            : "Historian Subscription Sync Not Requested";
    const syncSummary = `Kepware Tag Created ✅ • ${registryText} • ${historianText}`;
    if (!data.differences || !data.differences.length) {
        return `${syncSummary}. Returned properties match the request.`;
    }
    const differences = data.differences.map((difference) => {
        return `${difference.property}: requested ${JSON.stringify(difference.requested)}, returned ${JSON.stringify(difference.actual)}`;
    });
    return `${syncSummary}. Kepware returned differences: ${differences.join("; ")}`;
}

function knowledgeIdentityPayload(node = selectedKnowledgeTag) {
    return {
        channel: node.context.channel,
        device: node.context.device,
        group_path: node.context.group_path || [],
        tag_name: node.name,
    };
}

function knowledgeNodeFromAlarm(alarm) {
    const parts = String(alarm?.tag_path || "").split("/").filter(Boolean);
    if (parts.length < 3) return null;
    return {
        name: parts.at(-1),
        object_type: "Tag",
        full_path: parts.join("."),
        context: {
            channel: parts[0],
            device: parts[1],
            group_path: parts.slice(2, -1),
        },
        tag_details: {
            node_id: alarm.node_id || "",
            data_type: alarm.data_type ?? "",
        },
    };
}

function loadOperationalTagContext(node) {
    if (!node) {
        resetTagKnowledgePanel();
        return;
    }
    selectedKnowledgeTag = node;
    loadTagKnowledge(node);
    loadTagResources(node);
}

function knowledgeFieldsPayload() {
    return {
        description: document.getElementById("knowledge-description").value,
        possible_cause: document.getElementById("knowledge-possible-cause").value,
        how_to_check: document.getElementById("knowledge-how-to-check").value,
        corrective_action: document.getElementById("knowledge-corrective-action").value,
        safety_warning: document.getElementById("knowledge-safety-warning").value,
        additional_notes: document.getElementById("knowledge-additional-notes").value,
    };
}

function emptyKnowledgeAttachments() {
    return Object.fromEntries(Object.keys(knowledgeSectionLabels).map((key) => [key, []]));
}

function knowledgeAttachmentReadUrl(attachment, node = selectedKnowledgeTag) {
    const identity = knowledgeIdentityPayload(node);
    const query = new URLSearchParams({
        channel: identity.channel, device: identity.device,
        group_path: JSON.stringify(identity.group_path), tag_name: identity.tag_name,
        relative_path: attachment.relative_path,
    });
    return `/api/tag-knowledge/attachment?${query}`;
}

function renderKnowledgeAttachments(section) {
    const container = document.getElementById(`knowledge-attachments-${section.replaceAll("_", "-")}`);
    container.replaceChildren();
    (knowledgeAttachments[section] || []).forEach((attachment) => {
        const card = document.createElement("div");
        card.className = "knowledge-attachment-card";
        const image = document.createElement("img");
        image.src = knowledgeAttachmentReadUrl(attachment);
        image.alt = attachment.caption || attachment.original_filename || "Tag Knowledge image";
        const caption = document.createElement("input");
        caption.type = "text";
        caption.maxLength = 500;
        caption.placeholder = "Optional caption";
        caption.value = attachment.caption || "";
        caption.addEventListener("input", () => {
            attachment.caption = caption.value;
            image.alt = caption.value || attachment.original_filename || "Tag Knowledge image";
        });
        const remove = document.createElement("button");
        remove.type = "button";
        remove.className = "danger-button";
        remove.textContent = "Remove";
        remove.addEventListener("click", () => {
            knowledgeAttachments[section] = knowledgeAttachments[section].filter((item) => item !== attachment);
            renderKnowledgeAttachments(section);
        });
        card.append(image, caption, remove);
        container.appendChild(card);
    });
}

function renderAllKnowledgeAttachments() {
    Object.keys(knowledgeSectionLabels).forEach(renderKnowledgeAttachments);
}

async function uploadKnowledgeImages(section, files) {
    if (!kmTagWriteEnabled || !selectedKnowledgeTag) return;
    const result = document.getElementById("knowledge-result");
    const node = selectedKnowledgeTag;
    const identity = knowledgeIdentityPayload(node);
    for (const file of files) {
        try {
            const form = new FormData();
            form.append("channel", identity.channel);
            form.append("device", identity.device);
            form.append("group_path", JSON.stringify(identity.group_path));
            form.append("tag_name", identity.tag_name);
            form.append("section", section);
            form.append("file", file, file.name);
            const response = await fetch("/api/tag-knowledge/attachments", { method: "POST", body: form });
            const data = await response.json();
            if (!response.ok || !data.success) throw new Error(data.error || `Unable to attach ${file.name}.`);
            if (selectedKnowledgeTag !== node) return;
            knowledgeAttachments[section].push(data.attachment);
            renderKnowledgeAttachments(section);
            result.textContent = `Attached ${file.name} to ${knowledgeSectionLabels[section]}.`;
            result.className = "create-result success-message";
        } catch (error) {
            result.textContent = error.message || `Unable to attach ${file.name}.`;
            result.className = "create-result error-message";
        }
    }
}

function clipboardImageFile(item, now = new Date()) {
    const blob = item.getAsFile();
    if (!blob) return null;
    const extension = {
        "image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp",
    }[blob.type] || ".bin";
    const two = (value) => String(value).padStart(2, "0");
    const timestamp = [
        now.getFullYear(), two(now.getMonth() + 1), two(now.getDate()), "_",
        two(now.getHours()), two(now.getMinutes()), two(now.getSeconds()),
    ].join("");
    return new File([blob], `clipboard_${timestamp}${extension}`, { type: blob.type });
}

function insertClipboardText(textarea, text) {
    if (!text) return;
    textarea.setRangeText(text, textarea.selectionStart, textarea.selectionEnd, "end");
    textarea.dispatchEvent(new Event("input", { bubbles: true }));
}

document.querySelectorAll(".knowledge-section textarea").forEach((textarea) => {
    textarea.addEventListener("paste", async (event) => {
        const items = [...(event.clipboardData?.items || [])];
        const imageItem = items.find((item) => item.kind === "file" && item.type.startsWith("image/"));
        if (!imageItem) return;
        const file = clipboardImageFile(imageItem);
        if (!file) return;
        event.preventDefault();
        insertClipboardText(textarea, event.clipboardData.getData("text/plain"));
        const section = textarea.closest(".knowledge-section").dataset.knowledgeSection;
        await uploadKnowledgeImages(section, [file]);
    });
});

document.querySelectorAll(".knowledge-attach-button").forEach((button) => {
    const section = button.dataset.section;
    const input = document.getElementById(`knowledge-image-${section.replaceAll("_", "-")}`);
    button.addEventListener("click", () => input.click());
    input.addEventListener("change", async () => {
        const files = [...input.files];
        input.value = "";
        await uploadKnowledgeImages(section, files);
    });
});

function resetTagKnowledgePanel() {
    selectedKnowledgeTag = null;
    pendingKnowledgePayload = null;
    knowledgeAttachments = emptyKnowledgeAttachments();
    document.getElementById("tag-knowledge-panel").classList.add("hidden");
    document.getElementById("tag-knowledge-form").reset();
    document.getElementById("knowledge-description").value = "";
    document.getElementById("knowledge-preview").classList.add("hidden");
    document.getElementById("knowledge-result").classList.add("hidden");
    renderAllKnowledgeAttachments();
    document.getElementById("tag-resources-panel").classList.add("hidden");
}

async function loadTagResources(node) {
    const panel = document.getElementById("tag-resources-panel");
    const status = document.getElementById("tag-resources-status");
    const list = document.getElementById("tag-resources-list");
    panel.classList.remove("hidden");
    status.textContent = "Loading Reference Resources…";
    status.className = "tree-counts";
    list.replaceChildren();
    const query = new URLSearchParams({
        channel: node.context.channel,
        device: node.context.device,
        tag: node.name,
    });
    (node.context.group_path || []).forEach((group) => query.append("tag_groups", group));
    try {
        const response = await fetch(`/api/tag-resources?${query}`);
        const data = await response.json();
        if (selectedKnowledgeTag !== node) return;
        if (!data.success) throw new Error(data.error || "Unable to load Reference Resources.");
        const resources = data.references.resources;
        status.textContent = resources.length ? `${resources.length} linked resource${resources.length === 1 ? "" : "s"}` : "No resources linked to this Tag.";
        resources.forEach((link) => {
            const item = document.createElement("article");
            item.className = "resource-item";
            const type = document.createElement("strong");
            type.textContent = link.relation_type;
            const name = document.createElement("span");
            name.textContent = link.resource.display_name;
            const details = document.createElement("span");
            details.textContent = [link.resource.manufacturer, link.resource.model, link.resource.part_no, link.resource.material_code,
                `v${link.resource.active_version}`, link.resource.updated_at].filter(Boolean).join(" · ");
            const actions = document.createElement("div"); actions.className = "preview-actions";
            actions.innerHTML = `<a href="/api/resources/${encodeURIComponent(link.resource_id)}/file" target="_blank">Open</a>`;
            if (link.relation_type === "Supplier") {
                actions.firstElementChild.remove();
                const view = document.createElement("button"); view.type = "button"; view.textContent = "View Supplier";
                view.addEventListener("click", () => showSupplier(link.resource_id)); actions.append(view);
                appendLinkedSupplierSummary(item, link.resource_id);
            }
            if (link.relation_type === "EquipmentPart") {
                actions.firstElementChild.remove();
                type.textContent = "Equipment / Part";
                const view = document.createElement("button"); view.type = "button"; view.textContent = "View"; view.onclick = () => showEquipmentPart(link.resource_id); actions.append(view);
                const edit = document.createElement("button"); edit.type = "button"; edit.textContent = "Edit"; edit.disabled = !kmResourceWriteEnabled;
                edit.onclick = async () => { const response = await fetch(`/api/equipment-parts/${encodeURIComponent(link.resource_id)}`); const data = await response.json(); if (data.success) openEquipmentPartForm(data.equipment_part); }; actions.append(edit);
                appendLinkedEquipmentPartSummary(item, link.resource_id);
            }
            const versions = document.createElement("button"); versions.type = "button"; versions.textContent = "Versions";
            versions.addEventListener("click", () => showResourceVersions(link.resource));
            const unlink = document.createElement("button"); unlink.type = "button"; unlink.textContent = "Unlink"; unlink.disabled = !kmResourceWriteEnabled;
            unlink.className = "danger-button";
            unlink.addEventListener("click", () => unlinkResource(link.resource_id));
            const more = document.createElement("button"); more.type = "button"; more.textContent = "Link to More Tags"; more.disabled = !kmResourceWriteEnabled;
            more.addEventListener("click", () => beginTargetSelection(link.resource));
            const newVersion = document.createElement("button"); newVersion.type = "button"; newVersion.textContent = "Upload New Version"; newVersion.disabled = !kmResourceWriteEnabled;
            newVersion.addEventListener("click", () => showVersionUpload(link.resource));
            if (link.relation_type !== "EquipmentPart") actions.append(versions);
            actions.append(unlink, more);
            if (!["Supplier", "EquipmentPart"].includes(link.relation_type)) actions.append(newVersion);
            item.append(type, name, details, actions);
            list.append(item);
        });
    } catch (error) {
        if (selectedKnowledgeTag !== node) return;
        status.textContent = error.message || "Unable to load Reference Resources.";
        status.className = "error-message";
    }
}

function showWorkflow(viewId) {
    document.getElementById("resource-workflow").classList.remove("hidden");
    ["resource-search-view", "resource-upload-form", "resource-version-view", "resource-target-view", "supplier-directory-view", "supplier-form", "equipment-part-directory-view", "equipment-part-form"].forEach((id) =>
        document.getElementById(id).classList.toggle("hidden", id !== viewId));
    document.getElementById("resource-workflow-result").classList.add("hidden");
}

document.getElementById("link-existing-resource").addEventListener("click", async () => { showWorkflow("resource-search-view"); await searchResources(); });
document.getElementById("upload-new-resource").addEventListener("click", () => showWorkflow("resource-upload-form"));
document.getElementById("new-supplier").addEventListener("click", () => openSupplierForm());
document.getElementById("find-supplier").addEventListener("click", async () => { showWorkflow("supplier-directory-view"); await searchSuppliers(); });
document.getElementById("new-equipment-part").addEventListener("click", () => openEquipmentPartForm());
document.getElementById("find-equipment-part").addEventListener("click", async () => { showWorkflow("equipment-part-directory-view"); await searchEquipmentParts(); });
document.getElementById("close-resource-workflow").addEventListener("click", () => { resourceTagSelectionMode = false; document.getElementById("resource-workflow").classList.add("hidden"); });
document.getElementById("resource-search").addEventListener("input", searchResources);

async function searchResources() {
    const response = await fetch(`/api/resources?q=${encodeURIComponent(document.getElementById("resource-search").value)}`);
    const data = await response.json(); const list = document.getElementById("resource-search-results"); list.replaceChildren();
    (data.resources || []).forEach((resource) => {
        const button = document.createElement("button"); button.type = "button";
        const active = resource.versions.find((version) => version.version === resource.active_version);
        button.textContent = [resource.resource_type, resource.display_name, resource.manufacturer, resource.model,
            `v${resource.active_version}`, active?.original_filename].filter(Boolean).join(" — ");
        button.addEventListener("click", () => beginTargetSelection(resource)); list.append(button);
    });
}

document.getElementById("resource-upload-form").addEventListener("submit", async (event) => {
    event.preventDefault(); const result = document.getElementById("resource-workflow-result");
    const formData = new FormData(event.currentTarget);
    const response = await fetch("/api/resources/upload", {method: "POST", body: formData}); const data = await response.json();
    if (!data.success) return showResourceResult(data.error || "Upload failed.", true);
    if (data.status === "duplicate") {
        resourceForLinking = data.duplicate; showResourceResult(`This file already exists: ${data.duplicate.display_name}, ${data.duplicate.resource_type}, version ${data.duplicate.version}. Use Existing Resource to link it.`);
        const use = document.createElement("button"); use.textContent = "Use Existing Resource"; use.onclick = () => beginTargetSelection(data.duplicate);
        const cancel = document.createElement("button"); cancel.textContent = "Cancel"; cancel.onclick = closeResourceDecision;
        result.append(document.createElement("br"), use, cancel); return;
    }
    if (data.status === "similar_resource_found") {
        pendingSimilarUpload = {formData, decisionToken: data.decision_token, candidates: data.candidates};
        showSimilarResourceDecision(data.candidates[0], formData.get("file")?.name || "Selected file");
        return;
    }
    showResourceResult(`Created ${data.resource.resource_id}, active version ${data.resource.active_version}.`); beginTargetSelection(data.resource);
});

function showSimilarResourceDecision(candidate, selectedFilename) {
    const result = document.getElementById("resource-workflow-result");
    showResourceResult("A similar Resource already exists. The selected file has different content.", false, true);
    const details = document.createElement("dl"); details.className = "object-properties resource-decision-details";
    const rows = [
        ["Existing Resource", candidate.display_name], ["Type", candidate.resource_type],
        ["Manufacturer", candidate.manufacturer || "—"], ["Model", candidate.model || "—"],
        ["Current Version", String(candidate.active_version)], ["Existing Original File", candidate.original_filename],
        ["Selected File", selectedFilename],
    ];
    rows.forEach(([label, value]) => { const term = document.createElement("dt"); term.textContent = label; const description = document.createElement("dd"); description.textContent = value; details.append(term, description); });
    const prompt = document.createElement("p"); prompt.textContent = "Choose what this file represents:";
    const version = document.createElement("button"); version.textContent = "Upload as New Version"; version.onclick = () => uploadSimilarAsVersion(candidate);
    const separate = document.createElement("button"); separate.textContent = "Create Separate Resource"; separate.onclick = () => confirmSeparateResource(candidate);
    const cancel = document.createElement("button"); cancel.textContent = "Cancel"; cancel.onclick = closeResourceDecision;
    const actions = document.createElement("div"); actions.className = "preview-actions"; actions.append(version, separate, cancel);
    result.append(details, prompt, actions);
}

async function uploadSimilarAsVersion(candidate) {
    if (!pendingSimilarUpload) return;
    const file = pendingSimilarUpload.formData.get("file"); const form = new FormData(); form.append("file", file);
    const response = await fetch(`/api/resources/${encodeURIComponent(candidate.resource_id)}/versions`, {method: "POST", body: form});
    const data = await response.json();
    if (!data.success) return showResourceResult(data.error || "Unable to upload the new version.", true);
    if (data.status === "duplicate") return showResourceResult(`This file already exists as ${data.duplicate.display_name} version ${data.duplicate.version}.`);
    pendingSimilarUpload = null; showResourceResult(`Uploaded as version ${data.resource.active_version} of ${data.resource.display_name}. Existing Tag links remain unchanged.`);
    if (selectedKnowledgeTag) await loadTagResources(selectedKnowledgeTag);
}

function confirmSeparateResource(candidate) {
    if (!pendingSimilarUpload) return;
    const displayName = pendingSimilarUpload.formData.get("display_name");
    showResourceResult(`Create a separate Resource? A similar Resource already exists: ${candidate.display_name}. New Resource: ${displayName}. This will create a new ResourceId and will not update the existing ${candidate.resource_type}.`, false, true);
    const result = document.getElementById("resource-workflow-result");
    const confirm = document.createElement("button"); confirm.textContent = "Confirm Separate Resource"; confirm.onclick = createConfirmedSeparateResource;
    const cancel = document.createElement("button"); cancel.textContent = "Cancel"; cancel.onclick = closeResourceDecision;
    result.append(document.createElement("br"), confirm, cancel);
}

async function createConfirmedSeparateResource() {
    if (!pendingSimilarUpload) return;
    const form = new FormData(); pendingSimilarUpload.formData.forEach((value, key) => form.append(key, value));
    form.append("confirm_separate_token", pendingSimilarUpload.decisionToken);
    const response = await fetch("/api/resources/upload", {method: "POST", body: form}); const data = await response.json();
    if (!data.success) return showResourceResult(data.error || "Unable to create a separate Resource.", true);
    if (data.status !== "created") return showResourceResult("The Resource state changed. Review the upload decision again.", true);
    pendingSimilarUpload = null; showResourceResult(`Created separate Resource ${data.resource.resource_id}.`); beginTargetSelection(data.resource);
}

function closeResourceDecision() {
    pendingSimilarUpload = null;
    showWorkflow("resource-upload-form");
}

function beginTargetSelection(resource) {
    resourceForLinking = resource; resourceTargetTags = new Map();
    if (selectedKnowledgeTag) resourceTargetTags.set(selectedKnowledgeTag.full_path, selectedKnowledgeTag);
    showWorkflow("resource-target-view"); renderResourceTargets();
}

function renderResourceTargets() {
    const container = document.getElementById("resource-target-tags"); container.replaceChildren();
    resourceTargetTags.forEach((node, path) => { const chip = document.createElement("button"); chip.type = "button"; chip.textContent = `${path} ×`; chip.onclick = () => { resourceTargetTags.delete(path); renderResourceTargets(); }; container.append(chip); });
}

document.getElementById("select-more-tags").addEventListener("click", () => { resourceTagSelectionMode = !resourceTagSelectionMode; showResourceResult(resourceTagSelectionMode ? "Selection mode active: manually expand the lazy Kepware tree and click Tag nodes." : "Selection mode stopped."); });
document.getElementById("link-resource-targets").addEventListener("click", async () => {
    if (!resourceForLinking || !resourceTargetTags.size) return;
    const tags = [...resourceTargetTags.values()].map((node) => ({channel: node.context.channel, device: node.context.device, tag_groups: node.context.group_path || [], tag: node.name}));
    const response = await fetch("/api/tag-resources/link-many", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({resource_id: resourceForLinking.resource_id, tags})});
    const data = await response.json(); showResourceResult(data.success ? data.results.map((r) => `${r.kepware_path}: ${r.status}`).join("; ") : data.error, !data.success);
    resourceTagSelectionMode = false; if (selectedKnowledgeTag) await loadTagResources(selectedKnowledgeTag);
});

async function unlinkResource(resourceId) {
    const response = await fetch("/api/tag-resources/unlink", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({...knowledgeIdentityPayload(), resource_id: resourceId})});
    const data = await response.json(); if (!data.success) showResourceResult(data.error, true); else await loadTagResources(selectedKnowledgeTag);
}

function showResourceVersions(resource) {
    showWorkflow("resource-search-view"); const list = document.getElementById("resource-search-results"); list.replaceChildren();
    [...resource.versions].reverse().forEach((version) => { const link = document.createElement("a"); link.target = "_blank"; link.href = `/api/resources/${encodeURIComponent(resource.resource_id)}/file?version=${version.version}`; link.textContent = `v${version.version}${version.version === resource.active_version ? " Active" : ""} — ${version.original_filename}`; list.append(link); });
}

function showVersionUpload(resource) { resourceForLinking = resource; showWorkflow("resource-version-view"); document.getElementById("resource-version-preview").textContent = `${resource.display_name}: current v${resource.active_version}, new v${resource.active_version + 1}`; }
document.getElementById("resource-version-file").addEventListener("change", (event) => {
    if (!resourceForLinking) return;
    const selected = event.target.files[0]?.name || "No file selected";
    document.getElementById("resource-version-preview").textContent = `${resourceForLinking.display_name}: current v${resourceForLinking.active_version}, new v${resourceForLinking.active_version + 1}, selected file: ${selected}`;
});
document.getElementById("confirm-resource-version").addEventListener("click", async () => {
    const file = document.getElementById("resource-version-file").files[0]; if (!file || !resourceForLinking) return;
    const form = new FormData(); form.append("file", file); const response = await fetch(`/api/resources/${encodeURIComponent(resourceForLinking.resource_id)}/versions`, {method: "POST", body: form}); const data = await response.json();
    showResourceResult(data.status === "duplicate" ? `This version/content already exists as ${data.duplicate.display_name} v${data.duplicate.version}.` : data.success ? `Active version is now ${data.resource.active_version}.` : data.error, !data.success);
    if (data.success && data.resource && selectedKnowledgeTag) await loadTagResources(selectedKnowledgeTag);
});

function showResourceResult(message, error = false, warning = false) { const result = document.getElementById("resource-workflow-result"); result.textContent = message; result.className = `create-result ${error ? "error-message" : warning ? "warning-message" : "success-message"}`; }

let supplierBeingEdited = null;
const supplierFieldNames = ["supplier_name", "supplier_code", "tax_id", "company_name", "website", "address", "general_phone", "general_email", "brands_products", "models_equipment", "support_notes", "additional_notes"];

document.getElementById("supplier-search").addEventListener("input", searchSuppliers);
document.getElementById("add-supplier-contact").addEventListener("click", () => addSupplierContact());
document.getElementById("cancel-supplier-edit").addEventListener("click", async () => { showWorkflow("supplier-directory-view"); await searchSuppliers(); });

async function searchSuppliers() {
    const response = await fetch(`/api/suppliers?q=${encodeURIComponent(document.getElementById("supplier-search").value)}`);
    const data = await response.json(); const list = document.getElementById("supplier-search-results"); list.replaceChildren();
    if (!data.success) return showResourceResult(data.error || "Unable to load Suppliers.", true);
    data.suppliers.forEach((supplier) => {
        const button = document.createElement("button"); button.type = "button";
        button.textContent = [supplier.supplier_name, supplier.supplier_code, supplier.company_name, supplier.general_phone,
            supplier.general_email, `${supplier.contacts.length} contact${supplier.contacts.length === 1 ? "" : "s"}`, supplier.updated_at].filter(Boolean).join(" — ");
        button.addEventListener("click", () => showSupplier(supplier.resource_id)); list.append(button);
    });
}

async function showSupplier(resourceId) {
    showWorkflow("supplier-directory-view");
    const response = await fetch(`/api/suppliers/${encodeURIComponent(resourceId)}`); const data = await response.json();
    if (!data.success) return showResourceResult(data.error || "Unable to load Supplier.", true);
    renderSupplierDetail(data.supplier, data.resource);
}

function renderSupplierDetail(supplier, resource) {
    const detail = document.getElementById("supplier-detail"); detail.replaceChildren(); detail.classList.remove("hidden");
    const title = document.createElement("strong"); title.textContent = supplier.supplier_name; detail.append(title);
    const company = document.createElement("span"); company.textContent = [supplier.supplier_code, supplier.tax_id && `Tax ID ${supplier.tax_id}`, supplier.company_name, supplier.website,
        supplier.address, supplier.general_phone, supplier.general_email].filter(Boolean).join(" · "); detail.append(company);
    appendSupplierSection(detail, "Brands / Products", supplier.brands_products);
    appendSupplierSection(detail, "Models / Equipment", supplier.models_equipment);
    appendSupplierSection(detail, "Support Notes", supplier.support_notes);
    supplier.contacts.forEach((contact) => appendContactSummary(detail, contact));
    appendSupplierEquipmentParts(detail, supplier.resource_id);
    appendManagedResourceRelationships(detail, supplier.resource_id, [{type: "Quotation", heading: "Quotations"}]);
    const actions = document.createElement("div"); actions.className = "preview-actions";
    const edit = document.createElement("button"); edit.type = "button"; edit.textContent = "Edit"; edit.disabled = !kmResourceWriteEnabled; edit.onclick = () => openSupplierForm(supplier);
    const link = document.createElement("button"); link.type = "button"; link.textContent = "Link to Current Tag"; link.disabled = !kmResourceWriteEnabled || !selectedKnowledgeTag; link.onclick = () => beginTargetSelection(resource);
    const more = document.createElement("button"); more.type = "button"; more.textContent = "Link to More Tags"; more.disabled = !kmResourceWriteEnabled; more.onclick = () => beginTargetSelection(resource);
    actions.append(edit, link, more); detail.append(actions);
}

function appendSupplierSection(parent, heading, value) {
    if (!value) return; const strong = document.createElement("strong"); strong.textContent = heading;
    const content = document.createElement("span"); content.textContent = value; parent.append(strong, content);
}

function appendContactSummary(parent, contact) {
    const block = document.createElement("div"); block.className = "supplier-contact-summary";
    const heading = document.createElement("strong"); heading.textContent = `${contact.contact_type}: ${contact.contact_name || "Contact"}`; block.append(heading);
    const details = document.createElement("span"); details.textContent = [contact.department_role, contact.phone && `Tel ${contact.phone}`, contact.mobile && `Mobile ${contact.mobile}`].filter(Boolean).join(" · "); block.append(details);
    if (contact.email) { const email = document.createElement("a"); email.textContent = contact.email; email.href = `mailto:${encodeURIComponent(contact.email)}`; block.append(email); }
    parent.append(block);
}

async function appendLinkedSupplierSummary(parent, resourceId) {
    try {
        const response = await fetch(`/api/suppliers/${encodeURIComponent(resourceId)}`); const data = await response.json();
        if (!data.success) return;
        const preferred = data.supplier.contacts.find((contact) => ["Technical", "Support"].includes(contact.contact_type)) || data.supplier.contacts[0];
        if (preferred) appendContactSummary(parent, preferred);
    } catch (_error) { /* The Resource card remains usable if profile enrichment is unavailable. */ }
}

function openSupplierForm(supplier = null) {
    supplierBeingEdited = supplier?.resource_id || null; showWorkflow("supplier-form");
    const form = document.getElementById("supplier-form"); form.reset();
    document.getElementById("supplier-form-title").textContent = supplier ? `Edit ${supplier.supplier_name}` : "New Supplier";
    supplierFieldNames.forEach((name) => { form.elements[name].value = supplier?.[name] || ""; });
    const contacts = document.getElementById("supplier-contacts"); contacts.replaceChildren();
    (supplier?.contacts || []).forEach(addSupplierContact); if (!supplier?.contacts?.length) addSupplierContact();
}

function addSupplierContact(contact = {}) {
    const row = document.createElement("fieldset"); row.className = "supplier-contact"; row.dataset.contactId = contact.contact_id || "";
    const fields = [["contact_name", "Contact Name"], ["department_role", "Department / Role"], ["phone", "Phone"], ["mobile", "Mobile"], ["email", "Email"], ["notes", "Notes"]];
    const typeLabel = document.createElement("label"); typeLabel.textContent = "Contact Type"; const type = document.createElement("select"); type.name = "contact_type";
    ["Sales", "Technical", "Service", "Support", "Other"].forEach((value) => { const option = document.createElement("option"); option.value = option.textContent = value; type.append(option); }); type.value = contact.contact_type || "Other"; typeLabel.append(type); row.append(typeLabel);
    fields.forEach(([name, labelText]) => { const label = document.createElement("label"); label.textContent = labelText; const input = name === "notes" ? document.createElement("textarea") : document.createElement("input"); input.name = name; input.value = contact[name] || ""; if (name === "email") input.type = "email"; label.append(input); row.append(label); });
    const remove = document.createElement("button"); remove.type = "button"; remove.textContent = "Remove Contact"; remove.className = "danger-button"; remove.onclick = () => row.remove(); row.append(remove);
    document.getElementById("supplier-contacts").append(row);
}

document.getElementById("supplier-form").addEventListener("submit", async (event) => {
    event.preventDefault(); const form = event.currentTarget; const payload = {};
    supplierFieldNames.forEach((name) => { payload[name] = form.elements[name].value; });
    payload.contacts = [...document.querySelectorAll("#supplier-contacts .supplier-contact")].map((row) => {
        const contact = {}; ["contact_name", "department_role", "contact_type", "phone", "mobile", "email", "notes"].forEach((name) => { contact[name] = row.querySelector(`[name="${name}"]`).value; });
        if (row.dataset.contactId) contact.contact_id = row.dataset.contactId; return contact;
    });
    const url = supplierBeingEdited ? `/api/suppliers/${encodeURIComponent(supplierBeingEdited)}` : "/api/suppliers";
    const response = await fetch(url, {method: supplierBeingEdited ? "PUT" : "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(payload)}); const data = await response.json();
    if (!data.success) return showResourceResult(data.error || "Unable to save Supplier.", true);
    showResourceResult(data.status === "unchanged" ? "Supplier is unchanged; no new version was created." : `Saved ${data.supplier.supplier_name} as version ${data.resource.active_version}.`);
    supplierBeingEdited = data.supplier.resource_id; renderSupplierDetail(data.supplier, data.resource);
});

let equipmentPartBeingEdited = null;
let equipmentPartSupplierOptions = [];
const equipmentPartFields = ["display_name", "item_kind", "category", "manufacturer", "brand", "model", "part_no", "material_code", "unit_of_measure", "description", "technical_specification", "notes"];

document.getElementById("equipment-part-search").addEventListener("input", searchEquipmentParts);
document.getElementById("add-equipment-part-supplier").addEventListener("click", () => addEquipmentPartSupplier());
document.getElementById("cancel-equipment-part-edit").addEventListener("click", async () => { showWorkflow("equipment-part-directory-view"); await searchEquipmentParts(); });

async function searchEquipmentParts() {
    const response = await fetch(`/api/equipment-parts?q=${encodeURIComponent(document.getElementById("equipment-part-search").value)}`);
    const data = await response.json(); const list = document.getElementById("equipment-part-search-results"); list.replaceChildren();
    if (!data.success) return showResourceResult(data.error || "Unable to load Equipment / Parts.", true);
    data.equipment_parts.forEach((item) => {
        const button = document.createElement("button"); button.type = "button";
        button.textContent = [item.display_name, item.item_kind, item.manufacturer, item.model, item.part_no, item.material_code, item.updated_at].filter(Boolean).join(" — ");
        button.onclick = () => showEquipmentPart(item.resource_id); list.append(button);
    });
}

async function showEquipmentPart(resourceId) {
    showWorkflow("equipment-part-directory-view");
    const response = await fetch(`/api/equipment-parts/${encodeURIComponent(resourceId)}`); const data = await response.json();
    if (!data.success) return showResourceResult(data.error || "Unable to load Equipment / Part.", true);
    await loadEquipmentPartSupplierOptions();
    renderEquipmentPartDetail(data.equipment_part, data.resource);
}

async function appendResourceRelationships(parent, sourceResourceId, headingText = "Linked Resources") {
    try {
        const response = await fetch(`/api/resource-relationships/${encodeURIComponent(sourceResourceId)}`); const data = await response.json();
        if (!data.success || !data.relationships.length) return;
        const heading = document.createElement("strong"); heading.textContent = headingText; parent.append(heading);
        data.relationships.forEach((link) => {
            const row = document.createElement("span");
            row.textContent = `${link.relationship_type}: ${link.resource.display_name} (${link.target_resource_id})`;
            parent.append(row);
        });
    } catch (_error) { /* Base canonical details remain available. */ }
}

async function appendSupplierEquipmentParts(parent, supplierResourceId) {
    try {
        const response = await fetch(`/api/suppliers/${encodeURIComponent(supplierResourceId)}/equipment-parts`); const data = await response.json();
        const heading = document.createElement("strong"); heading.textContent = "Equipment / Parts"; parent.append(heading);
        if (!data.success || !data.equipment_parts.length) { const empty = document.createElement("span"); empty.textContent = "None linked through EPT Supplier relationships."; parent.append(empty); return; }
        data.equipment_parts.forEach((item) => { const row = document.createElement("span"); row.textContent = `${item.display_name} (${item.resource_id})`; parent.append(row); });
    } catch (_error) { /* Supplier details remain usable. */ }
}

async function appendManagedResourceRelationships(parent, sourceResourceId, sections) {
    let links = [];
    try { const response = await fetch(`/api/resource-relationships/${encodeURIComponent(sourceResourceId)}`); const data = await response.json(); if (data.success) links = data.relationships; }
    catch (_error) { /* Render empty management sections. */ }
    sections.forEach((section) => {
        const group = document.createElement("div"); group.className = "relationship-section";
        const heading = document.createElement("strong"); heading.textContent = section.heading; group.append(heading);
        const matching = links.filter((link) => link.relationship_type === section.type);
        if (!matching.length) { const empty = document.createElement("span"); empty.textContent = "No linked resources."; group.append(empty); }
        matching.forEach((link) => {
            const row = document.createElement("div"); row.className = "preview-actions";
            const open = document.createElement("a"); open.target = "_blank"; open.href = `/api/resources/${encodeURIComponent(link.target_resource_id)}/file`; open.textContent = `${link.resource.display_name} (${link.target_resource_id})`;
            const unlink = document.createElement("button"); unlink.type = "button"; unlink.className = "danger-button"; unlink.textContent = "Unlink"; unlink.disabled = !kmResourceWriteEnabled;
            unlink.onclick = async () => { if (!confirm(`Unlink ${link.resource.display_name}?`)) return; await mutateResourceRelationship("unlink", sourceResourceId, link.target_resource_id); };
            row.append(open, unlink); group.append(row);
        });
        const add = document.createElement("button"); add.type = "button"; add.textContent = `+ Link Existing ${section.heading.replace(/s$/, "")}`; add.disabled = !kmResourceWriteEnabled;
        add.onclick = () => openExistingResourceLinker(group, sourceResourceId, section.type); group.append(add); parent.append(group);
    });
}

async function openExistingResourceLinker(group, sourceResourceId, resourceType) {
    group.querySelector(".existing-resource-linker")?.remove();
    const panel = document.createElement("div"); panel.className = "existing-resource-linker resource-item";
    const search = document.createElement("input"); search.type = "search"; search.placeholder = `Search existing ${resourceType}`;
    const results = document.createElement("div"); results.className = "resource-list"; panel.append(search, results); group.append(panel);
    const load = async () => {
        const response = await fetch(`/api/resources?resource_type=${encodeURIComponent(resourceType)}&q=${encodeURIComponent(search.value)}`); const data = await response.json(); results.replaceChildren();
        if (!data.success) return;
        data.resources.forEach((resource) => { const select = document.createElement("button"); select.type = "button"; select.textContent = `${resource.display_name} (${resource.resource_id})`;
            select.onclick = async () => { if (!confirm(`Link existing ${resourceType} ${resource.display_name}?`)) return; await mutateResourceRelationship("link", sourceResourceId, resource.resource_id); }; results.append(select); });
    };
    search.addEventListener("input", load); await load(); search.focus();
}

async function mutateResourceRelationship(operation, sourceResourceId, targetResourceId) {
    const response = await fetch(`/api/resource-relationships/${operation}`, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({source_resource_id: sourceResourceId, target_resource_id: targetResourceId})});
    const data = await response.json(); if (!data.success) return showResourceResult(data.error || `Unable to ${operation} Resource.`, true);
    showResourceResult(operation === "link" ? "Relationship linked." : "Relationship unlinked.");
    if (sourceResourceId.startsWith("EPT_")) await showEquipmentPart(sourceResourceId); else await showSupplier(sourceResourceId);
}

function renderEquipmentPartDetail(item, resource) {
    const detail = document.getElementById("equipment-part-detail"); detail.replaceChildren(); detail.classList.remove("hidden");
    const title = document.createElement("strong"); title.textContent = item.display_name; detail.append(title);
    const identity = document.createElement("span"); identity.textContent = [item.item_kind, item.category, item.manufacturer, item.brand, item.model,
        item.part_no && `Part No. ${item.part_no}`, item.material_code && `Material Code ${item.material_code}`, item.unit_of_measure].filter(Boolean).join(" · "); detail.append(identity);
    appendSupplierSection(detail, "Description", item.description); appendSupplierSection(detail, "Technical Specification", item.technical_specification);
    appendSupplierSection(detail, "Aliases / Alternate Names", item.aliases.join(" · ")); appendSupplierSection(detail, "Notes", item.notes);
    if (item.supplier_links.length) {
        const heading = document.createElement("strong"); heading.textContent = "Suppliers"; detail.append(heading);
        item.supplier_links.forEach((link) => { const row = document.createElement("span"); const supplier = equipmentPartSupplierOptions.find((value) => value.resource_id === link.supplier_resource_id);
            row.textContent = [supplier?.supplier_name || link.supplier_resource_id, link.relationship, link.supplier_part_no].filter(Boolean).join(" · "); detail.append(row); });
    }
    appendManagedResourceRelationships(detail, item.resource_id, [
        {type: "Manual", heading: "Manuals"}, {type: "Drawing", heading: "Drawings"},
        {type: "Quotation", heading: "Quotations"}, {type: "GeneralDocument", heading: "Documents"},
    ]);
    const actions = document.createElement("div"); actions.className = "preview-actions";
    const edit = document.createElement("button"); edit.type = "button"; edit.textContent = "Edit"; edit.disabled = !kmResourceWriteEnabled; edit.onclick = () => openEquipmentPartForm(item);
    const link = document.createElement("button"); link.type = "button"; link.textContent = "Link to Current Tag"; link.disabled = !kmResourceWriteEnabled || !selectedKnowledgeTag; link.onclick = () => beginTargetSelection(resource);
    const more = document.createElement("button"); more.type = "button"; more.textContent = "Link to More Tags"; more.disabled = !kmResourceWriteEnabled; more.onclick = () => beginTargetSelection(resource);
    actions.append(edit, link, more); detail.append(actions);
}

async function appendLinkedEquipmentPartSummary(parent, resourceId) {
    try {
        const response = await fetch(`/api/equipment-parts/${encodeURIComponent(resourceId)}`); const data = await response.json(); if (!data.success) return;
        const item = data.equipment_part; const summary = document.createElement("span");
        summary.textContent = [item.manufacturer && `Manufacturer: ${item.manufacturer}`, item.model && `Model: ${item.model}`,
            item.part_no && `Part No: ${item.part_no}`, item.material_code && `Material Code: ${item.material_code}`].filter(Boolean).join(" · "); parent.append(summary);
        if (item.supplier_links.length) {
            const suppliers = document.createElement("span"); suppliers.textContent = `Suppliers: ${item.supplier_links.map((link) => {
                const supplier = equipmentPartSupplierOptions.find((value) => value.resource_id === link.supplier_resource_id); return supplier?.supplier_name || link.supplier_resource_id;
            }).join(", ")}`; parent.append(suppliers);
        }
        await appendResourceRelationships(parent, resourceId, "Equipment Resources");
    } catch (_error) { /* Keep the base Resource card usable. */ }
}

async function loadEquipmentPartSupplierOptions() {
    const response = await fetch("/api/suppliers"); const data = await response.json();
    equipmentPartSupplierOptions = data.success ? data.suppliers : [];
}

async function openEquipmentPartForm(item = null) {
    equipmentPartBeingEdited = item?.resource_id || null; showWorkflow("equipment-part-form"); await loadEquipmentPartSupplierOptions();
    const form = document.getElementById("equipment-part-form"); form.reset();
    document.getElementById("equipment-part-form-title").textContent = item ? `Edit ${item.display_name}` : "New Equipment / Part";
    equipmentPartFields.forEach((name) => { form.elements[name].value = item?.[name] || ""; });
    form.elements.aliases.value = (item?.aliases || []).join("\n");
    const links = document.getElementById("equipment-part-suppliers"); links.replaceChildren();
    (item?.supplier_links || []).forEach(addEquipmentPartSupplier);
}

function addEquipmentPartSupplier(link = {}) {
    const row = document.createElement("fieldset"); row.className = "supplier-contact equipment-part-supplier";
    const searchLabel = document.createElement("label"); searchLabel.textContent = "Search Supplier"; const search = document.createElement("input"); search.type = "search"; search.placeholder = "Name, code or company"; searchLabel.append(search); row.append(searchLabel);
    const supplierLabel = document.createElement("label"); supplierLabel.textContent = "Existing Supplier"; const supplier = document.createElement("select"); supplier.name = "supplier_resource_id"; supplier.required = true;
    const prompt = document.createElement("option"); prompt.value = ""; prompt.textContent = "Select Supplier"; supplier.append(prompt);
    equipmentPartSupplierOptions.forEach((item) => { const option = document.createElement("option"); option.value = item.resource_id; option.textContent = [item.supplier_name, item.supplier_code, item.company_name].filter(Boolean).join(" — "); supplier.append(option); });
    supplier.value = link.supplier_resource_id || ""; supplierLabel.append(supplier); row.append(supplierLabel);
    search.addEventListener("input", () => { const needle = search.value.trim().toLocaleLowerCase(); [...supplier.options].forEach((option, index) => { if (index) option.hidden = Boolean(needle) && !option.textContent.toLocaleLowerCase().includes(needle); }); });
    const relationshipLabel = document.createElement("label"); relationshipLabel.textContent = "Relationship"; const relationship = document.createElement("select"); relationship.name = "relationship";
    ["Manufacturer", "Distributor", "Dealer", "Service", "Repair", "Fabricator", "Contractor", "Other"].forEach((value) => { const option = document.createElement("option"); option.value = option.textContent = value; relationship.append(option); }); relationship.value = link.relationship || "Other"; relationshipLabel.append(relationship); row.append(relationshipLabel);
    [["supplier_part_no", "Supplier Part No."], ["notes", "Relationship Notes"]].forEach(([name, text]) => { const label = document.createElement("label"); label.textContent = text; const input = name === "notes" ? document.createElement("textarea") : document.createElement("input"); input.name = name; input.value = link[name] || ""; label.append(input); row.append(label); });
    const remove = document.createElement("button"); remove.type = "button"; remove.textContent = "Remove Supplier"; remove.className = "danger-button"; remove.onclick = () => row.remove(); row.append(remove);
    document.getElementById("equipment-part-suppliers").append(row);
}

function equipmentPartPayload() {
    const form = document.getElementById("equipment-part-form"); const payload = {};
    equipmentPartFields.forEach((name) => { payload[name] = form.elements[name].value; });
    payload.aliases = form.elements.aliases.value.split(/\r?\n/).map((value) => value.trim()).filter(Boolean);
    payload.supplier_links = [...document.querySelectorAll("#equipment-part-suppliers .equipment-part-supplier")].map((row) => ({
        supplier_resource_id: row.querySelector('[name="supplier_resource_id"]').value,
        relationship: row.querySelector('[name="relationship"]').value,
        supplier_part_no: row.querySelector('[name="supplier_part_no"]').value,
        notes: row.querySelector('[name="notes"]').value,
    })); return payload;
}

document.getElementById("equipment-part-form").addEventListener("submit", async (event) => { event.preventDefault(); await saveEquipmentPart(); });

async function saveEquipmentPart(confirmSeparateToken = null) {
    const payload = equipmentPartPayload(); if (confirmSeparateToken) payload.confirm_separate_token = confirmSeparateToken;
    const url = equipmentPartBeingEdited ? `/api/equipment-parts/${encodeURIComponent(equipmentPartBeingEdited)}` : "/api/equipment-parts";
    const response = await fetch(url, {method: equipmentPartBeingEdited ? "PUT" : "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(payload)}); const data = await response.json();
    if (!data.success) return showResourceResult(data.error || "Unable to save Equipment / Part.", true);
    if (data.status === "similar_equipment_part_found") return renderEquipmentPartCandidates(data, payload.display_name);
    showResourceResult(data.status === "unchanged" ? "Equipment / Part is unchanged; no new version was created." : `Saved ${data.equipment_part.display_name} as version ${data.resource.active_version}.`);
    equipmentPartBeingEdited = data.equipment_part.resource_id; renderEquipmentPartDetail(data.equipment_part, data.resource);
}

function renderEquipmentPartCandidates(data, requestedName) {
    const result = document.getElementById("resource-workflow-result"); result.replaceChildren(); result.className = "create-result warning-message";
    const message = document.createElement("p"); message.textContent = `A likely matching Equipment / Part exists for ${requestedName}. Choose explicitly.`; result.append(message);
    data.candidates.forEach((candidate) => { const row = document.createElement("div"); row.className = "resource-item";
        const details = document.createElement("span"); details.textContent = [candidate.display_name, candidate.manufacturer, candidate.model, candidate.part_no, candidate.material_code, candidate.matched_on.join(", ")].filter(Boolean).join(" · ");
        const use = document.createElement("button"); use.type = "button"; use.textContent = "Use Existing"; use.onclick = () => showEquipmentPart(candidate.resource_id); row.append(details, use); result.append(row); });
    const separate = document.createElement("button"); separate.type = "button"; separate.textContent = "Create Separate Equipment / Part"; separate.onclick = () => saveEquipmentPart(data.decision_token);
    const cancel = document.createElement("button"); cancel.type = "button"; cancel.textContent = "Cancel"; cancel.onclick = () => result.classList.add("hidden"); result.append(separate, cancel);
}

async function loadTagKnowledge(node) {
    selectedKnowledgeTag = node;
    const panel = document.getElementById("tag-knowledge-panel");
    const status = document.getElementById("knowledge-status");
    panel.classList.remove("hidden");
    document.getElementById("knowledge-preview").classList.add("hidden");
    knowledgeAttachments = emptyKnowledgeAttachments();
    renderAllKnowledgeAttachments();
    status.textContent = "Loading Tag Knowledge…";
    status.className = "tree-counts";
    try {
        const response = await fetch("/api/tag-knowledge/load", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(knowledgeIdentityPayload(node)),
        });
        const data = await response.json();
        if (selectedKnowledgeTag !== node) return;
        if (!data.success) throw new Error(data.error || "Unable to load Tag Knowledge.");
        const knowledge = data.knowledge;
        const details = data.tag.tag_details || {};
        document.getElementById("knowledge-directory").textContent = knowledge.km_directory;
        document.getElementById("knowledge-updated").textContent = knowledge.updated_at || "—";
        Object.entries(knowledge.fields).forEach(([key, value]) => {
            const id = `knowledge-${key.replaceAll("_", "-")}`;
            document.getElementById(id).value = value;
        });
        knowledgeAttachments = emptyKnowledgeAttachments();
        Object.keys(knowledgeSectionLabels).forEach((section) => {
            knowledgeAttachments[section] = [...(knowledge.attachments?.[section] || [])];
        });
        renderAllKnowledgeAttachments();
        status.textContent = "";
    } catch (error) {
        if (selectedKnowledgeTag !== node) return;
        status.textContent = error.message || "Unable to load Tag Knowledge.";
        status.className = "error-message";
    }
}

document.getElementById("tag-knowledge-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!kmTagWriteEnabled || !selectedKnowledgeTag) return;
    const result = document.getElementById("knowledge-result");
    try {
        const payload = {
            ...knowledgeIdentityPayload(), ...knowledgeFieldsPayload(),
            attachments: knowledgeAttachments,
        };
        const response = await fetch("/api/tag-knowledge/preview", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
        });
        const data = await response.json();
        if (!data.success) throw new Error(data.error || "Unable to preview Tag Knowledge.");
        payload.preview_created_at = data.preview.created_at;
        payload.attachments = data.preview.attachments;
        pendingKnowledgePayload = JSON.parse(JSON.stringify(payload));
        document.getElementById("knowledge-preview-tag").textContent = data.preview.kepware_path;
        document.getElementById("knowledge-preview-directory").textContent = data.preview.km_directory;
        document.getElementById("knowledge-preview-version").textContent = String(data.preview.new_version);
        document.getElementById("knowledge-preview-file").textContent = data.preview.new_file;
        const previewFields = document.getElementById("knowledge-preview-fields");
        previewFields.replaceChildren();
        visibleKnowledgeSections.forEach((section) => {
            const label = knowledgeSectionLabels[section];
            const block = document.createElement("section");
            block.className = "knowledge-preview-section";
            const heading = document.createElement("h5");
            heading.textContent = label;
            const text = document.createElement("p");
            text.textContent = data.preview.fields?.[section] || "(empty)";
            const images = document.createElement("div");
            images.className = "knowledge-preview-images";
            (data.preview.attachments?.[section] || []).forEach((attachment) => {
                const figure = document.createElement("figure");
                figure.className = "knowledge-preview-image";
                const image = document.createElement("img");
                image.src = knowledgeAttachmentReadUrl(attachment);
                image.alt = attachment.caption || attachment.original_filename || "Tag Knowledge image";
                const caption = document.createElement("figcaption");
                caption.textContent = attachment.caption || attachment.original_filename || attachment.relative_path;
                figure.append(image, caption);
                images.appendChild(figure);
            });
            block.append(heading, text, images);
            previewFields.appendChild(block);
        });
        document.getElementById("knowledge-preview").classList.remove("hidden");
        result.classList.add("hidden");
    } catch (error) {
        result.textContent = error.message || "Unable to preview Tag Knowledge.";
        result.className = "create-result error-message";
    }
});

document.getElementById("cancel-knowledge-save").addEventListener("click", () => {
    pendingKnowledgePayload = null;
    document.getElementById("knowledge-preview").classList.add("hidden");
});

document.getElementById("confirm-knowledge-save").addEventListener("click", async () => {
    if (!kmTagWriteEnabled || !selectedKnowledgeTag || !pendingKnowledgePayload) return;
    const button = document.getElementById("confirm-knowledge-save");
    const result = document.getElementById("knowledge-result");
    button.disabled = true;
    try {
        const response = await fetch("/api/tag-knowledge/save", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(pendingKnowledgePayload),
        });
        const data = await response.json();
        if (!data.success) throw new Error(data.error || "Unable to save Tag Knowledge.");
        result.textContent = `Saved Knowledge version ${data.knowledge.version}: ${data.knowledge.active_file}`;
        result.className = "create-result success-message";
        document.getElementById("knowledge-preview").classList.add("hidden");
        pendingKnowledgePayload = null;
        await loadTagKnowledge(selectedKnowledgeTag);
    } catch (error) {
        result.textContent = error.message || "Unable to save Tag Knowledge.";
        result.className = "create-result error-message";
    } finally {
        button.disabled = false;
    }
});

function setTagProperty(id, value) {
    const detail = document.getElementById(id);
    const label = detail.previousElementSibling;
    const available = value !== null && value !== undefined && value !== "";
    detail.textContent = available ? String(value) : "";
    detail.classList.toggle("hidden", !available);
    label.classList.toggle("hidden", !available);
}
