// DocVerify Frontend Logic

const API = '';
let statusPollInterval = null;

// --- Init ---
document.addEventListener('DOMContentLoaded', () => {
    initTabs();
    refreshAll();
    // Poll status every 3s when pipeline is running
    statusPollInterval = setInterval(pollStatus, 3000);
});

// --- Tabs ---
function initTabs() {
    document.querySelectorAll('.tab').forEach(tab => {
        tab.addEventListener('click', () => {
            document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
            document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
            tab.classList.add('active');
            document.getElementById('page-' + tab.dataset.page).classList.add('active');

            // Refresh data when switching to a tab
            const page = tab.dataset.page;
            if (page === 'inbox') refreshInbox();
            if (page === 'documents') refreshDocuments();
            if (page === 'results') refreshResults();
            if (page === 'feedback') refreshFeedback();
            if (page === 'config') loadConfig();
        });
    });
}

// --- API Helpers ---
async function api(path, opts = {}) {
    try {
        const resp = await fetch(API + path, {
            headers: { 'Content-Type': 'application/json' },
            ...opts,
        });
        return await resp.json();
    } catch (e) {
        console.error('API error:', path, e);
        return null;
    }
}

function toast(msg, type = 'info') {
    const container = document.getElementById('toasts');
    const el = document.createElement('div');
    el.className = 'toast ' + type;
    el.textContent = msg;
    container.appendChild(el);
    setTimeout(() => el.remove(), 4000);
}

// --- Status Polling ---
async function pollStatus() {
    const data = await api('/api/status');
    if (!data) return;

    const pill = document.getElementById('status-pill');
    const text = document.getElementById('status-text');
    const dot = document.getElementById('status-dot');

    pill.className = 'status-pill ' + data.status;
    text.textContent = data.status.toUpperCase();

    if (data.status === 'running') {
        dot.innerHTML = '<div class="spinner"></div>';
    } else {
        dot.innerHTML = '';
    }

    // Update dashboard stats
    if (data.last_run) {
        document.getElementById('stat-groups').textContent = data.last_run.total_groups || '—';
        document.getElementById('stat-passed').textContent = data.last_run.passed || '—';
        document.getElementById('stat-failed').textContent = data.last_run.failed || '—';

        const card = document.getElementById('last-run-card');
        card.style.display = 'block';
        document.getElementById('last-run-content').innerHTML = `
            <div style="font-size:13px;color:var(--text-dim)">
                Last run: ${data.last_run.timestamp ? new Date(data.last_run.timestamp).toLocaleString() : '—'}
                &nbsp;|&nbsp; ${data.last_run.total_groups} groups
                &nbsp;|&nbsp; <span style="color:var(--green)">${data.last_run.passed} PASS</span>
                &nbsp;|&nbsp; <span style="color:var(--red)">${data.last_run.failed} FAIL</span>
            </div>
        `;
    }

    // Update pipeline log
    if (data.output && data.output.length > 0) {
        const logEl = document.getElementById('dash-log');
        logEl.innerHTML = data.output.map(line => {
            let cls = '';
            if (line.includes('PASS')) cls = 'success';
            if (line.includes('FAIL') || line.includes('Error')) cls = 'error';
            if (line.includes('WARN')) cls = 'warn';
            if (line.startsWith('[')) cls = 'info';
            return `<span class="log-line ${cls}">${escapeHtml(line)}</span>`;
        }).join('');
        logEl.scrollTop = logEl.scrollHeight;
    }
}

// --- Dashboard ---
async function refreshAll() {
    await pollStatus();
    refreshFeedbackQuick();
}

async function refreshLogs() {
    const data = await api('/api/logs');
    if (!data) return;

    const logEl = document.getElementById('debug-log');
    if (data.length === 0) {
        logEl.innerHTML = '<span style="color:var(--text-dim)">No pipeline output yet.</span>';
        return;
    }
    logEl.innerHTML = data.map(line => {
        let cls = '';
        if (line.includes('PASS')) cls = 'success';
        if (line.includes('FAIL') || line.includes('Error')) cls = 'error';
        return `<span class="log-line ${cls}">${escapeHtml(line)}</span>`;
    }).join('');
    logEl.scrollTop = logEl.scrollHeight;
}

