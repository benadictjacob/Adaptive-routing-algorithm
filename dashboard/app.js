/**
 * ═══════════════════════════════════════════════════════════════
 * AVRS — CROSS-ARCHITECTURE SIMULATOR CORE LOGIC
 * ═══════════════════════════════════════════════════════════════
 */

const API = "";
let nodes = [], edges = [], nodeMap = {};
let architecture = "microservice", config = {};
let canvas, ctx, canvasW, canvasH;
let transform = { x: 0, y: 0, scale: 0.8 };
let hoveredNode = null, draggedNode = null, isPanning = false, panStart = { x: 0, y: 0 };
let overlays = { latency: false, failures: false, congestion: false, clusters: false };
let lastClickTime = 0, mouseDownPos = { x: 0, y: 0 };

// Routing Animation State
let isAnimating = false;
let animationQueue = []; // { algo: 'adaptive'|'trad', path: [], hops: [], step: 0 }

// Colors (Canvas ignores CSS variables, using hex values)
const COLORS = {
    cyan: "#06b6d4",
    indigo: "#6366f1",
    emerald: "#10b981",
    amber: "#f59e0b",
    rose: "#f43f5e",
    textMid: "#94a3b8",
    bgItem: "#1a1a2e",
    border: "rgba(255, 255, 255, 0.1)"
};

// ─── INIT ───

window.onload = () => {
    canvas = document.getElementById("networkCanvas");
    ctx = canvas.getContext("2d");

    window.addEventListener("resize", resize);
    canvas.addEventListener("mousedown", onMouseDown);
    canvas.addEventListener("mousemove", onMouseMove);
    canvas.addEventListener("mouseup", onMouseUp);
    canvas.addEventListener("wheel", onWheel, { passive: false });

    resize();
    loadNetwork();
    updateMetrics();
    setInterval(updateMetrics, 5000);

    requestAnimationFrame(renderLoop);
};

function resize() {
    const rect = canvas.parentNode.getBoundingClientRect();
    canvasW = rect.width;
    canvasH = rect.height;

    // Support High DPI displays
    const dpr = window.devicePixelRatio || 1;
    canvas.width = canvasW * dpr;
    canvas.height = canvasH * dpr;
    canvas.style.width = canvasW + "px";
    canvas.style.height = canvasH + "px";

    ctx.scale(dpr, dpr);
}

// ─── DATA LOADING ───

async function loadNetwork() {
    try {
        const res = await fetch(API + "/api/network");
        const data = await res.json();
        nodes = data.nodes;
        edges = data.edges;
        architecture = data.architecture;
        config = data;  // store full response as config

        nodeMap = {};
        nodes.forEach(n => nodeMap[n.id] = n);

        updateUI();
        logEvent(`Architecture: ${data.label} initialized.`);
    } catch (e) {
        console.error("Load error:", e);
        logEvent("Error: Failed to fetch network data.");
    }
}

function updateUI() {
    document.getElementById("archTitle").textContent = config.label || architecture;
    document.getElementById("stat-density").textContent = `${nodes.length} nodes`;
    document.getElementById("stat-fail").textContent = `${((config.fail_prob || 0) * 100).toFixed(1)}%`;
    document.getElementById("stat-topo").textContent = (config.latency || "N/A").toUpperCase();

    // Populate start node dropdown
    const selStart = document.getElementById("startNode");
    const prevStart = selStart.value;
    selStart.innerHTML = nodes.map(n => `<option value="${n.id}">${n.id} (${n.role})</option>`).join("");
    if (nodes.find(n => n.id === prevStart)) selStart.value = prevStart;

    // Build role legend
    const legendEl = document.getElementById("roleLegend");
    if (legendEl && config.roles) {
        legendEl.innerHTML = config.roles.map(r => `
            <div class="legend-item">
                <span class="legend-dot" style="background:${CLUSTER_COLORS[r.color_idx]}"></span>
                <span class="legend-label">${r.name.replace(/_/g, ' ')}</span>
                <span class="legend-count">×${r.count}</span>
            </div>
        `).join("");
    }
}

// ─── RENDERING ───

