const runtimeTags = document.querySelectorAll(".tag-click");
let selectedRuntimeTag = null;
let selectedAlarm = null;
let alarmMp3Loaded = false;

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
const treePanel = document.querySelector(".tree-panel");
const detailsPanel = document.querySelector(".details-panel");
const mainPanelSplitter = document.getElementById("main-panel-splitter");
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
    const style = getComputedStyle(mainPanelSplitter);
    return (
        mainPanelSplitter.getBoundingClientRect().width +
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

    treePanel.style.flex = `0 0 ${leftWidth}px`;
    detailsPanel.style.flex = `0 0 ${rightWidth}px`;
    mainPanelSplitter.setAttribute("aria-valuenow", String(Math.round(mainPanelRatio * 100)));
}

function ratioFromPointer(clientX) {
    const workspaceRect = workspace.getBoundingClientRect();
    const splitterRect = mainPanelSplitter.getBoundingClientRect();
    const style = getComputedStyle(mainPanelSplitter);
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

mainPanelSplitter.addEventListener("pointerdown", (event) => {
    if (event.button !== 0) return;
    mainPanelSplitter.classList.add("dragging");
    document.body.style.userSelect = "none";

    const onPointerMove = (moveEvent) => {
        mainPanelRatio = ratioFromPointer(moveEvent.clientX);
        applyMainPanelRatio();
    };
    const onPointerUp = () => {
        mainPanelSplitter.classList.remove("dragging");
        document.body.style.userSelect = "";
        document.removeEventListener("pointermove", onPointerMove);
        document.removeEventListener("pointerup", onPointerUp);
        savePanelRatio();
    };

    document.addEventListener("pointermove", onPointerMove);
    document.addEventListener("pointerup", onPointerUp);
    event.preventDefault();
});

mainPanelSplitter.addEventListener("keydown", (event) => {
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
    });
});

applyMainPanelRatio();

runtimeTags.forEach((tag) => {
    tag.addEventListener("click", async () => {
        runtimeTags.forEach((item) => item.classList.remove("selected-tag"));
        tag.classList.add("selected-tag");
        selectedRuntimeTag = tag;
        document.getElementById("selected-tag-path").value = tag.dataset.path;
        document.getElementById("selected-tag-id").value = tag.dataset.tagid || "";
        await loadTagAlarm(tag.dataset.tagid);
    });
});

document.querySelectorAll(".alarm-filter-button").forEach((button) => {
    button.addEventListener("click", () => {
        document.querySelectorAll(".alarm-filter-button").forEach((item) => item.classList.toggle("active", item === button));
        const alarmOnly = button.dataset.alarmFilter === "alarm";
        runtimeTags.forEach((tag) => {
            tag.closest("li.leaf").classList.toggle("hidden", alarmOnly && tag.dataset.hasAlarm !== "true");
        });
    });
});

function alarmNumber(id) {
    const value = document.getElementById(id).value;
    return value === "" ? null : Number(value);
}

async function loadAlarmMp3(selected = "") {
    const select = document.getElementById("alarm-mp3");
    if (!alarmMp3Loaded) {
        const response = await fetch("/api/alarm-mp3");
        const data = await response.json();
        select.replaceChildren(...(data.files || []).map((file) => new Option(file.filename, file.filename)));
        alarmMp3Loaded = true;
    }
    if (selected && ![...select.options].some((option) => option.value === selected)) {
        select.add(new Option(`${selected} (missing from browse repository)`, selected));
    }
    select.value = selected;
}