async function runPipeline(mode) {
    toast('Starting pipeline...', 'info');
    const body = JSON.stringify({
        numeric_tolerance: parseFloat(document.getElementById('cfg-tolerance')?.value) || 0.0,
        use_llm: document.getElementById('cfg-use-llm')?.checked || false,
    });
    let result;
    if (mode === 'email') {
        result = await api('/api/pipeline/email', { method: 'POST', body: body });
    } else {
        result = await api('/api/pipeline/run', { method: 'POST', body: body });
    }
    if (result?.success) {
        toast('Pipeline started!', 'success');
    } else {
        toast(result?.error || 'Failed to start pipeline', 'error');
    }
}

async function runSimulation() {
    const num = prompt('How many simulated emails?', '5');
    if (!num) return;
    toast('Starting agent simulation...', 'info');
    const result = await api('/api/simulate', {
        method: 'POST',
        body: JSON.stringify({ num_emails: parseInt(num), dry_run: true }),
    });
    if (result?.success) {
        toast('Simulation started!', 'success');
    } else {
        toast(result?.error || 'Failed to start simulation', 'error');
    }
}

// --- Inbox ---
async function refreshInbox() {
    const data = await api('/api/inbox');
    if (!data) return;

    const tbody = document.getElementById('inbox-table');

    if (data.length === 0 || data[0]?.error) {
        const err = data[0]?.error || 'No emails found';
        tbody.innerHTML = `<tr><td colspan="5" style="color:var(--text-dim);text-align:center;padding:24px">
            ${escapeHtml(err)}
        </td></tr>`;
        return;
    }

    tbody.innerHTML = data.map(email => `
        <tr>
            <td>${escapeHtml(email.from || '—')}</td>
            <td>${escapeHtml(email.subject || '—')}</td>
            <td style="color:var(--text-dim);font-size:12px">${escapeHtml(email.date || '—')}</td>
            <td>${email.attachments > 0
                ? `<span class="badge badge-new">${email.attachments} file(s)</span>`
                : '<span style="color:var(--text-dim)">—</span>'}</td>
            <td>${email.read
                ? '<span class="badge badge-read">Read</span>'
                : '<span class="badge badge-new">New</span>'}</td>
        </tr>
    `).join('');
}

