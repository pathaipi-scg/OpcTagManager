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
    status.textContent = "Kepware Configuration API — Loading…";
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

        status.textContent = "Kepware Configuration API — Connected";
        status.className = "connection-status connected";
        error.classList.add("hidden");
        loadedCounts = { channels: data.nodes.length, devices: 0, tag_groups: 0, tags: 0 };
        updateLoadedCounts();
        renderKepwareRoot(data.nodes);
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
    details.addEventListener("toggle", () => {
        if (details.open && details.dataset.loaded !== "true" && details.dataset.loading !== "true") {
            loadKepwareChildren(details, children, node);
        }
    });
    item.appendChild(details);
    return item;
}

async function loadKepwareChildren(details, container, node) {
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
        addLoadedCounts(data.nodes);
        document.getElementById("kepware-error").classList.add("hidden");
        document.getElementById("kepware-status").textContent = "Kepware Configuration API — Connected";
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
    status.textContent = "Kepware Configuration API — Temporarily Unavailable";
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

function setTagProperty(id, value) {
    const detail = document.getElementById(id);
    const label = detail.previousElementSibling;
    const available = value !== null && value !== undefined && value !== "";
    detail.textContent = available ? String(value) : "";
    detail.classList.toggle("hidden", !available);
    label.classList.toggle("hidden", !available);
}
