/**
 * DOCKER SWARM SELF-HEALING DASHBOARD — App Logic
 * Topology, AI Analysis, Timeline, Blue-Green Deployment, SSE
 */

const API = "";
let eventCount = 0;
let aiCount = 0;

// ═══════════════════════════════════════════════════════════
//  TAB SWITCHING + MOBILE MENU
// ═══════════════════════════════════════════════════════════

function switchTab(name) {
    document.querySelectorAll(".tab-content").forEach(t => t.classList.remove("active"));
    document.querySelectorAll(".nav-item").forEach(n => n.classList.remove("active"));
    document.getElementById("tab-" + name)?.classList.add("active");
    document.querySelector(`.nav-item[data-tab="${name}"]`)?.classList.add("active");
    // Close mobile menu
    document.getElementById("sidebar")?.classList.remove("open");
    if (name === "topology") setTimeout(refresh, 100);
    if (name === "timeline") loadTimeline();
    if (name === "logs") loadLogs();
}

// ═══════════════════════════════════════════════════════════
//  LOG EXPLORER
// ═══════════════════════════════════════════════════════════

async function loadLogs() {
    const target = document.getElementById("log-target")?.value;
    if (!target) return;

    const viewer = document.getElementById("log-viewer");
    if (!viewer) return;

    try {
        viewer.innerHTML = '<div class="empty-state">Fetching logs...</div>';
        const r = await fetch(`${API}/api/logs/${target}?tail=200`).then(r => r.json());

        if (!r.logs || r.logs.startsWith("[ERROR]")) {
            viewer.innerHTML = `<div class="empty-state error">${r.logs || "No logs found"}</div>`;
            return;
        }

        // Format logs: highlight timestamps and keywords
        const formatted = r.logs
            .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
            .replace(/(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2})/g, '<span class="log-time">$1</span>')
            .replace(/(ERROR|CRITICAL|FAIL|Failed)/gi, '<span class="log-err">$1</span>')
            .replace(/(INFO|SUCCESS|OK)/gi, '<span class="log-ok">$1</span>');

        viewer.innerHTML = `<pre>${formatted}</pre>`;
        viewer.scrollTop = viewer.scrollHeight;
    } catch (e) {
        viewer.innerHTML = `<div class="empty-state error">Fetch failed: ${e.message}</div>`;
    }
}

document.getElementById("menu-toggle")?.addEventListener("click", () => {
    document.getElementById("sidebar")?.classList.toggle("open");
});

// ═══════════════════════════════════════════════════════════
//  SVG TOPOLOGY RENDERING
// ═══════════════════════════════════════════════════════════

function renderTopology(services, containers) {
    const canvas = document.getElementById("topology-canvas");
    if (!canvas) return;
    const W = canvas.clientWidth;
    const H = canvas.clientHeight;
    canvas.innerHTML = "";
    if (W < 10 || H < 10) return;

    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("width", W);
    svg.setAttribute("height", H);
    svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
    canvas.appendChild(svg);

    // Server manager
    const cx = W / 2, manY = 50;
    drawRect(svg, cx - 65, manY - 18, 130, 36, "#161b22", "#58a6ff", 2);
    drawText(svg, cx, manY + 5, "🐳 Server Manager", "#58a6ff", 11, true);

    // Services row
    const svcList = services || [];
    if (svcList.length === 0) return;
    const svcSpacing = Math.min(W / (svcList.length + 1), 260);
    const svcStartX = (W - svcSpacing * (svcList.length - 1)) / 2;
    const svcY = 140;

    svcList.forEach((svc, i) => {
        const sx = svcStartX + svcSpacing * i;
        const svcName = svc.name.replace("healstack_", "");
        const running = svc.replicas_running || 0;
        const desired = svc.replicas_desired || 0;
        const healthy = running >= desired;
        const color = healthy ? "#238636" : "#da3633";

        // Line to manager
        drawLine(svg, cx, manY + 18, sx, svcY - 24, "#30363d");

        // Service box
        drawRect(svg, sx - 65, svcY - 24, 130, 48, "#0d1117", color, 2);
        drawText(svg, sx, svcY - 4, svcName, "#f0f6fc", 11, true);
        drawText(svg, sx, svcY + 14, `${running}/${desired} replicas`, "#8b949e", 9, false);

        // Containers below
        const svcContainers = (containers || []).filter(c =>
            c.service_name && (
                c.service_name.includes(svcName.replace(/-/g, "_")) ||
                c.service_name.includes(svcName) ||
                c.service_name === svc.name
            )
        );

        const numC = svcContainers.length || 0;
        const cSpacing = Math.min(50, 130 / (numC + 1));
        const cStartX = sx - (numC - 1) * cSpacing / 2;
        const cY = svcY + 75;

        svcContainers.forEach((c, j) => {
            const ccx = cStartX + cSpacing * j;

            // Line
            drawLine(svg, sx, svcY + 24, ccx, cY - 14, "#30363d");

            // Dot color
            let fill = "#238636";
            if (c.status === "exited" || c.health === "unhealthy") fill = "#da3633";
            if (c.status === "restarting") fill = "#d29922";

            drawCircle(svg, ccx, cY, 13, fill, c.status === "running" ? 0.12 : 0);

            // Container short id
            const label = c.id || c.name?.slice(-8) || "?";
            drawText(svg, ccx, cY + 26, label.slice(0, 8), "#8b949e", 7, false);
        });
    });
}