function showAlarmForm(alarm) {
    selectedAlarm = alarm;
    document.getElementById("use-tag-as-alarm").classList.add("hidden");
    document.getElementById("alarm-form").classList.remove("hidden");
    document.getElementById("alarm-id").value = alarm?.alarm_id || "";
    document.getElementById("alarm-enable").checked = alarm?.enable_alarm ?? true;
    document.getElementById("alarm-mode").value = alarm?.alarm_mode || "HIGH";
    document.getElementById("alarm-threshold-high").value = alarm?.threshold_high ?? "";
    document.getElementById("alarm-threshold-low").value = alarm?.threshold_low ?? "";
    document.getElementById("alarm-priority").value = alarm?.priority ?? 1;
    document.getElementById("alarm-repeat").value = alarm?.repeat ?? 3;
    document.getElementById("delete-alarm").classList.toggle("hidden", !alarm);
    loadAlarmMp3(alarm?.mp3_file || "");
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

document.getElementById("use-tag-as-alarm").addEventListener("click", () => showAlarmForm(null));

document.getElementById("alarm-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!selectedRuntimeTag) return;
    const result = document.getElementById("alarm-result");
    const payload = {
        alarm_mode: document.getElementById("alarm-mode").value,
        threshold_high: alarmNumber("alarm-threshold-high"),
        threshold_low: alarmNumber("alarm-threshold-low"),
        mp3_file: document.getElementById("alarm-mp3").value,
        priority: Number(document.getElementById("alarm-priority").value),
        repeat: Number(document.getElementById("alarm-repeat").value),
        enable_alarm: document.getElementById("alarm-enable").checked,
    };
    const alarmId = document.getElementById("alarm-id").value;
    if (!alarmId) payload.tag_id = Number(selectedRuntimeTag.dataset.tagid);
    const response = await fetch(alarmId ? `/api/alarms/${alarmId}` : "/api/alarms", {
        method: alarmId ? "PUT" : "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
    });
    const data = await response.json();
    result.classList.remove("hidden");
    if (!response.ok || !data.success) {
        result.className = "create-result error-message";
        result.textContent = data.error || "Alarm save failed.";
        return;
    }
    result.className = data.reload_notified ? "create-result success-message" : "create-result warning-message";
    result.textContent = data.reload_notified
        ? "Alarm mapping saved and reload notified."
        : `Alarm mapping saved; reload not notified (${data.reload_error || "unknown"}).`;
    selectedRuntimeTag.dataset.hasAlarm = "true";
    await loadTagAlarm(selectedRuntimeTag.dataset.tagid);
});

document.getElementById("delete-alarm").addEventListener("click", async () => {
    if (!selectedAlarm || !window.confirm("Remove this Alarm mapping?")) return;
    const response = await fetch(`/api/alarms/${selectedAlarm.alarm_id}`, { method: "DELETE" });
    const data = await response.json();
    const result = document.getElementById("alarm-result");
    result.classList.remove("hidden");
    if (!response.ok || !data.success) {
        result.className = "create-result error-message";
        result.textContent = data.error || "Alarm delete failed.";
        return;
    }
    selectedRuntimeTag.dataset.hasAlarm = "false";
    selectedAlarm = null;
    document.getElementById("alarm-form").classList.add("hidden");
    document.getElementById("alarm-status").textContent = "Not configured";
    document.getElementById("use-tag-as-alarm").classList.remove("hidden");
    result.className = data.reload_notified ? "create-result success-message" : "create-result warning-message";
    result.textContent = data.reload_notified
        ? "Alarm mapping removed and reload notified."
        : `Alarm mapping removed; reload not notified (${data.reload_error || "unknown"}).`;
});

document.getElementById("preview-alarm-mp3").addEventListener("click", () => {
    const filename = document.getElementById("alarm-mp3").value;
    if (!filename) return;
    const audio = document.getElementById("alarm-preview-audio");
    audio.src = `/api/alarm-mp3/${encodeURIComponent(filename)}/preview`;
    audio.classList.remove("hidden");
    audio.play();
});

const viewTabs = document.querySelectorAll(".view-tab");
let kepwareLoaded = false;
let loadedCounts = { channels: 0, devices: 0, tag_groups: 0, tags: 0 };
const kepwareWriteEnabled =
    document.getElementById("kepware-tree-view").dataset.writeEnabled === "true";
const kepwareTreeView = document.getElementById("kepware-tree-view");
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
let resourceForLinking = null;
let resourceTargetTags = new Map();
let resourceTagSelectionMode = false;
let pendingSimilarUpload = null;