// --- Results ---
async function refreshResults() {
    const [results, scorecard] = await Promise.all([
        api('/api/results'),
        api('/api/scorecard'),
    ]);

    // Scorecard
    if (scorecard && scorecard.grouping_accuracy) {
        document.getElementById('scorecard-card').style.display = 'block';
        document.getElementById('scorecard-stats').innerHTML = `
            <div class="stat-card">
                <div class="stat-value">${scorecard.grouping_accuracy}</div>
                <div class="stat-label">Grouping</div>
            </div>
            <div class="stat-card">
                <div class="stat-value">${scorecard.recall}</div>
                <div class="stat-label">Recall</div>
            </div>
            <div class="stat-card">
                <div class="stat-value">${scorecard.precision}</div>
                <div class="stat-label">Precision</div>
            </div>
            <div class="stat-card">
                <div class="stat-value">${scorecard.f1}</div>
                <div class="stat-label">F1 Score</div>
            </div>
            <div class="stat-card">
                <div class="stat-value">${scorecard.localization_accuracy}</div>
                <div class="stat-label">Localization</div>
            </div>
            <div class="stat-card">
                <div class="stat-value ${scorecard.overall_pass ? 'green' : 'red'}">${scorecard.overall_pass ? 'PASS' : 'FAIL'}</div>
                <div class="stat-label">Overall</div>
            </div>
        `;
    }

    // Shipment groups
    const container = document.getElementById('results-list');
    if (!results?.shipments || results.shipments.length === 0) {
        container.innerHTML = `<div class="empty-state">
            <div class="icon">📋</div>
            <div class="title">No results yet</div>
            <div class="desc">Run the pipeline to see verification results</div>
        </div>`;
        return;
    }

    container.innerHTML = results.shipments.map(s => {
        const isPass = s.verdict === 'PASS';
        const badge = isPass ? 'badge-pass' : 'badge-fail';
        const findingCount = s.findings?.length || 0;
        const docCount = s.documents?.length || 0;

        return `
        <div class="card" style="cursor:pointer" onclick="showDetail('${s.group_id}')">
            <div style="display:flex;justify-content:space-between;align-items:center">
                <div>
                    <span style="font-weight:700;font-size:16px;color:var(--text-bright)">${s.group_id}</span>
                    <span class="badge ${badge}" style="margin-left:12px">${s.verdict}</span>
                </div>
                <div style="font-size:13px;color:var(--text-dim)">
                    ${docCount} doc(s) &nbsp;|&nbsp; ${findingCount} finding(s)
                </div>
            </div>
            ${findingCount > 0 ? `
            <div style="margin-top:12px">
                ${s.findings.slice(0, 3).map(f => `
                    <div class="finding-card" style="padding:8px 12px;margin-bottom:4px">
                        <span class="badge badge-${f.severity}" style="margin-right:8px">${f.severity}</span>
                        <span style="font-size:13px">${escapeHtml(f.field)}</span>
                        <span style="font-size:12px;color:var(--text-dim);margin-left:8px">${escapeHtml(f.message)}</span>
                    </div>
                `).join('')}
                ${findingCount > 3 ? `<div style="font-size:12px;color:var(--text-dim);padding:4px">+${findingCount - 3} more...</div>` : ''}
            </div>` : ''}
        </div>`;
    }).join('');
}

async function showDetail(groupId) {
    const data = await api('/api/results/' + groupId);
    if (!data || data.error) {
        toast('Group not found', 'error');
        return;
    }

    document.getElementById('detail-card').style.display = 'block';
    document.getElementById('detail-title').textContent = `${groupId} — ${data.verdict}`;

    const docs = data.documents || [];
    const findings = data.findings || [];

    let html = `
        <h3 style="font-size:14px;color:var(--text-dim);margin-bottom:12px">Documents (${docs.length})</h3>
        <table style="margin-bottom:20px">
            <thead><tr>
                <th>Doc ID</th><th>Type</th><th>Source</th>
            </tr></thead>
            <tbody>
                ${docs.map(d => `<tr>
                    <td style="font-family:monospace;font-size:12px">${d.doc_id?.substring(0, 12)}...</td>
                    <td>${d.doc_type || '—'}</td>
                    <td style="color:var(--text-dim)">${escapeHtml(d.source_path || '—')}</td>
                </tr>`).join('')}
            </tbody>
        </table>

        <h3 style="font-size:14px;color:var(--text-dim);margin-bottom:12px">Findings (${findings.length})</h3>
    `;

    if (findings.length === 0) {
        html += '<div style="color:var(--green);padding:12px">✓ No discrepancies found</div>';
    } else {
        html += findings.map(f => `
            <div class="finding-card">
                <div style="display:flex;justify-content:space-between;align-items:center">
                    <span class="finding-field">${escapeHtml(f.field)}</span>
                    <span class="badge badge-${f.severity}">${f.severity}</span>
                </div>
                <div class="finding-detail">${escapeHtml(f.message)}</div>
                <div class="finding-values">
                    <span class="expected">Expected: ${escapeHtml(String(f.value_a ?? '—'))}</span>
                    <span class="actual">Found: ${escapeHtml(String(f.value_b ?? '—'))}</span>
                </div>
            </div>
        `).join('');
    }

    document.getElementById('detail-content').innerHTML = html;
    document.getElementById('detail-card').scrollIntoView({ behavior: 'smooth' });
}

function closeDetail() {
    document.getElementById('detail-card').style.display = 'none';
}