function drawRect(svg, x, y, w, h, fill, stroke, sw) {
    const r = document.createElementNS("http://www.w3.org/2000/svg", "rect");
    r.setAttribute("x", x); r.setAttribute("y", y);
    r.setAttribute("width", w); r.setAttribute("height", h);
    r.setAttribute("rx", 6); r.setAttribute("fill", fill);
    r.setAttribute("stroke", stroke); r.setAttribute("stroke-width", sw);
    svg.appendChild(r);
}

function drawCircle(svg, cx, cy, r, fill, glowOpacity) {
    if (glowOpacity > 0) {
        const g = document.createElementNS("http://www.w3.org/2000/svg", "circle");
        g.setAttribute("cx", cx); g.setAttribute("cy", cy);
        g.setAttribute("r", r + 6); g.setAttribute("fill", fill);
        g.setAttribute("opacity", glowOpacity);
        svg.appendChild(g);
    }
    const c = document.createElementNS("http://www.w3.org/2000/svg", "circle");
    c.setAttribute("cx", cx); c.setAttribute("cy", cy);
    c.setAttribute("r", r); c.setAttribute("fill", fill);
    c.setAttribute("stroke", "#161b22"); c.setAttribute("stroke-width", 2);
    svg.appendChild(c);
}

function drawLine(svg, x1, y1, x2, y2, color) {
    const l = document.createElementNS("http://www.w3.org/2000/svg", "line");
    l.setAttribute("x1", x1); l.setAttribute("y1", y1);
    l.setAttribute("x2", x2); l.setAttribute("y2", y2);
    l.setAttribute("stroke", color); l.setAttribute("stroke-width", 1);
    l.setAttribute("stroke-dasharray", "4,3");
    svg.appendChild(l);
}

function drawText(svg, x, y, text, fill, size, bold) {
    const t = document.createElementNS("http://www.w3.org/2000/svg", "text");
    t.setAttribute("x", x); t.setAttribute("y", y);
    t.setAttribute("fill", fill); t.setAttribute("font-size", size);
    t.setAttribute("text-anchor", "middle");
    t.setAttribute("font-family", "'Inter', sans-serif");
    if (bold) t.setAttribute("font-weight", "600");
    t.textContent = text;
    svg.appendChild(t);
}

// ═══════════════════════════════════════════════════════════
//  DATA REFRESH
// ═══════════════════════════════════════════════════════════

async function refresh() {
    try {
        const [svcR, ctR, hR, mR] = await Promise.all([
            fetch(`${API}/api/services`).then(r => r.json()),
            fetch(`${API}/api/containers`).then(r => r.json()),
            fetch(`${API}/api/health`).then(r => r.json()),
            fetch(`${API}/api/metrics`).then(r => r.json()),
        ]);

        const services = svcR.services || [];
        const containers = ctR.containers || [];
        const pct = hR.health_pct ?? 100;
        const active = mR.health?.active ?? 0;

        // Metrics
        el("m-services", services.length);
        el("m-containers", containers.length);
        el("m-health", pct + "%");
        el("m-recovered", mR.recovery?.total_actions ?? 0);
        el("m-failures", active);

        // Health styling
        const hPill = document.querySelector(".metric-pill.healthy .metric-value");
        if (hPill) hPill.style.color = pct >= 80 ? "#238636" : pct >= 50 ? "#d29922" : "#da3633";

        const fPill = document.getElementById("m-fail-pill");
        if (fPill) fPill.style.display = active > 0 ? "flex" : "flex";

        // Status dot
        const dot = document.getElementById("status-dot");
        const st = document.getElementById("cluster-status");
        if (dot && st) {
            if (pct >= 80) { dot.className = "status-dot online"; st.textContent = "System Healthy"; }
            else { dot.className = "status-dot offline"; st.textContent = "Degraded"; }
        }

        // Disaster mode
        if (mR.disaster_mode) {
            st.textContent = "🌪️ DISASTER MODE";
        }

        renderTopology(services, containers);
    } catch (err) {
        console.error("Refresh:", err);
    }
}

function el(id, val) {
    const e = document.getElementById(id);
    if (e) e.textContent = val;
}

// ═══════════════════════════════════════════════════════════
//  SSE
// ═══════════════════════════════════════════════════════════

function connectSSE() {
    const src = new EventSource(`${API}/api/events/stream`);
    src.onmessage = function (ev) {
        try {
            const payload = JSON.parse(ev.data);
            addEvent(payload);
            if (payload.type === "ai_analysis") addAIEntry(payload.data);
            refresh();
        } catch (e) { }
    };
    src.onerror = () => { src.close(); setTimeout(connectSSE, 5000); };
}