function renderLoop() {
    ctx.clearRect(0, 0, canvasW, canvasH);

    ctx.save();
    // Center origin
    ctx.translate(canvasW / 2 + transform.x, canvasH / 2 + transform.y);
    ctx.scale(transform.scale, transform.scale);

    drawOverlays();

    // Edges
    ctx.beginPath();
    edges.forEach(e => {
        const s = nodeMap[e.source], t = nodeMap[e.target];
        if (s && t) {
            ctx.moveTo(s.x, s.y);
            ctx.lineTo(t.x, t.y);
        }
    });
    ctx.strokeStyle = "rgba(255, 255, 255, 0.08)";
    ctx.lineWidth = 1 / transform.scale;
    ctx.stroke();

    // Nodes
    nodes.forEach(n => {
        const isHovered = hoveredNode === n.id;
        const isNeighborOfHovered = hoveredNode && nodeMap[hoveredNode].neighbors.includes(n.id);

        const clusterColor = getClusterColor(n.cluster || 0);
        const statusColor = !n.alive ? COLORS.rose : (n.load > 15 ? COLORS.rose : (n.load > 8 ? COLORS.amber : clusterColor));

        // Cluster region ring (outer glow/neighbor highlight)
        ctx.beginPath();
        ctx.arc(n.x, n.y, (isHovered ? 16 : (isNeighborOfHovered ? 13 : 12)), 0, Math.PI * 2);
        ctx.fillStyle = isHovered ? "#ffffff" : clusterColor;
        ctx.globalAlpha = isHovered ? 0.3 : (isNeighborOfHovered ? 0.25 : 0.15);
        ctx.fill();
        ctx.globalAlpha = 1.0;

        // Node Body
        ctx.beginPath();
        ctx.arc(n.x, n.y, isHovered ? 10 : 7, 0, Math.PI * 2);
        ctx.fillStyle = statusColor;
        ctx.globalAlpha = n.alive ? (n.trust * 0.7 + 0.3) : 0.4;
        ctx.fill();
        ctx.globalAlpha = 1.0;

        // Status Ring
        if (!n.alive) {
            // Dead: red dashed ring
            ctx.beginPath();
            ctx.arc(n.x, n.y, isHovered ? 12 : 9, 0, Math.PI * 2);
            ctx.strokeStyle = COLORS.rose;
            ctx.lineWidth = 2.5 / transform.scale;
            ctx.setLineDash([4, 3]);
            ctx.stroke();
            ctx.setLineDash([]);
            // X mark
            const s = 4;
            ctx.beginPath();
            ctx.moveTo(n.x - s, n.y - s); ctx.lineTo(n.x + s, n.y + s);
            ctx.moveTo(n.x + s, n.y - s); ctx.lineTo(n.x - s, n.y + s);
            ctx.strokeStyle = COLORS.rose;
            ctx.lineWidth = 2 / transform.scale;
            ctx.stroke();
        } else if (isHovered) {
            ctx.beginPath();
            ctx.arc(n.x, n.y, 12, 0, Math.PI * 2);
            ctx.strokeStyle = "#ffffff";
            ctx.lineWidth = 2;
            ctx.stroke();
        } else if (isNeighborOfHovered) {
            ctx.beginPath();
            ctx.arc(n.x, n.y, 9, 0, Math.PI * 2);
            ctx.strokeStyle = "rgba(255,255,255,0.5)";
            ctx.lineWidth = 1;
            ctx.stroke();
        }

        // Vector Tag (if zoomed in or hovered)
        if (transform.scale > 1.2 || isHovered) {
            ctx.font = "10px JetBrains Mono";
            ctx.fillStyle = "rgba(255,255,255,0.6)";
            ctx.textAlign = "center";
            ctx.fillText(n.id, n.x, n.y - (isHovered ? 18 : 14));
        }
    });

    // Routing Paths
    drawRoutingPaths();

    ctx.restore();
    requestAnimationFrame(renderLoop);
}

// Cluster color palette — distinct colors for each region
const CLUSTER_COLORS = [
    "#06b6d4", // cyan
    "#a855f7", // purple
    "#f97316", // orange
    "#10b981", // emerald
    "#ec4899", // pink
    "#eab308", // yellow
];

function getClusterColor(cluster) {
    return CLUSTER_COLORS[cluster % CLUSTER_COLORS.length];
}

function getLoadColor(load, alive) {
    if (!alive) return COLORS.rose;
    if (load > 15) return COLORS.rose;
    if (load > 8) return COLORS.amber;
    return COLORS.emerald;
}