// --- Feedback ---
async function refreshFeedback() {
    const [metrics, log] = await Promise.all([
        api('/api/feedback'),
        api('/api/feedback/log'),
    ]);

    if (metrics) {
        document.getElementById('fb-total').textContent = metrics.total_reviews || 0;
        document.getElementById('fb-confirmed').textContent = metrics.confirmed || 0;
        document.getElementById('fb-rejected').textContent = metrics.rejected || 0;
        document.getElementById('fb-accuracy').textContent =
            metrics.total_reviews > 0 ? (metrics.accuracy * 100).toFixed(1) + '%' : '—';

        // Error rate bars
        const fieldsContainer = document.getElementById('fb-fields');
        const fields = metrics.error_rate_by_field || {};
        const fieldEntries = Object.entries(fields).sort((a, b) => b[1] - a[1]);

        if (fieldEntries.length > 0) {
            fieldsContainer.innerHTML = fieldEntries.map(([field, rate]) => {
                const pct = (rate * 100).toFixed(1);
                const color = rate > 0.3 ? 'red' : rate > 0.1 ? 'yellow' : 'green';
                return `
                <div class="bar-row">
                    <div class="bar-label">${escapeHtml(field)}</div>
                    <div class="bar-track">
                        <div class="bar-fill ${color}" style="width:${pct}%"></div>
                    </div>
                    <div class="bar-value" style="color:var(--${color})">${pct}%</div>
                </div>`;
            }).join('');
        }
    }

    // Feedback log
    if (log && log.length > 0) {
        const tbody = document.getElementById('fb-log-table');
        tbody.innerHTML = log.map(r => `
            <tr>
                <td style="font-size:12px;color:var(--text-dim)">${new Date(r.timestamp).toLocaleString()}</td>
                <td>${escapeHtml(r.shipment_id)}</td>
                <td style="font-family:monospace;font-size:12px">${escapeHtml(r.field)}</td>
                <td><span class="badge ${
                    r.verdict === 'confirmed' ? 'badge-pass' :
                    r.verdict === 'rejected' ? 'badge-fail' : 'badge-medium'
                }">${r.verdict}</span></td>
                <td style="color:var(--text-dim)">${escapeHtml(r.notes || '—')}</td>
            </tr>
        `).join('');
    }
}

async function refreshFeedbackQuick() {
    const metrics = await api('/api/feedback');
    if (metrics) {
        document.getElementById('stat-accuracy').textContent =
            metrics.total_reviews > 0 ? (metrics.accuracy * 100).toFixed(0) + '%' : '—';
    }
}

async function refreshFeedbackLog() {
    const log = await api('/api/feedback/log');
    if (!log || log.length === 0) return;

    const tbody = document.getElementById('fb-log-table');
    tbody.innerHTML = log.map(r => `
        <tr>
            <td style="font-size:12px;color:var(--text-dim)">${new Date(r.timestamp).toLocaleString()}</td>
            <td>${escapeHtml(r.shipment_id)}</td>
            <td style="font-family:monospace;font-size:12px">${escapeHtml(r.field)}</td>
            <td><span class="badge ${
                r.verdict === 'confirmed' ? 'badge-pass' :
                r.verdict === 'rejected' ? 'badge-fail' : 'badge-medium'
            }">${r.verdict}</span></td>
            <td style="color:var(--text-dim)">${escapeHtml(r.notes || '—')}</td>
        </tr>
    `).join('');
}

async function submitFeedback() {
    const shipmentId = document.getElementById('fb-ship-id').value.trim();
    const field = document.getElementById('fb-field').value.trim();
    const verdict = document.getElementById('fb-verdict').value;
    const notes = document.getElementById('fb-notes').value.trim();

    if (!shipmentId || !field) {
        toast('Shipment ID and Field are required', 'error');
        return;
    }

    const result = await api('/api/feedback/log', {
        method: 'POST',
        body: JSON.stringify({ shipment_id: shipmentId, field, verdict, notes }),
    });

    if (result?.success) {
        toast('Feedback logged!', 'success');
        document.getElementById('fb-ship-id').value = '';
        document.getElementById('fb-field').value = '';
        document.getElementById('fb-notes').value = '';
        refreshFeedback();
    } else {
        toast(result?.error || 'Failed to log feedback', 'error');
    }
}

