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
            loadKepwareTree();
        }
    });
});

async function loadKepwareTree() {
    const status = document.getElementById("kepware-status");
    const error = document.getElementById("kepware-error");
    const treeContainer = document.getElementById("kepware-tree");

    try {
        const response = await fetch("/api/kepware/tree", { method: "GET" });
        const data = await response.json();

        if (!data.connected) {
            status.textContent = "Kepware Configuration API — Not Connected";
            status.className = "connection-status disconnected";
            error.textContent = data.error || "Kepware Configuration API is unavailable.";
            error.classList.remove("hidden");
            return;
        }

        status.textContent = "Kepware Configuration API — Connected";
        status.className = "connection-status connected";
        error.classList.add("hidden");
        showKepwareCounts(data.counts);

        const list = document.createElement("ul");
        list.className = "tree kepware-tree";
        data.tree.forEach((node) => list.appendChild(createKepwareNode(node)));
        treeContainer.replaceChildren(list);
    } catch (_error) {
        status.textContent = "Kepware Configuration API — Not Connected";
        status.className = "connection-status disconnected";
        error.textContent = "Unable to load the Kepware Configuration view.";
        error.classList.remove("hidden");
    }
}

function showKepwareCounts(counts) {
    const element = document.getElementById("kepware-counts");
    element.textContent = [
        `${counts.channels} channels`,
        `${counts.devices} devices`,
        `${counts.tag_groups} tag groups`,
        `${counts.tags} tags`,
    ].join(" · ");
    element.classList.remove("hidden");
}

function createKepwareNode(node) {
    const item = document.createElement("li");
    const button = document.createElement("button");
    button.type = "button";
    button.className = "kepware-object";
    button.textContent = node.name;
    button.dataset.objectType = node.object_type;
    button.addEventListener("click", () => selectKepwareObject(button, node));

    const type = document.createElement("span");
    type.className = "object-type-label";
    type.textContent = `(${node.object_type})`;

    if (node.children && node.children.length) {
        const details = document.createElement("details");
        const summary = document.createElement("summary");
        summary.append(button, type);
        details.appendChild(summary);

        const children = document.createElement("ul");
        children.className = "tree";
        node.children.forEach((child) => children.appendChild(createKepwareNode(child)));
        details.appendChild(children);
        item.appendChild(details);
    } else {
        item.append(button, type);
    }

    return item;
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
    document.getElementById("kepware-raw-properties").textContent = JSON.stringify(
        node.properties,
        null,
        2,
    );

    const tagDetails = node.tag_details || {};
    setTagProperty("kepware-tag-address", tagDetails.address);
    setTagProperty("kepware-tag-data-type", tagDetails.data_type);
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