function drawRoutingPaths() {
    animationQueue.forEach(q => {
        if (!q.path || q.path.length < 2) return;

        ctx.beginPath();
        const start = nodeMap[q.path[0]];
        if (!start) return;
        ctx.moveTo(start.x, start.y);

        const shownSteps = Math.min(q.step, q.path.length);
        for (let i = 1; i < shownSteps; i++) {
            const n = nodeMap[q.path[i]];
            if (n) ctx.lineTo(n.x, n.y);
        }

        ctx.strokeStyle = q.algo === 'adaptive' ? COLORS.cyan : COLORS.textMid;
        ctx.lineWidth = 4 / transform.scale;
        ctx.lineJoin = "round";
        ctx.lineCap = "round";

        if (q.algo === 'adaptive') {
            ctx.shadowBlur = 15;
            ctx.shadowColor = COLORS.cyan;
        }
        ctx.stroke();
        ctx.shadowBlur = 0;

        // Packet head
        const currentId = q.path[Math.floor(q.step)];
        const node = nodeMap[currentId];
        if (node && q.step < q.path.length) {
            ctx.beginPath();
            ctx.arc(node.x, node.y, 10 / transform.scale, 0, Math.PI * 2);
            ctx.fillStyle = q.algo === 'adaptive' ? COLORS.cyan : "#ffffff";
            ctx.fill();
        }
    });
}

function drawOverlays() {
    if (overlays.latency) {
        ctx.fillStyle = "rgba(99, 102, 241, 0.03)";
        ctx.fillRect(-2000, -2000, 4000, 4000);
    }
    if (overlays.failures) {
        nodes.filter(n => !n.alive).forEach(n => {
            ctx.beginPath();
            ctx.arc(n.x, n.y, 40, 0, Math.PI * 2);
            ctx.fillStyle = "rgba(244, 63, 94, 0.04)";
            ctx.fill();
        });
    }
}

// ─── INTERACTIONS ───

function onMouseDown(e) {
    const p = getMousePos(e);
    mouseDownPos = { x: e.clientX, y: e.clientY };
    const node = findNodeAt(p.x, p.y);
    if (node) {
        draggedNode = node;
    } else {
        // Pan the canvas
        isPanning = true;
        panStart = { x: e.clientX - transform.x, y: e.clientY - transform.y };
    }
}

function onMouseMove(e) {
    const p = getMousePos(e);
    const node = findNodeAt(p.x, p.y);
    hoveredNode = node ? node.id : null;

    if (draggedNode) {
        const dx = e.clientX - mouseDownPos.x;
        const dy = e.clientY - mouseDownPos.y;
        // Only drag if moved more than 5px
        if (Math.sqrt(dx * dx + dy * dy) > 5) {
            draggedNode.x = (p.x - canvasW / 2 - transform.x) / transform.scale;
            draggedNode.y = (p.y - canvasH / 2 - transform.y) / transform.scale;
        }
    } else if (isPanning) {
        transform.x = e.clientX - panStart.x;
        transform.y = e.clientY - panStart.y;
    }

    updateTooltip(e, node);
    canvas.style.cursor = node ? "pointer" : (isPanning ? "grabbing" : "grab");
}

function onMouseUp(e) {
    if (draggedNode) {
        const dx = e.clientX - mouseDownPos.x;
        const dy = e.clientY - mouseDownPos.y;
        const dist = Math.sqrt(dx * dx + dy * dy);
        // Click (not drag) → toggle node alive/dead
        if (dist < 5) {
            toggleNode(draggedNode.id);
        }
    }
    draggedNode = null;
    isPanning = false;
}

function onWheel(e) {
    e.preventDefault();
    const zoom = e.deltaY < 0 ? 1.15 : 0.85;
    transform.scale = Math.max(0.1, Math.min(15, transform.scale * zoom));
}

function getMousePos(e) {
    const rect = canvas.getBoundingClientRect();
    return { x: e.clientX - rect.left, y: e.clientY - rect.top };
}

function findNodeAt(mx, my) {
    return nodes.find(n => {
        const nx = n.x * transform.scale + canvasW / 2 + transform.x;
        const ny = n.y * transform.scale + canvasH / 2 + transform.y;
        const dx = nx - mx;
        const dy = ny - my;
        return Math.sqrt(dx * dx + dy * dy) < 15;
    });
}

