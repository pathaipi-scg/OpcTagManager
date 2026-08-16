const runtimeTags = document.querySelectorAll(".tag-click");

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
let selectedDestinationNode = null;
let selectedDestinationDetails = null;
let selectedDestinationChildren = null;

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
    nodes.forEach((node) => list.appendChild(createKepwareNode(node)));
    document.getElementById("kepware-tree").replaceChildren(list);
}

function createKepwareNode(node) {
    const item = document.createElement("li");
    const button = document.createElement("button");
    button.type = "button";
    button.className = "kepware-object";
    button.textContent = node.name;
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
        data.nodes.forEach((child) => fragment.appendChild(createKepwareNode(child)));
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
        selectedDestinationNode = node;
        selectedDestinationDetails = button.kepwareDetails;
        selectedDestinationChildren = button.kepwareChildren;
        document.getElementById("add-kepware-tag-panel").classList.remove("hidden");
        document.getElementById("add-tag-destination").textContent =
            `Destination: ${destinationPath(node)}`;
        document.getElementById("create-tag-preview").classList.add("hidden");
        document.getElementById("create-tag-result").classList.add("hidden");
    } else {
        resetCreateTagPanel();
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
}

document.getElementById("add-kepware-tag-form").addEventListener("submit", (event) => {
    event.preventDefault();
    if (!kepwareWriteEnabled || !selectedDestinationNode) return;

    const name = document.getElementById("new-tag-name").value.trim();
    const address = document.getElementById("new-tag-address").value.trim();
    const description = document.getElementById("new-tag-description").value.trim();
    const result = document.getElementById("create-tag-result");
    if (!name || !address) {
        result.textContent = "Tag Name and Address are required.";
        result.className = "create-result error-message";
        return;
    }

    const destination = destinationPath(selectedDestinationNode);
    document.getElementById("preview-destination").textContent = destination;
    document.getElementById("preview-tag-name").textContent = name;
    document.getElementById("preview-address").textContent = address;
    document.getElementById("preview-description").textContent = description || "(not provided)";
    document.getElementById("preview-full-path").textContent = `${destination}/${name}`;
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

        result.textContent = `Created ${data.tag.full_path}`;
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

function setTagProperty(id, value) {
    const detail = document.getElementById(id);
    const label = detail.previousElementSibling;
    const available = value !== null && value !== undefined && value !== "";
    detail.textContent = available ? String(value) : "";
    detail.classList.toggle("hidden", !available);
    label.classList.toggle("hidden", !available);
}