viewTabs.forEach((tab) => {
    tab.addEventListener("click", () => {
        const isKepware = tab.dataset.view === "kepware";
        viewTabs.forEach((item) => item.classList.toggle("active", item === tab));
        document.getElementById("runtime-tree-view").classList.toggle("hidden", isKepware);
        document.getElementById("kepware-tree-view").classList.toggle("hidden", !isKepware);
        document.getElementById("runtime-details-view").classList.toggle("hidden", isKepware);
        document.getElementById("kepware-details-view").classList.toggle("hidden", !isKepware);
        document.getElementById("refresh-form").classList.toggle("hidden", isKepware);
        document.getElementById("full-reconcile").classList.toggle("hidden", isKepware);

        if (isKepware && !kepwareLoaded) {
            kepwareLoaded = true;
            loadKepwareChannels();
        }
        if (!isKepware) {
            loadRuntimeStatus();
        }
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

async function loadRuntimeStatus() {
    try {
        const response = await fetch("/api/runtime/status");
        const data = await response.json();
        document.getElementById("historian-ownership").textContent =
            data.historian_ownership === "legacy_opc_service"
                ? `Legacy expected / process ${data.legacy_historian_process_state || "unknown"}`
                : data.historian_ownership;
        document.getElementById("supervisor-state").textContent = data.supervisor_enabled ? "Enabled" : "Disabled";
        document.getElementById("worker-state").textContent = data.worker_state || "unknown";
        document.getElementById("runtime-opc-state").textContent = data.opc_state || "unknown";
        document.getElementById("runtime-tag-count").textContent =
            data.tagmaster_active_count == null ? "Unknown" : `${data.tagmaster_active_count} Active`;
        document.getElementById("runtime-subscriber-count").textContent =
            data.subscribed_tag_count == null ? "Unknown" : data.subscribed_tag_count;
        document.getElementById("runtime-influx-state").textContent = data.influx_state || "unknown";
        document.getElementById("runtime-rebuild-state").textContent = data.rebuild_pending ? "Pending" : "No pending rebuild";
    } catch (_error) {
        document.getElementById("worker-state").textContent = "status unavailable";
    }
}

// Tag Configuration is intentionally the default on every full page load/refresh.
document.querySelector('.view-tab[data-view="kepware"]').click();

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
        loadTagKnowledge(node);
        loadTagResources(node);
    } else {
        resetCreateTagPanel();
        selectedTemplateCandidate = null;
        document.getElementById("use-tag-template").classList.add("hidden");
        resetTagKnowledgePanel();
    }

    if (node.object_type !== "Tag") resetTagKnowledgePanel();
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

function resetTagKnowledgePanel() {
    selectedKnowledgeTag = null;
    pendingKnowledgePayload = null;
    document.getElementById("tag-knowledge-panel").classList.add("hidden");
    document.getElementById("tag-knowledge-form").reset();
    document.getElementById("knowledge-preview").classList.add("hidden");
    document.getElementById("knowledge-result").classList.add("hidden");
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
        document.getElementById("knowledge-kepware-path").textContent = knowledge.kepware_path;
        document.getElementById("knowledge-address").textContent = details.address ?? "";
        document.getElementById("knowledge-data-type").textContent = friendlyEnumValue("new-tag-data-type", details.data_type);
        document.getElementById("knowledge-scan-rate").textContent = details.scan_rate ?? "";
        document.getElementById("knowledge-access").textContent = friendlyEnumValue("new-tag-access", details.access);
        document.getElementById("knowledge-directory").textContent = knowledge.km_directory;
        document.getElementById("knowledge-version").textContent = knowledge.exists ? String(knowledge.version) : "—";
        document.getElementById("knowledge-updated").textContent = knowledge.updated_at || "—";
        Object.entries(knowledge.fields).forEach(([key, value]) => {
            const id = `knowledge-${key.replaceAll("_", "-")}`;
            document.getElementById(id).value = value;
        });
        status.textContent = knowledge.exists ? `Active Knowledge version ${knowledge.version}` : "No Tag Knowledge";
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
        const payload = {...knowledgeIdentityPayload(), ...knowledgeFieldsPayload()};
        const response = await fetch("/api/tag-knowledge/preview", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
        });
        const data = await response.json();
        if (!data.success) throw new Error(data.error || "Unable to preview Tag Knowledge.");
        payload.preview_created_at = data.preview.created_at;
        pendingKnowledgePayload = payload;
        document.getElementById("knowledge-preview-tag").textContent = data.preview.kepware_path;
        document.getElementById("knowledge-preview-directory").textContent = data.preview.km_directory;
        document.getElementById("knowledge-preview-version").textContent = String(data.preview.new_version);
        document.getElementById("knowledge-preview-file").textContent = data.preview.new_file;
        const fields = knowledgeFieldsPayload();
        document.getElementById("knowledge-preview-fields").textContent = Object.entries(fields)
            .map(([key, value]) => `${key.replaceAll("_", " ")}: ${value || "(empty)"}`)
            .join("\n");
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