// ─── ANALYSIS ───

async function runAnalysis() {
    const start = document.getElementById("startNode").value;
    const target = [
        parseFloat(document.getElementById("v0").value),
        parseFloat(document.getElementById("v1").value),
        parseFloat(document.getElementById("v2").value),
        parseFloat(document.getElementById("v3").value)
    ];

    try {
        const res = await fetch(API + "/api/route", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ start, target })
        });
        const data = await res.json();

        // Handle section failure: all nodes in target section are dead
        if (data.section_failure) {
            const roleName = (data.target_role || 'unknown').replace(/_/g, ' ');
            logEvent(`SECTION FAILURE: All nodes in "${roleName}" section are dead. Route returns to source.`);

            // Show failure in decision panel
            const panel = document.getElementById("decisionBody");
            panel.innerHTML = `
                <div class="decision-card" style="border-color:var(--rose);background:rgba(244,63,94,0.1)">
                    <div class="dec-node" style="color:var(--rose)">SECTION FAILURE</div>
                    <div style="margin:8px 0;color:var(--text-high)">
                        All nodes in <strong style="color:var(--rose)">${roleName}</strong> section are dead.
                    </div>
                    <div style="color:var(--text-mid);font-size:12px">
                        Route cannot cross section boundary.<br>
                        Returning to source node <strong>${start}</strong>.
                    </div>
                </div>
            `;

            // Minimal animation: just blink at source
            animationQueue = [
                { algo: 'adaptive', path: [start], hops: [], step: 0 }
            ];
            return;
        }

        // Normal routing result
        const targetRole = (data.target_role || '').replace(/_/g, ' ');

        // Reset and populate animation
        animationQueue = [
            { algo: 'adaptive', path: data.adaptive.path, hops: data.adaptive.hops, step: 0 },
            { algo: 'trad', path: data.trad.path, step: 0 }
        ];

        // Dynamic step increment
        let st = 0;
        const interval = setInterval(() => {
            st += 0.2;
            animationQueue.forEach(q => q.step = st);

            // Trigger decision panel update on integer steps
            if (st % 1 < 0.2) {
                const hopIdx = Math.floor(st);
                if (data.adaptive.hops[hopIdx]) updateDecisionPanel(data.adaptive.hops[hopIdx]);
            }

            if (st > Math.max(data.adaptive.path.length, data.trad.path.length)) {
                clearInterval(interval);
            }
        }, 60);

        updateMetrics();

        if (!data.adaptive.success) {
            logEvent(`Route FAILED: crossed section boundary to "${targetRole}". Path returned to source.`);
        } else {
            logEvent(`Route: [${start}] -> ${targetRole} section (${data.adaptive.total_hops} hops)`);
        }
    } catch (e) { logEvent(`Error: ${e.message}`); }
}

function updateDecisionPanel(hop) {
    const panel = document.getElementById("decisionBody");
    if (!hop) return;
    if (hop.step === 0) panel.innerHTML = "";

    const card = document.createElement("div");
    card.className = "decision-card";

    const topScores = (hop.scores || []).slice(0, 4).map(s =>
        `<div class="score-row">
            <span>${s.neighbor}</span>
            <span class="score-val">${(s.score || 0).toFixed(3)}</span>
            <span class="score-meta">load:${s.load || 0}</span>
        </div>`
    ).join("");

    const dist = hop.distance !== undefined ? hop.distance : '?';
    const next = hop.chosen_next || (hop.is_terminal ? '✓ TARGET' : '✗ FAILED');
    const nextColor = hop.is_terminal ? 'var(--emerald)' : (hop.chosen_next ? 'var(--cyan)' : 'var(--rose)');

    card.innerHTML = `
        <div class="dec-node">STEP ${hop.step !== undefined ? hop.step : '?'}: ${hop.node_id}</div>
        <div class="dec-dist">Distance to target: ${typeof dist === 'number' ? dist.toFixed(4) : dist}</div>
        <div class="dec-scores">${topScores}</div>
        <div class="dec-next" style="color:${nextColor}">→ ${next}</div>
    `;
    panel.prepend(card);
}

// ─── CONTROLS ───

