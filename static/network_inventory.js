(() => {
    "use strict";
    const el = id => document.getElementById(`inventory-${id}`);
    const root = document.getElementById("network-inventory-workspace");
    if (!root) return;
    let rows = [], selected = null, generation = 0, detailGeneration = 0;
    let saving = false;
    let scanPending = false, progressTimer = null, progressEpoch = 0;
    let completedSummary = null;
    function renderCompletedSummary() {
        if (!completedSummary) return;
        const {finishedAt, online, mac} = completedSummary;
        const time = new Date(finishedAt).toLocaleTimeString([], {
            hour: 'numeric', minute: '2-digit', second: '2-digit', hour12: true});
        el('freshness').textContent = `Last scan: ${time} | ${online} online | ${mac} MAC`;
    }
    const duration = seconds => {
        const total = Math.max(0, Math.floor(seconds || 0));
        return `${String(Math.floor(total / 60)).padStart(2, '0')}:${String(total % 60).padStart(2, '0')}`;
    };
    function renderProgress(progress, finishedAt) {
        if (!progress?.status) return;
        if (scanPending && progress.status !== 'running') return;
        if (progress.status === 'idle') {
            el('scan').disabled = false;
            el('scan').textContent = 'Scan Now';
            return;
        }
        const running = progress.status === 'running';
        el('scan').disabled = running || scanPending;
        el('scan').textContent = running || scanPending ? 'Scanning...' : 'Scan Now';
        el('progress').hidden = false;
        if (running) {
            el('progress').textContent = `Scanning ${progress.network_name || 'configured networks'}\n` +
                `Network ${progress.network_number}/${progress.total_networks}\n` +
                `Progress: ${progress.scanned_ips} / ${progress.total_ips}\n` +
                `Current IP: ${progress.current_ip || 'Preparing'}\n` +
                `Online: ${progress.online_count}\nMAC Found: ${progress.mac_count}\n` +
                `Elapsed: ${duration(progress.elapsed_seconds)}\n${progress.phase || ''}` +
                '\nMAC count updates after each network\'s ARP collection.';
        } else if (progress.status === 'completed') {
            el('progress').hidden = true;
            el('progress').textContent = '';
            completedSummary = {
                scanId: progress.scan_id,
                finishedAt: finishedAt ? (/[zZ]$|[+-]\d\d:\d\d$/.test(finishedAt) ? finishedAt : `${finishedAt}Z`) :
                    (completedSummary?.scanId === progress.scan_id ? completedSummary.finishedAt : new Date().toISOString()),
                online: progress.online_count,
                mac: progress.mac_count,
            };
            renderCompletedSummary();
        } else {
            el('progress').textContent = 'Scan failed\n' +
                `${progress.scanned_ips} IPs scanned\n${progress.online_count} online\n` +
                `${progress.mac_count} MAC addresses found\nDuration: ${duration(progress.elapsed_seconds)}` +
                (progress.error ? `\n${progress.error}` : '');
        }
    }
    function stopProgressPolling() {
        ++progressEpoch;
        clearTimeout(progressTimer);
        progressTimer = null;
    }
    function scheduleProgressPolling() {
        if (progressTimer !== null) return;
        const epoch = progressEpoch;
        progressTimer = setTimeout(async () => {
            // Keep the timer occupied until the request finishes: no overlapping polls.
            let running = scanPending;
            try {
                const progress = await api('/progress');
                if (epoch !== progressEpoch) return;
                renderProgress(progress);
                running = scanPending || progress.status === 'running';
                if (!running && progress.status === 'completed') await refresh();
            } catch (error) {
                if (epoch !== progressEpoch) return;
                if (!el('progress').textContent.includes('Progress unavailable'))
                    el('progress').textContent += '\nProgress unavailable; checking again...';
                running = true;
            } finally {
                if (epoch === progressEpoch) {
                    progressTimer = null;
                    if (running) scheduleProgressPolling();
                }
            }
        }, 1000);
    }
    const editable = () => selected && selected.network_id !== null;
    const identity = row => `${row.network_id ?? row.NetworkId ?? 'legacy'}|${row.IPAddress}`;
    const networkQuery = value => value == null || value === 'all' || value === '' ? '' : `?network_id=${encodeURIComponent(value)}`;
    const rowNetwork = row => row.network_id === null ? 'legacy' : (row.network_id ?? row.NetworkId);
    const rowLabel = row => row.network_name ? `${row.network_name} / ${row.IPAddress}` : row.IPAddress;
    function updateManualState() {
        el("manual-selection").textContent = selected ? (editable() ? `Editing IP: ${rowLabel(selected)}` : 'Legacy / unassigned history is read-only') : "Select an IP to edit";
        for (const key of ["MachineName", "Description", "Location", "Remark", "Vendor", "DeviceType"]) {
            const field = el("manual").elements.namedItem(key);
            field.disabled = !editable() || saving;
            if (!selected) field.value = "";
        }
        el("manual-save").disabled = !editable() || saving;
    }
    updateManualState();
    const timestamp = value => value ? new Date(/[zZ]$|[+-]\d\d:\d\d$/.test(value) ? value : `${value}Z`).toLocaleString() : "Never";
    const cellText = (key, value) => /Time$|At$|^Last(Scan|Seen)$/.test(key) ? timestamp(value) : (value ?? "Unknown");
    const widthKey = 'opctagmanager.ot_inventory.column_widths';
    const columns = [
        ['ip_address', 'IP Address', 95, row => row.IPAddress],
        ['machine_name', 'Machine Name', 100, row => cellText('MachineName', row.MachineName)],
        ['status', 'Status', 100, row => cellText('Status', row.Status) + (row.Ambiguity ? ' (ambiguous)' : '')],
        ['vendor', 'Vendor', 120, row => cellText('Vendor', row.Vendor)],
        ['network', 'Network', 80, row => row.network_name || row.NetworkName || 'Legacy / unassigned'],
        ['last_seen', 'Last Seen', 130, row => timestamp(row.LastSeen)],
        ['description_location', 'Description / Location', 140, row => [row.Description, row.Location].filter(Boolean).join(' / ')],
    ];
    let widths = {};
    try {
        const saved = JSON.parse(localStorage.getItem(widthKey));
        for (const [id, , min] of columns) {
            if (typeof saved?.[id] === 'number' && Number.isFinite(saved[id]))
                widths[id] = Math.max(min, Math.min(10000, saved[id]));
        }
    } catch (_) { /* Storage can be unavailable or contain invalid JSON. */ }
    function applyWidths() {
        let total = 0;
        for (const [id] of columns) {
            el(`col-${id}`).style.width = widths[id] ? `${widths[id]}px` : '';
            total += widths[id] || 0;
        }
        // Freeze all measured widths during a drag so the table cannot redistribute them.
        el('table').style.width = columns.every(([id]) => widths[id]) ? `${total}px` : '';
        el('table').style.minWidth = columns.every(([id]) => widths[id]) ? `${total}px` : '';
    }
    applyWidths();
    for (const [id, label, min] of columns) {
        const header = el(`heading-${id}`);
        const handle = document.createElement('span');
        handle.className = 'inventory-resize-handle';
        handle.title = `Drag to resize ${label}`;
        header.appendChild(handle);
        let drag = null;
        handle.addEventListener('pointerdown', event => {
            if (event.button !== 0) return;
            event.preventDefault(); event.stopPropagation();
            for (const [key, , minimum] of columns)
                widths[key] = Math.max(minimum, el(`heading-${key}`).getBoundingClientRect().width);
            drag = {x: event.clientX, width: widths[id], pointerId: event.pointerId};
            handle.setPointerCapture(event.pointerId);
            applyWidths();
        });
        handle.addEventListener('pointermove', event => {
            if (!drag || event.pointerId !== drag.pointerId) return;
            widths[id] = Math.max(min, Math.min(10000, Math.round(drag.width + event.clientX - drag.x)));
            applyWidths();
        });
        const finish = () => {
            if (!drag) return;
            drag = null;
            try { localStorage.setItem(widthKey, JSON.stringify(widths)); } catch (_) { /* Keep resizing usable. */ }
        };
        handle.addEventListener('pointerup', finish);
        handle.addEventListener('pointercancel', finish);
        handle.addEventListener('lostpointercapture', finish);
        handle.addEventListener('click', event => event.stopPropagation());
    }
    el('reset-widths').addEventListener('click', () => {
        widths = {};
        try { localStorage.removeItem(widthKey); } catch (_) { /* Keep reset usable. */ }
        applyWidths();
    });
    const viewState = () => JSON.stringify(['network', 'filter', 'search', 'sort'].map(id => el(id).value).concat(el('descending').checked));
    let loadedState = null;
    el('download').addEventListener('click', async () => {
        if (loadedState !== viewState()) {
            clearTimeout(debounce);
            await refresh();
            if (loadedState !== viewState()) return;
        }
        const escape = value => '"' + String(value ?? '').replace(/"/g, '""') + '"';
        const csv = '\uFEFF' + [columns.map(([, label]) => label), ...rows.map(row => columns.map(([, , , value]) => value(row)))]
            .map(record => record.map(escape).join(',')).join('\r\n') + '\r\n';
        const now = new Date();
        const pad = n => String(n).padStart(2, '0');
        const stamp = `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}_${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}`;
        const url = URL.createObjectURL(new Blob([csv], {type: 'text/csv;charset=utf-8'}));
        const link = document.createElement('a');
        link.href = url;
        link.download = `OT_Network_Inventory_${stamp}.csv`;
        document.body.appendChild(link);
        link.click(); link.remove();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
    });
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
        const requestedState = viewState();
        el("download").disabled = true;
        const params = new URLSearchParams({q: el("search").value, category: el("filter").value,
            sort: el("sort").value, descending: el("descending").checked});
        const network = el('network').value || 'all';
        if (network !== 'all') params.set('network_id', network);
        try {
            const data = await api(`?${params}`);
            if (request !== generation) return;
            rows = data.rows;
            loadedState = requestedState;
            el("download").disabled = false;
            if (!scanPending && data.progress) {
                const finishedAt = (data.network_summaries || []).find(
                    n => n.network_id === data.progress.network_id)?.last_run?.FinishedAt ||
                    (data.last_run?.NetworkId == null || data.last_run.NetworkId === data.progress.network_id ? data.last_run?.FinishedAt : undefined);
                renderProgress(data.progress, finishedAt);
                if (data.progress.status === 'running') scheduleProgressPolling();
            }
            if (data.networks) {
                el('network').replaceChildren();
                text(el('network'), 'option', 'All Networks').value = 'all';
                for (const item of data.networks) text(el('network'), 'option', `${item.network_name} — ${item.scan_start}-${item.scan_end}`).value = String(item.network_id);
                el('network').value = network;
            }
            const allMultiple = network === 'all' && data.networks?.length > 1;
            el("range").textContent = allMultiple ? `All Networks: ${data.networks.length} configured` : `IP range: ${data.scan_start}-${data.scan_end}`;
            el("freshness").textContent = allMultiple ? `Scanned: ${(data.network_summaries || []).filter(n => n.last_run).length}/${data.networks.length} networks` : `Scanned: ${timestamp(data.last_run?.FinishedAt)}`;
            el('freshness').title = (data.network_summaries || []).map(n => `${n.network_name}: ${timestamp(n.last_run?.FinishedAt)}`).join('\n');
            renderCompletedSummary();
            el("message").textContent = [data.last_run?.KepwareError,
                ...(data.network_summaries || []).map(n => n.last_run?.KepwareError ? `${n.network_name}: ${n.last_run.KepwareError}` : ''),
                rows.some(r => r.Ambiguity) ? 'Overlapping ranges: physical network is ambiguous without NIC binding; Candidate Free is withheld for those addresses.' : '',
                data.legacy_count ? `${data.legacy_count} legacy IPs have unassigned history (visible in All Networks).` : ''].filter(Boolean).join(' ');
            el("rows").replaceChildren();
            for (const row of rows) {
                const tr = document.createElement("tr");
                const ipCell = text(tr, "td", "");
                const button = text(ipCell, "button", row.IPAddress);
                button.type = "button";
                button.addEventListener("click", () => showDetails(row));
                for (const [, , , value] of columns.slice(1)) {
                    const display = value(row);
                    text(tr, 'td', display).title = display;
                }
                tr.addEventListener("click", event => { if (event.target !== button) showDetails(row); });
                el("rows").appendChild(tr);
            }
            if (selected) {
                const current = rows.find(r => identity(r) === identity(selected));
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
        el("detail-title").textContent = `${rowLabel(row)} — ${row.MachineName}`;
        el("current").replaceChildren();
        for (const key of ["NetworkId", "NetworkName", "Ambiguity", "IPAddress", "MachineName", "Status", "Vendor", "DeviceType", "DeviceModel", "MACAddress", "ObservedMACAddress", "ARPInterface", "ARPSource", "MACPrefix", "OUIVendor", "MACReason", "HostName", "KepwareChannel", "KepwareDevice", "Description", "Location", "Remark", "LastScan", "LastSeen", "Source", "ResponseMs", "DetectionSource", "ScanError"]) {
            const label = key === "MachineName" ? "Effective Machine Name" : key
                .replace(/([A-Z])([A-Z][a-z])/g, "$1 $2").replace(/([a-z])([A-Z])/g, "$1 $2");
            text(el("current"), "dt", label);
            text(el("current"), "dd", cellText(key, row[key]));
        }
        for (const key of ["MachineName", "Description", "Location", "Remark", "Vendor", "DeviceType"])
            el("manual").elements.namedItem(key).value = row.Manual?.[key] || "";
        el("histories").replaceChildren();
        el("detail-message").textContent = "Loading history…";
        try {
            const histories = await api(`/${row.IPAddress}/history${networkQuery(rowNetwork(row))}`);
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
        if (scanPending || el('scan').disabled) return;
        scanPending = true;
        stopProgressPolling();
        el("scan").disabled = true;
        el('scan').textContent = 'Scanning...';
        el('progress').hidden = false;
        el('progress').textContent = 'Starting scan...';
        scheduleProgressPolling();
        try {
            const result = await api(`/scan${networkQuery(el('network').value)}`, {method: "POST"});
            scanPending = false;
            stopProgressPolling();
            renderProgress(result.progress, result.runs?.[result.runs.length - 1]?.FinishedAt || result.run?.FinishedAt);
            await refresh();
        } catch (error) {
            scanPending = false;
            stopProgressPolling();
            el('progress').textContent = `Scan request failed: ${error.message}`;
            el('progress').hidden = false;
            el('message').textContent = error.message;
            // A disconnected POST does not cancel the server's scan.
            try {
                const progress = await api('/progress');
                if (progress.status === 'running' || progress.status === 'error') renderProgress(progress);
                if (progress.status === 'running') scheduleProgressPolling();
            } catch (_) {
                el('progress').textContent += '\nScan status unavailable; checking again...';
                scheduleProgressPolling();
            }
        } finally {
            if (progressTimer === null) {
                el('scan').disabled = false;
                el('scan').textContent = 'Scan Now';
            }
        }
    });
    el("manual").addEventListener("submit", async event => {
        event.preventDefault();
        if (!editable() || saving) return;
        const ip = selected.IPAddress;
        const network = rowNetwork(selected);
        const body = Object.fromEntries(new FormData(el("manual")));
        saving = true;
        updateManualState();
        el("manual-message").textContent = `Saving revision for ${ip}…`;
        try {
            await api(`/${ip}/manual${networkQuery(network)}`, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)});
            await refresh();
            el("manual-message").textContent = `Manual revision saved for ${ip}. Previous revisions preserved.`;
        } catch (error) { el("manual-message").textContent = error.message; }
        finally { saving = false; updateManualState(); }
    });
    let debounce;
    el('network').addEventListener('change', () => {
        selected = null;
        ++detailGeneration;
        updateManualState();
        el('detail').classList.add('hidden');
        el('manual-message').textContent = '';
        return refresh();
    });
    el("search").addEventListener("input", () => { clearTimeout(debounce); debounce = setTimeout(refresh, 180); });
    ["filter", "sort", "descending"].forEach(id => el(id).addEventListener("change", refresh));
    el("refresh").addEventListener("click", refresh);
    el("free").addEventListener("click", () => { el("filter").value = "Candidate Free"; el("search").value = ""; refresh(); });
    document.querySelector('[data-view="network-inventory"]').addEventListener("click", refresh);
})();
