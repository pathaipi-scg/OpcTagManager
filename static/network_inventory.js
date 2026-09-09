(() => {
    "use strict";
    const el = id => document.getElementById(`inventory-${id}`);
    const root = document.getElementById("network-inventory-workspace");
    if (!root) return;
    let rows = [], selected = null, generation = 0, detailGeneration = 0;
    let saving = false;
    function updateManualState() {
        el("manual-selection").textContent = selected ? `Editing IP: ${selected.IPAddress}` : "Select an IP to edit";
        for (const key of ["MachineName", "Description", "Location", "Remark"]) {
            const field = el("manual").elements.namedItem(key);
            field.disabled = !selected || saving;
            if (!selected) field.value = "";
        }
        el("manual-save").disabled = !selected || saving;
    }
    updateManualState();
    const timestamp = value => value ? new Date(/[zZ]$|[+-]\d\d:\d\d$/.test(value) ? value : `${value}Z`).toLocaleString() : "Never";
    const cellText = (key, value) => /Time$|At$|^Last(Scan|Seen)$/.test(key) ? timestamp(value) : (value ?? "Unknown");
    async function api(path = "", options = {}) {
        const response = await fetch(`/api/network-inventory${path}`, options);
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || "Inventory request failed");
        return data;
    }
    function text(parent, tag, value) {
        const node = document.createElement(tag);
        node.textContent = value;
        parent.appendChild(node);
        return node;
    }
    async function refresh() {
        const request = ++generation;
        const params = new URLSearchParams({q: el("search").value, category: el("filter").value,
            sort: el("sort").value, descending: el("descending").checked});
        try {
            const data = await api(`?${params}`);
            if (request !== generation) return;
            rows = data.rows;
            el("range").textContent = `IP range: ${data.scan_start}-${data.scan_end}`;
            el("freshness").textContent = `Scanned: ${timestamp(data.last_run?.FinishedAt)}`;
            el("message").textContent = data.last_run?.KepwareError || "";
            el("rows").replaceChildren();
            for (const row of rows) {
                const tr = document.createElement("tr");
                const ipCell = text(tr, "td", "");
                const button = text(ipCell, "button", row.IPAddress);
                button.type = "button";
                button.addEventListener("click", () => showDetails(row));
                for (const key of ["MachineName", "Status", "KepwareDevice", "LastSeen"]) {
                    const value = cellText(key, row[key]);
                    text(tr, "td", value).title = value;
                }
                const description = [row.Description, row.Location].filter(Boolean).join(" / ");
                text(tr, "td", description).title = description;
                for (const key of ["Vendor", "DeviceType"]) {
                    const value = cellText(key, row[key]);
                    text(tr, "td", value).title = value;
                }
                tr.addEventListener("click", event => { if (event.target !== button) showDetails(row); });
                el("rows").appendChild(tr);
            }
            if (selected) {
                const current = rows.find(r => r.IPAddress === selected.IPAddress);
                if (current) await showDetails(current);
                else {
                    selected = null;
                    updateManualState();
                    el("manual-message").textContent = "";
                    ++detailGeneration;
                    el("detail").classList.add("hidden");
                }
            }
        } catch (error) {
            if (request === generation) el("message").textContent = error.message;
        }
    }
    async function showDetails(row) {
        selected = row;
        updateManualState();
        el("manual-message").textContent = "";
        const request = ++detailGeneration;
        el("detail").classList.remove("hidden");
        el("detail-title").textContent = `${row.IPAddress} — ${row.MachineName}`;
        el("current").replaceChildren();
        for (const key of ["IPAddress", "MachineName", "Status", "Vendor", "DeviceType", "DeviceModel", "MACAddress", "HostName", "KepwareChannel", "KepwareDevice", "Description", "Location", "Remark", "LastScan", "LastSeen", "Source", "ResponseMs", "DetectionSource", "ScanError"]) {
            const label = key === "MachineName" ? "Effective Machine Name" : key
                .replace(/([A-Z])([A-Z][a-z])/g, "$1 $2").replace(/([a-z])([A-Z])/g, "$1 $2");
            text(el("current"), "dt", label);
            text(el("current"), "dd", cellText(key, row[key]));
        }
        for (const key of ["MachineName", "Description", "Location", "Remark"])
            el("manual").elements.namedItem(key).value = row.Manual?.[key] || "";
        el("histories").replaceChildren();
        el("detail-message").textContent = "Loading history…";
        try {
            const histories = await api(`/${row.IPAddress}/history`);
            if (request !== detailGeneration) return;
            for (const [key, title] of [["network", "Network Scan History"], ["kepware", "Kepware History"], ["manual", "Manual Edit History"]]) {
                const section = text(el("histories"), "details", "");
                text(section, "summary", `${title} (${histories[key].length}) — newest first`);
                if (!histories[key].length) { text(section, "p", "No history recorded."); continue; }
                const scroll = text(section, "div", ""); scroll.className = "inventory-table-scroll";
                const table = text(scroll, "table", ""); table.className = "inventory-table";
                const columns = Object.keys(histories[key][0]);
                const header = text(text(table, "thead", ""), "tr", "");
                columns.forEach(col => text(header, "th", col));
                const body = text(table, "tbody", "");
                histories[key].forEach(record => {
                    const tr = text(body, "tr", "");
                    columns.forEach(col => text(tr, "td", cellText(col, record[col])));
                });
            }
            el("detail-message").textContent = "";
        } catch (error) { if (request === detailGeneration) el("detail-message").textContent = error.message; }
    }
    el("scan").addEventListener("click", async () => {
        el("scan").disabled = true;
        el("message").textContent = "Scanning the configured OT range and capturing Kepware. This can take several minutes…";
        try {
            await api("/scan", {method: "POST"});
            await refresh();
        } catch (error) { el("message").textContent = error.message; }
        finally { el("scan").disabled = false; }
    });
    el("manual").addEventListener("submit", async event => {
        event.preventDefault();
        if (!selected || saving) return;
        const ip = selected.IPAddress;
        const body = Object.fromEntries(new FormData(el("manual")));
        saving = true;
        updateManualState();
        el("manual-message").textContent = `Saving revision for ${ip}…`;
        try {
            await api(`/${ip}/manual`, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)});
            await refresh();
            el("manual-message").textContent = `Manual revision saved for ${ip}. Previous revisions preserved.`;
        } catch (error) { el("manual-message").textContent = error.message; }
        finally { saving = false; updateManualState(); }
    });
    let debounce;
    el("search").addEventListener("input", () => { clearTimeout(debounce); debounce = setTimeout(refresh, 180); });
    ["filter", "sort", "descending"].forEach(id => el(id).addEventListener("change", refresh));
    el("refresh").addEventListener("click", refresh);
    el("free").addEventListener("click", () => { el("filter").value = "Candidate Free"; el("search").value = ""; refresh(); });
    document.querySelector('[data-view="network-inventory"]').addEventListener("click", refresh);
})();