async function switchMode(mode) {
    try {
        const res = await fetch(API + "/api/architecture", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ mode })
        });
        animationQueue = [];
        loadNetwork();

        document.querySelectorAll(".arch-btn").forEach(b => {
            b.classList.toggle("active", b.textContent.toLowerCase().includes(mode));
        });
    } catch (e) { logEvent(`Error switching mode: ${e.message}`); }
}

// ─── NODE TOGGLE (click to kill / recover) ───

async function toggleNode(nodeId) {
    try {
        const res = await fetch(API + `/api/node/${nodeId}/toggle`, { method: "POST" });
        const data = await res.json();
        if (data.id) {
            loadNetwork();
            const stateLabels = {
                'ALIVE': '🟢 RECOVERED',
                'LOADED': '🟠 STRESSED (Amber)',
                'DEAD': '🔴 KILLED'
            };
            logEvent(`Node ${nodeId}: ${stateLabels[data.state] || 'Updated'}`);
        }
    } catch (e) {
        logEvent(`Error toggling node: ${e.message}`);
    }
}

async function simFailure(type) {
    try {
        await fetch(API + "/api/simulate/failure", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ type })
        });
        loadNetwork();
        logEvent(`Architecture event triggered: ${type}`);
    } catch (e) { logEvent(`Error: ${e.message}`); }
}

async function resetSystem() {
    await fetch(API + "/api/reset", { method: "POST" });
    animationQueue = [];
    loadNetwork();
    updateMetrics();
    document.getElementById("decisionBody").innerHTML = '<div class="empty-state">System reset and metrics cleared.</div>';
}



// ─── OVERLAYS & ZOOM ───

function toggleOverlay(name) {
    overlays[name] = !overlays[name];
}

function zoom(factor) {
    transform.scale = Math.max(0.1, Math.min(15, transform.scale * factor));
}

function resetZoom() {
    transform = { x: 0, y: 0, scale: 0.8 };
}

// ─── TIMELINE ───

let tlPlaying = false;
let tlInterval = null;

function tlStep(dir) {
    if (animationQueue.length === 0) return;
    const maxLen = Math.max(...animationQueue.map(q => q.path ? q.path.length : 0));
    animationQueue.forEach(q => {
        q.step = Math.max(0, Math.min(maxLen, q.step + dir));
    });
    document.getElementById("frameIdx").textContent = Math.floor(animationQueue[0]?.step || 0);
    document.getElementById("frameCount").textContent = maxLen;
    document.getElementById("tlSlider").value = maxLen > 0 ? (animationQueue[0].step / maxLen) * 100 : 0;
}

function tlPlay() {
    if (tlPlaying) {
        clearInterval(tlInterval);
        tlPlaying = false;
        return;
    }
    tlPlaying = true;
    const maxLen = Math.max(...animationQueue.map(q => q.path ? q.path.length : 0));
    if (maxLen === 0) return;

    // Reset to start
    animationQueue.forEach(q => q.step = 0);

    tlInterval = setInterval(() => {
        animationQueue.forEach(q => q.step += 0.15);
        const currentStep = animationQueue[0]?.step || 0;
        document.getElementById("frameIdx").textContent = Math.floor(currentStep);
        document.getElementById("frameCount").textContent = maxLen;
        document.getElementById("tlSlider").value = (currentStep / maxLen) * 100;

        if (currentStep >= maxLen) {
            clearInterval(tlInterval);
            tlPlaying = false;
        }
    }, 60);
}

// ─── UTILS ───

async function updateMetrics() {
    try {
        const res = await fetch(API + "/api/metrics");
        const data = await res.json();

        document.getElementById("m-ad-rate").textContent = `${data.adaptive.success_rate}%`;
        document.getElementById("m-ad-hops").textContent = data.adaptive.avg_hops;
        document.getElementById("m-ad-time").textContent = data.adaptive.avg_time.toFixed(2);

        document.getElementById("m-tr-rate").textContent = `${data.trad.success_rate}%`;
        document.getElementById("m-tr-hops").textContent = data.trad.avg_hops;
        document.getElementById("m-tr-time").textContent = data.trad.avg_time.toFixed(2);
    } catch (e) { }
}