// --- Config ---
async function loadConfig() {
    const data = await api('/api/config');
    if (!data) return;

    document.getElementById('cfg-llm-provider').value = data.LLM_PROVIDER || 'ollama';
    document.getElementById('cfg-ollama-url').value = data.OLLAMA_BASE_URL || '';
    document.getElementById('cfg-ollama-model').value = data.OLLAMA_MODEL || '';
    document.getElementById('cfg-email-from').value = data.EMAIL_FROM || '';
    document.getElementById('cfg-email-to').value = data.EMAIL_TO || '';
    document.getElementById('cfg-imap-host').value = data.EMAIL_HOST || '';
    document.getElementById('cfg-imap-user').value = data.EMAIL_USER || '';
    document.getElementById('cfg-tolerance').value = data.NUMERIC_TOLERANCE || '0.0';
}

async function saveConfig() {
    const updates = {
        LLM_PROVIDER: document.getElementById('cfg-llm-provider').value,
        OLLAMA_BASE_URL: document.getElementById('cfg-ollama-url').value,
        OLLAMA_MODEL: document.getElementById('cfg-ollama-model').value,
    };

    // Only update keys if user entered new values
    const anthropicKey = document.getElementById('cfg-anthropic-key').value;
    if (anthropicKey && !anthropicKey.includes('...')) {
        updates.ANTHROPIC_API_KEY = anthropicKey;
    }
    const geminiKey = document.getElementById('cfg-gemini-key').value;
    if (geminiKey && !geminiKey.includes('...')) {
        updates.GEMINI_API_KEY = geminiKey;
    }

    const result = await api('/api/config', {
        method: 'POST',
        body: JSON.stringify(updates),
    });

    if (result?.success) {
        toast('Config saved!', 'success');
    } else {
        toast(result?.error || 'Failed to save config', 'error');
    }
}

async function saveEmailConfig() {
    const updates = {
        EMAIL_FROM: document.getElementById('cfg-email-from').value,
        EMAIL_TO: document.getElementById('cfg-email-to').value,
        EMAIL_HOST: document.getElementById('cfg-imap-host').value,
        EMAIL_USER: document.getElementById('cfg-imap-user').value,
    };

    const resendKey = document.getElementById('cfg-resend-key').value;
    if (resendKey && !resendKey.includes('...')) {
        updates.RESEND_API_KEY = resendKey;
    }
    const imapPass = document.getElementById('cfg-imap-pass').value;
    if (imapPass && !imapPass.includes('...')) {
        updates.EMAIL_PASSWORD = imapPass;
    }

    const result = await api('/api/config', {
        method: 'POST',
        body: JSON.stringify(updates),
    });

    if (result?.success) {
        toast('Email config saved!', 'success');
    } else {
        toast(result?.error || 'Failed to save config', 'error');
    }
}

async function checkOllama() {
    const el = document.getElementById('ollama-status');
    el.innerHTML = '<span style="color:var(--yellow)">Checking...</span>';

    const data = await api('/api/health/ollama');
    if (!data) {
        el.innerHTML = '<span style="color:var(--red)">Connection failed</span>';
        return;
    }

    if (data.healthy) {
        el.innerHTML = `<span style="color:var(--green)">✓ Connected to ${escapeHtml(data.url)} — model "${escapeHtml(data.model)}" available</span>`;
    } else {
        el.innerHTML = `<span style="color:var(--red)">✗ Cannot reach ${escapeHtml(data.url || 'Ollama')} — ${escapeHtml(data.error || 'is Ollama running?')}</span>`;
    }
}

