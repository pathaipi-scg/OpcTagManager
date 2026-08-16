const runtimeTags = document.querySelectorAll(".tag-click");

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
    setTagProperty("kepware-tag-data-type", tagDetails.data_type);
    setTagProperty("kepware-tag-scan-rate", tagDetails.scan_rate);
    setTagProperty("kepware-tag-description", tagDetails.description);
    setTagProperty("kepware-tag-access", tagDetails.access);
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
    document.getElementById("new-tag-data-type").value =
        templateTag?.tag_details?.data_type ?? configuredTagDefaults.dataType;
    document.getElementById("new-tag-scan-rate").value =
        templateTag?.tag_details?.scan_rate ?? configuredTagDefaults.scanRate;
    document.getElementById("new-tag-access").value =
        templateTag?.tag_details?.access ?? configuredTagDefaults.access;
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
    document.getElementById("preview-data-type").textContent = String(dataType);
    document.getElementById("preview-scan-rate").textContent = String(scanRate);
    document.getElementById("preview-access").textContent = String(access);
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
        document.getElementById("knowledge-data-type").textContent = details.data_type ?? "";
        document.getElementById("knowledge-scan-rate").textContent = details.scan_rate ?? "";
        document.getElementById("knowledge-access").textContent = details.access ?? "";
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