function updateTooltip(e, node) {
    const panel = document.getElementById("nodeInspector");
    if (!panel) return;

    if (!node) return;

    const clusterColor = getClusterColor(node.cluster || 0);
    const roleLabel = (node.role || 'unknown').replace(/_/g, ' ');
    const statusLabel = node.alive ? 'ALIVE' : 'DEAD';
    const statusColor = node.alive ? '#10b981' : '#f43f5e';
    const neighborCount = (node.neighbors || []).length;

    panel.innerHTML = `
        <div class="insp-header">
            <span class="insp-dot" style="background:${clusterColor}"></span>
            <span class="insp-id">${node.id}</span>
            <span class="insp-status" style="color:${statusColor}">${statusLabel}</span>
        </div>
        <div class="insp-role" style="color:${clusterColor}">${roleLabel}</div>
        <div class="insp-details">
            <div class="insp-row">
                <span class="insp-label">Vector</span>
                <span class="insp-val mono" id="inspVector">[${node.vector.map(v => v.toFixed(2)).join(", ")}]</span>
            </div>
            <div class="insp-row">
                <span class="insp-label">Load</span>
                <span class="insp-val">${node.load}</span>
            </div>
            <div class="insp-row">
                <span class="insp-label">Trust</span>
                <span class="insp-val">${node.trust.toFixed(2)}</span>
            </div>
            <div class="insp-row">
                <span class="insp-label">Neighbors</span>
                <span class="insp-val">${neighborCount}</span>
            </div>
        </div>
        <div class="insp-actions" style="display:flex; gap:6px; margin-top:8px">
            <button class="btn btn-sm btn-primary" style="flex:1" onclick="setTargetVector('${node.vector.join(",")}')">Set as Target</button>
            <button class="btn btn-sm btn-ghost" onclick="copyVectorToClipboard('${node.vector.join(",")}')">Copy</button>
        </div>
        <div class="insp-hint">Click node to ${node.alive ? 'Kill' : 'Recover'}</div>
    `;
}

function setTargetVector(vecStr) {
    const vec = vecStr.split(",").map(Number);
    vec.forEach((v, i) => {
        const input = document.getElementById("v" + i);
        if (input) input.value = v.toFixed(2);
    });
    logEvent(`Target vector updated to: [${vecStr}]`);
}

function copyVectorToClipboard(vecStr) {
    navigator.clipboard.writeText(`[${vecStr}]`).then(() => {
        logEvent("Vector copied to clipboard.");
    });
}

function logEvent(msg) {
    const log = document.getElementById("eventLog");
    const now = new Date().toLocaleTimeString();
    const entry = document.createElement("div");
    entry.className = "log-entry";
    entry.innerHTML = `<span class="log-time">[${now}]</span> ${msg}`;
    log.prepend(entry);
    if (log.children.length > 30) log.removeChild(log.lastChild);
}

// ─── SIDEBAR RESIZE ───

(function initResize() {
    const grid = document.querySelector(".main-grid");
    const leftHandle = document.getElementById("resizeHandleLeft");
    const rightHandle = document.getElementById("resizeHandleRight");

    if (!grid || !leftHandle || !rightHandle) return;

    let activeSide = null; // 'left' or 'right'
    let leftWidth = 280;
    let rightWidth = 320;

    function updateGrid() {
        grid.style.gridTemplateColumns = `${leftWidth}px 1fr ${rightWidth}px`;
    }

    const startResize = (e, side) => {
        e.preventDefault();
        activeSide = side;
        document.body.style.cursor = "col-resize";
        document.body.style.userSelect = "none";
        (side === 'left' ? leftHandle : rightHandle).classList.add("active");
    };

    leftHandle.addEventListener("mousedown", (e) => startResize(e, 'left'));
    rightHandle.addEventListener("mousedown", (e) => startResize(e, 'right'));

    window.addEventListener("mousemove", (e) => {
        if (!activeSide) return;

        if (activeSide === 'left') {
            leftWidth = Math.max(250, Math.min(e.clientX, window.innerWidth * 0.4));
        } else {
            rightWidth = Math.max(200, Math.min(window.innerWidth - e.clientX, window.innerWidth * 0.5));
        }
        updateGrid();
    });

    window.addEventListener("mouseup", () => {
        if (!activeSide) return;
        (activeSide === 'left' ? leftHandle : rightHandle).classList.remove("active");
        activeSide = null;
        document.body.style.cursor = "";
        document.body.style.userSelect = "";
        resize(); // recalculate canvas size
    });
})();