function addEvent(ev) {
    const log = document.getElementById("event-log");
    if (!log) return;
    const div = document.createElement("div");
    const sev = ev.data?.severity?.toLowerCase?.() || "ok";
    div.className = `event-entry ${sev === "critical" ? "ev-crit" : sev === "warning" ? "ev-warn" : "ev-ok"}`;
    const t = new Date((ev.timestamp || 0) * 1000).toLocaleTimeString([], { hour12: false });
    const msg = ev.data?.message || JSON.stringify(ev.data || {}).slice(0, 80);
    div.innerHTML = `<span class="event-time">${t}</span>${ev.type}: ${msg}`;
    log.prepend(div);
    eventCount++;
    el("event-count", eventCount);
    while (log.childNodes.length > 80) log.removeChild(log.lastChild);
}

function addAIEntry(data) {
    const panel = document.getElementById("ai-panel");
    if (!panel) return;
    const empty = panel.querySelector(".empty-state");
    if (empty) empty.remove();

    const a = data.analysis || {};
    const div = document.createElement("div");
    div.className = "ai-entry";
    div.innerHTML = `
        <div class="ai-type">🔍 ${a.error_type || "Unknown"} <span style="color:var(--text-muted);font-weight:400">${a.severity || ""}</span></div>
        <div class="ai-human">${a.human_explanation || a.root_cause || ""}</div>
        <div class="ai-fix">💡 ${a.fix_instructions || ""}</div>
        <div class="ai-category">${a.category || ""}</div>
    `;
    panel.prepend(div);
    aiCount++;
    el("ai-count", aiCount);
    while (panel.childNodes.length > 20) panel.removeChild(panel.lastChild);
}

// ═══════════════════════════════════════════════════════════
//  TIMELINE
// ═══════════════════════════════════════════════════════════

async function loadTimeline() {
    try {
        const r = await fetch(`${API}/api/timeline`).then(r => r.json());
        const panel = document.getElementById("timeline-panel");
        if (!panel) return;
        const entries = r.entries || [];
        if (entries.length === 0) {
            panel.innerHTML = '<div class="empty-state">No events yet. Trigger a failure to see the full lifecycle.</div>';
            return;
        }
        panel.innerHTML = "";
        entries.reverse().forEach(e => {
            const div = document.createElement("div");
            div.className = "tl-entry";
            const t = new Date((e.timestamp || 0) * 1000).toLocaleTimeString([], { hour12: false });
            div.innerHTML = `
                <div class="tl-phase ${e.phase}">${e.phase}</div>
                <div class="tl-body">
                    <div class="tl-msg">${e.message}</div>
                    <div class="tl-svc">${e.service}</div>
                </div>
                <div class="tl-time">${t}</div>
            `;
            panel.appendChild(div);
        });
    } catch (e) {
        console.error("Timeline:", e);
    }
}

// ═══════════════════════════════════════════════════════════
//  SIMULATION CONTROLS
// ═══════════════════════════════════════════════════════════

const post = (url, body) => fetch(url, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body)
}).then(r => r.json()).catch(() => ({}));

function simKill(svc) { post(`${API}/api/simulate/kill-container`, { service: svc }); }
function simCrash(port) { post(`${API}/api/simulate/crash-service`, { port }); }
function simToggle(port) { post(`${API}/api/simulate/toggle-health`, { port }); }

async function simDisaster() {
    // Kill one container from each service in rapid succession
    await post(`${API}/api/simulate/kill-container`, { service: "healstack_api-gateway" });
    await post(`${API}/api/simulate/kill-container`, { service: "healstack_auth-service" });
    await post(`${API}/api/simulate/kill-container`, { service: "healstack_data-service" });
}

// ═══════════════════════════════════════════════════════════
//  BLUE-GREEN DEPLOYMENT
// ═══════════════════════════════════════════════════════════

async function startDeploy() {
    const service = document.getElementById("deploy-service").value;
    const image = document.getElementById("deploy-image").value;
    if (!image) { alert("Enter an image name"); return; }
    const status = document.getElementById("deploy-status");
    status.innerHTML = '<div class="ai-entry" style="border-left-color:var(--blue)">🚀 Deploying...</div>';
    const r = await post(`${API}/api/deploy`, { service, image });
    status.innerHTML = `<div class="ai-entry" style="border-left-color:var(--blue)">Status: ${r.status || "sent"}</div>`;
}

// ═══════════════════════════════════════════════════════════
//  INIT
// ═══════════════════════════════════════════════════════════

window.addEventListener("load", () => {
    refresh();
    connectSSE();
    setInterval(refresh, 5000);
});

window.addEventListener("resize", () => {
    if (document.getElementById("tab-topology")?.classList.contains("active")) {
        refresh();
    }
});