// --- Documents ---
async function refreshDocuments() {
    const data = await api('/api/documents');
    if (!data) return;

    const container = document.getElementById('doc-list');
    if (data.length === 0) {
        container.innerHTML = `<div class="empty-state" style="padding:24px">
            <div class="icon">📭</div>
            <div class="title">No documents</div>
            <div class="desc">Place .docx or .xlsx files in data/corpus/</div>
        </div>`;
        return;
    }

    container.innerHTML = `<div style="max-height:600px;overflow-y:auto">
        ${data.map(d => `
            <div class="finding-card" style="cursor:pointer;padding:10px 14px;margin-bottom:4px" onclick="viewDocument('${d.filename}')">
                <div style="display:flex;justify-content:space-between;align-items:center">
                    <div>
                        <span style="font-size:16px;margin-right:6px">${d.type === 'docx' ? '📄' : '📊'}</span>
                        <span style="font-weight:600;font-size:13px">${escapeHtml(d.filename)}</span>
                    </div>
                    <span style="font-size:11px;color:var(--text-dim)">${d.size_kb} KB</span>
                </div>
            </div>
        `).join('')}
    </div>`;
}

async function viewDocument(filename) {
    const data = await api('/api/documents/' + encodeURIComponent(filename));
    if (!data || data.error) {
        toast(data?.error || 'Failed to load document', 'error');
        return;
    }

    document.getElementById('doc-viewer-title').textContent = filename;

    let html = '';

    // Document type badge
    html += `<div style="margin-bottom:16px">
        <span class="badge badge-new" style="margin-right:8px">${data.type.toUpperCase()}</span>
        <span style="font-size:12px;color:var(--text-dim)">ID: ${data.doc_id?.substring(0, 16)}...</span>
    </div>`;

    // Parsed text
    if (data.text) {
        const lines = data.text.split('\n');
        html += `<div class="card-title" style="margin-bottom:8px">Extracted Text</div>`;
        html += `<div class="log-output" style="max-height:300px;margin-bottom:20px">`;
        html += lines.map(line => {
            const trimmed = line.trim();
            let cls = '';
            // Highlight key fields
            if (/order\s*no|ordine/i.test(trimmed)) cls = 'info';
            if (/container|bl\s*no|bill/i.test(trimmed)) cls = 'info';
            if (/weight|peso|kg/i.test(trimmed)) cls = 'success';
            if (/carton|colli/i.test(trimmed)) cls = 'success';
            if (/total/i.test(trimmed)) cls = 'warn';
            return `<span class="log-line ${cls}">${escapeHtml(line)}</span>`;
        }).join('');
        html += `</div>`;
    }

    // Tables
    if (data.tables && data.tables.length > 0) {
        html += `<div class="card-title" style="margin-bottom:8px">Tables (${data.tables.length})</div>`;
        data.tables.forEach((table, tIdx) => {
            if (table.length === 0) return;
            html += `<div style="margin-bottom:16px;overflow-x:auto">`;
            html += `<div style="font-size:11px;color:var(--text-dim);margin-bottom:4px">Table ${tIdx + 1} (${table.length} rows)</div>`;
            html += `<table>`;
            table.forEach((row, rIdx) => {
                html += `<tr>`;
                row.forEach(cell => {
                    const cellText = cell || '';
                    if (rIdx === 0) {
                        html += `<th>${escapeHtml(cellText)}</th>`;
                    } else {
                        // Highlight numeric values
                        const isNum = /^[\d.,]+$/.test(cellText.trim()) && cellText.trim();
                        html += `<td style="${isNum ? 'font-family:monospace;color:var(--accent)' : ''}">${escapeHtml(cellText)}</td>`;
                    }
                });
                html += `</tr>`;
            });
            html += `</table></div>`;
        });
    }

    document.getElementById('doc-viewer').innerHTML = html;
}

// --- Email Test ---
async function testEmail() {
    toast('Sending test email...', 'info');
    const result = await api('/api/email/test', { method: 'POST' });
    if (result?.success) {
        toast('Test email sent! Check your inbox. ID: ' + result.id, 'success');
    } else {
        toast('Email failed: ' + (result?.error || 'unknown error'), 'error');
    }
}

// --- Utils ---
function escapeHtml(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}
