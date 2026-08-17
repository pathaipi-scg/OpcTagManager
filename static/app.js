const runtimeTags = document.querySelectorAll(".tag-click");

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
    tag.addEventListener("click", () => {
        runtimeTags.forEach((item) => item.classList.remove("selected-tag"));
        tag.classList.add("selected-tag");
        document.getElementById("selected-tag-path").value = tag.dataset.path;
        document.getElementById("selected-tag-id").value = tag.dataset.tagid || "";
    });
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

        if (isKepware && !kepwareLoaded) {
            kepwareLoaded = true;
            loadKepwareChannels();
        }
    });
});

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
        result.className = "create-result success-message";
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
    if (!data.differences || !data.differences.length) {
        return `Created ${data.tag.full_path}. Returned properties match the request.`;
    }
    const differences = data.differences.map((difference) => {
        return `${difference.property}: requested ${JSON.stringify(difference.requested)}, returned ${JSON.stringify(difference.actual)}`;
    });
    return `Created ${data.tag.full_path}. Differences: ${differences.join("; ")}`;
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
            const versions = document.createElement("button"); versions.type = "button"; versions.textContent = "Versions";
            versions.addEventListener("click", () => showResourceVersions(link.resource));
            const unlink = document.createElement("button"); unlink.type = "button"; unlink.textContent = "Unlink"; unlink.disabled = !kmResourceWriteEnabled;
            unlink.className = "danger-button";
            unlink.addEventListener("click", () => unlinkResource(link.resource_id));
            const more = document.createElement("button"); more.type = "button"; more.textContent = "Link to More Tags"; more.disabled = !kmResourceWriteEnabled;
            more.addEventListener("click", () => beginTargetSelection(link.resource));
            const newVersion = document.createElement("button"); newVersion.type = "button"; newVersion.textContent = "Upload New Version"; newVersion.disabled = !kmResourceWriteEnabled;
            newVersion.addEventListener("click", () => showVersionUpload(link.resource));
            actions.append(versions, unlink, more, newVersion); item.append(type, name, details, actions);
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
    ["resource-search-view", "resource-upload-form", "resource-version-view", "resource-target-view"].forEach((id) =>
        document.getElementById(id).classList.toggle("hidden", id !== viewId));
    document.getElementById("resource-workflow-result").classList.add("hidden");
}

document.getElementById("link-existing-resource").addEventListener("click", async () => { showWorkflow("resource-search-view"); await searchResources(); });
document.getElementById("upload-new-resource").addEventListener("click", () => showWorkflow("resource-upload-form"));
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
