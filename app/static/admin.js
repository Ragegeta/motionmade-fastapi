const API_BASE = window.location.origin;
let adminToken = '';
let generatedFaqsFromUrl = [];

// ---------- Debug (triple-click logo toggles) ----------
(function () {
    const banner = document.getElementById('uiDebugBanner');
    const logoWrap = document.getElementById('logoWrap');
    if (!logoWrap || !banner) return;
    let clicks = 0;
    let t = 0;
    logoWrap.addEventListener('click', function () {
        clicks++;
        const now = Date.now();
        if (now - t > 400) clicks = 1;
        t = now;
        if (clicks >= 3) {
            clicks = 0;
            banner.classList.toggle('visible');
        }
    });
})();
function updateDebugTime() {
    const el = document.getElementById('debugTime');
    if (el) el.textContent = new Date().toLocaleTimeString();
}
setInterval(updateDebugTime, 1000);
updateDebugTime();
document.addEventListener('click', function (e) {
    const el = document.getElementById('debugLastClick');
    if (el) el.textContent = (e.target.id || e.target.className || e.target.tagName) + '';
}, true);
window.onerror = function (msg, src, line, col, err) {
    const el = document.getElementById('uiErrors');
    if (el) el.textContent = '[' + new Date().toLocaleTimeString() + '] ' + msg + '\n' + (el.textContent || '');
};
window.onunhandledrejection = function (e) {
    const el = document.getElementById('uiErrors');
    if (el) el.textContent = '[' + new Date().toLocaleTimeString() + '] ' + (e.reason && e.reason.message) + '\n' + (el.textContent || '');
};

function getHeaders() {
    return { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + adminToken };
}

function showPage(pageId) {
    document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
    const page = document.getElementById(pageId);
    if (page) page.classList.add('active');
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// ---------- Auth ----------
function login() {
    const token = document.getElementById('adminToken').value;
    if (!token) {
        document.getElementById('authError').textContent = 'Token required';
        return;
    }
    adminToken = token;
    document.getElementById('authError').textContent = '';
    fetch(API_BASE + '/admin/api/tenants', { headers: getHeaders() })
        .then(async res => {
            if (res.ok) {
                document.getElementById('authSection').style.display = 'none';
                loadTenants();
            } else {
                document.getElementById('authError').textContent = 'Login failed: ' + res.status;
            }
        })
        .catch(err => {
            document.getElementById('authError').textContent = 'Login failed: ' + err.message;
        });
}

// ---------- Businesses list ----------
async function loadTenants() {
    try {
        const res = await fetch(API_BASE + '/admin/api/tenants', { headers: getHeaders() });
        if (!res.ok) throw new Error('HTTP ' + res.status);
        const data = await res.json();
        const container = document.getElementById('businessCards');
        container.innerHTML = '';
        (data.tenants || []).forEach(t => {
            const card = document.createElement('div');
            card.className = 'business-card';
            const typeLabel = (t.business_type || '—') + '';
            const statusClass = t.active ? 'active' : '';
            const ownerLine = t.owner_email ? ('Owner: ' + escapeHtml(t.owner_email)) : 'No owner account';
            card.innerHTML = `
                <div>
                    <div class="card-name">${escapeHtml(t.name || t.id)}</div>
                    <div class="card-meta">
                        <span class="type business-type-badge">${escapeHtml(typeLabel)}</span>
                        <span>${t.live_faq_count} FAQs</span>
                        <span>${t.queries_this_week} questions this week</span>
                        <span class="dot ${statusClass}" title="${t.active ? 'Active' : 'Inactive'}"></span>
                    </div>
                    <div class="card-owner">${ownerLine}</div>
                </div>
                <div class="card-actions">
                    <button type="button" class="btn-secondary viewTenantButton" data-tenant-id="${escapeHtml(t.id)}">View</button>
                    <button type="button" class="btn-secondary editFaqsButton" data-tenant-id="${escapeHtml(t.id)}">Edit FAQs</button>
                    <button type="button" class="btn-danger deleteTenantButton" data-tenant-id="${escapeHtml(t.id)}">Delete</button>
                </div>
            `;
            container.appendChild(card);
        });
        showPage('tenantsPage');
    } catch (e) {
        document.getElementById('authError').textContent = e.message;
        document.getElementById('authSection').style.display = 'block';
    }
}

async function deleteTenant(tenantId) {
    if (!confirm('Delete this business and all its data? This cannot be undone.')) return;
    try {
        const res = await fetch(API_BASE + '/admin/api/tenant/' + encodeURIComponent(tenantId), {
            method: 'DELETE',
            headers: getHeaders()
        });
        if (!res.ok) throw new Error('HTTP ' + res.status);
        loadTenants();
    } catch (e) {
        alert('Error: ' + e.message);
    }
}

// ---------- Tenant detail (View / Edit FAQs) ----------
async function showTenantDetail(tenantId) {
    try {
        const [tenantRes, statsRes, ownerRes, suggestionsRes, faqDumpRes, queriesRes] = await Promise.all([
            fetch(API_BASE + '/admin/api/tenant/' + encodeURIComponent(tenantId), { headers: getHeaders() }),
            fetch(API_BASE + '/admin/api/tenant/' + encodeURIComponent(tenantId) + '/stats', { headers: getHeaders() }).catch(() => null),
            fetch(API_BASE + '/admin/api/tenant/' + encodeURIComponent(tenantId) + '/owner', { headers: getHeaders() }).catch(() => null),
            fetch(API_BASE + '/admin/api/tenant/' + encodeURIComponent(tenantId) + '/suggestions', { headers: getHeaders() }).catch(() => null),
            fetch(API_BASE + '/admin/api/tenant/' + encodeURIComponent(tenantId) + '/faq-dump', { headers: getHeaders() }).catch(() => null),
            fetch(API_BASE + '/admin/api/tenant/' + encodeURIComponent(tenantId) + '/queries?days=7&limit=50', { headers: getHeaders() }).catch(() => null)
        ]);
        if (!tenantRes.ok) throw new Error('HTTP ' + tenantRes.status);
        const tenant = await tenantRes.json();
        const stats = statsRes && statsRes.ok ? await statsRes.json() : null;
        let owner = null;
        if (ownerRes && ownerRes.ok) try { owner = await ownerRes.json(); } catch (_) {}
        let suggestions = [];
        if (suggestionsRes && suggestionsRes.ok) try { const d = await suggestionsRes.json(); suggestions = d.suggestions || []; } catch (_) {}
        let liveFaqs = [];
        if (faqDumpRes && faqDumpRes.ok) try { const d = await faqDumpRes.json(); liveFaqs = d.faqs || []; } catch (_) {}
        let recentQueries = [];
        if (queriesRes && queriesRes.ok) try { const d = await queriesRes.json(); recentQueries = d.queries || []; } catch (_) {}
        const pendingSuggestions = suggestions.filter(s => (s.status || '').toLowerCase() === 'pending');
        const lastLoginStr = owner && owner.last_login ? new Date(owner.last_login).toLocaleString() : 'Never';
        const ownerSectionHtml = owner
            ? `<div class="section owner-section">
                <h2>Owner Account</h2>
                <p><strong>Email:</strong> ${escapeHtml(owner.email)}</p>
                <p><strong>Name:</strong> ${escapeHtml(owner.display_name || '—')}</p>
                <p><strong>Last login:</strong> ${escapeHtml(lastLoginStr)}</p>
                <div style="display:flex;gap:10px;flex-wrap:wrap;margin-top:12px;">
                    <button type="button" class="btn-primary" id="resetOwnerPasswordButton" data-tenant-id="${escapeHtml(tenant.id)}">Reset Password</button>
                    <button type="button" class="btn-danger" id="deleteOwnerButton" data-tenant-id="${escapeHtml(tenant.id)}">Delete Owner</button>
                </div>
                <div id="ownerNewPasswordBox" class="new-password-box" style="display:none;"></div>
            </div>`
            : `<div class="section owner-section">
                <h2>Owner Account</h2>
                <p style="color:#6b7280;margin-bottom:12px;">No owner account set up yet.</p>
                <button type="button" class="btn-primary" id="createOwnerAccountButton" data-tenant-id="${escapeHtml(tenant.id)}">Create Owner Account</button>
                <div id="createOwnerForm" style="display:none;margin-top:16px;">
                    <div class="form-group"><label>Email</label><input type="email" id="createOwnerEmail" placeholder="owner@example.com" /></div>
                    <div class="form-group"><label>Temp password</label><input type="password" id="createOwnerPassword" placeholder="temp123" autocomplete="new-password" /></div>
                    <div class="form-group"><label>Display name (optional)</label><input type="text" id="createOwnerDisplayName" placeholder="Mike" /></div>
                    <button type="button" class="btn-primary" id="createOwnerButton" data-tenant-id="${escapeHtml(tenant.id)}">Create owner</button>
                </div>
                <div id="createOwnerError" class="error"></div>
                <div id="createOwnerSuccess" class="success"></div>
                <div id="ownerNewPasswordBox" class="new-password-box" style="display:none;"></div>
            </div>`;
        const detailDiv = document.getElementById('tenantDetail');
        detailDiv.setAttribute('data-tenant-id', tenant.id);
        detailDiv.setAttribute('data-tenant-name', tenant.name || tenant.id);
        detailDiv.setAttribute('data-tenant-phone', tenant.contact_phone || '');
        detailDiv.innerHTML = `
            <h1>${escapeHtml(tenant.name || tenant.id)}</h1>
            <p style="color:#6b7280;margin-bottom:20px;">ID: ${escapeHtml(tenant.id)}</p>
            <div class="section">
                <h2>Domains</h2>
                <div class="form-group" style="display:flex;gap:10px;">
                    <input type="text" id="newDomain" placeholder="example.com" style="flex:1;" />
                    <button type="button" class="btn-primary" id="addDomainButton" data-tenant-id="${escapeHtml(tenant.id)}">Add Domain</button>
                </div>
                <ul class="domains-list" id="domainsList">
                    ${(tenant.domains || []).map(d => '<li><span>' + escapeHtml(d.domain) + ' ' + (d.enabled ? '✓' : '') + '</span><button type="button" class="btn-danger removeDomainButton" data-tenant-id="' + escapeHtml(tenant.id) + '" data-domain="' + escapeHtml(d.domain) + '">Remove</button></li>').join('')}
                </ul>
            </div>
            <div class="section">
                <h2>FAQs</h2>
                <p style="color:#6b7280;margin-bottom:12px;">Live: ${tenant.live_faq_count || 0} | Staged: ${tenant.staged_faq_count || 0}</p>
                <div class="form-group">
                    <label>Upload staged FAQs (JSON)</label>
                    <textarea id="stagedFaqsJson" rows="6" placeholder='[{"question":"Q1","answer":"A1"}]'></textarea>
                </div>
                <div style="display:flex;gap:10px;flex-wrap:wrap;">
                    <button type="button" class="btn-primary" id="uploadStagedFaqsButton" data-tenant-id="${escapeHtml(tenant.id)}">Upload Staged</button>
                    <button type="button" class="btn-primary" id="promoteStagedButton" data-tenant-id="${escapeHtml(tenant.id)}" ${(tenant.staged_faq_count || 0) === 0 ? 'disabled' : ''}>Go Live</button>
                    <button type="button" class="btn-secondary" id="rollbackTenantButton" data-tenant-id="${escapeHtml(tenant.id)}" ${(tenant.last_good_count || 0) === 0 ? 'disabled' : ''}>Rollback</button>
                </div>
                <div id="faqsError" class="error"></div>
                <div id="faqsSuccess" class="success"></div>
            </div>
            <div class="section">
                <h2>Live FAQs (${liveFaqs.length})</h2>
                ${liveFaqs.length === 0 ? '<p style="color:#6b7280;">No live FAQs yet. Upload staged and click Go Live.</p>' : liveFaqs.map(f => `
                <div class="faq-card" style="border:1px solid #e5e7eb;border-radius:8px;padding:14px 16px;margin-bottom:12px;background:#fff;">
                    <div class="faq-question" style="font-weight:600;color:#111827;margin-bottom:6px;">${escapeHtml(f.question)}</div>
                    <div class="faq-answer" style="font-size:14px;color:#6b7280;line-height:1.5;border-left:3px solid #e5e7eb;padding-left:12px;">${escapeHtml(typeof f.answer === 'string' ? f.answer : (f.answer || ''))}</div>
                </div>`).join('')}
            </div>
            <div class="section">
                <h2>Recent Customer Questions (last 7 days)</h2>
                ${recentQueries.length === 0 ? '<p style="color:#6b7280;">No customer questions yet. Queries will appear here once the widget is in use.</p>' : recentQueries.map(q => {
                    const borderColor = q.answered ? '#10b981' : '#f59e0b';
                    const status = q.answered ? '✅' : '❌';
                    const answerText = (q.answer || '').trim() || '—';
                    const answerShort = answerText.length > 120 ? answerText.slice(0, 120) + '…' : answerText;
                    const timeStr = q.timestamp ? new Date(q.timestamp).toLocaleString() : '';
                    return `
                <div class="query-card" style="border:1px solid #e5e7eb;border-left:4px solid ${borderColor};border-radius:8px;padding:14px 16px;margin-bottom:12px;background:#fff;">
                    <div style="font-weight:600;color:#111827;margin-bottom:6px;">"${escapeHtml(q.question)}"</div>
                    <div style="font-size:14px;color:#6b7280;margin-bottom:6px;">Answer: ${escapeHtml(answerShort)}</div>
                    <div style="font-size:13px;color:#6b7280;">→ ${q.matched_to ? 'Matched: ' + escapeHtml(q.matched_to) : 'No match'} ${status} · ${escapeHtml(timeStr)}</div>
                </div>`;
                }).join('')}
            </div>
            <div class="section">
                <h2>Generate FAQs from website</h2>
                <p style="color:#6b7280;margin-bottom:12px;font-size:14px;">Paste their website URL to suggest FAQs. Review and add to staged below.</p>
                <div class="form-group" style="display:flex;gap:10px;flex-wrap:wrap;align-items:center;">
                    <input type="url" id="tenantWebsiteUrl" placeholder="https://www.example.com.au" style="flex:1;min-width:200px;max-width:400px;" />
                    <button type="button" class="btn-primary" id="generateFaqsFromUrlButton" data-tenant-id="${escapeHtml(tenant.id)}">Generate</button>
                </div>
                <div id="generateFaqsError" class="error" style="margin-top:8px;"></div>
                <div id="generateFaqsResult" style="display:none;margin-top:16px;">
                    <p style="font-weight:500;margin-bottom:10px;">Generated FAQs — edit if needed, then add to staged:</p>
                    <ul id="generatedFaqsList" class="faq-list" style="margin-bottom:12px;"></ul>
                    <button type="button" class="btn-primary" id="addGeneratedToStagedButton">Add these to staged FAQs</button>
                </div>
            </div>
            <div class="section">
                <h2>Stats (last 24 hours)</h2>
                ${stats ? '<div class="stats-grid"><div class="stat-card"><div class="label">Questions answered</div><div class="value">' + stats.total_queries + '</div></div><div class="stat-card"><div class="label">FAQ match rate</div><div class="value">' + ((stats.faq_hit_rate || 0) * 100).toFixed(1) + '%</div></div><div class="stat-card"><div class="label">Avg latency</div><div class="value">' + (stats.avg_latency_ms || 0) + 'ms</div></div></div>' : '<p style="color:#6b7280;">No stats yet</p>'}
            </div>
            ${ownerSectionHtml}
            <div class="section" id="suggestionsSection">
                <h2>FAQ Suggestions (${pendingSuggestions.length} pending)</h2>
                ${pendingSuggestions.length === 0 ? '<p style="color:#6b7280;">No pending suggestions.</p>' : pendingSuggestions.map(s => `
                <div class="suggestion-card" data-suggestion-id="${s.id}" style="background:#f9fafb;border:1px solid #e5e7eb;border-radius:8px;padding:14px 16px;margin-bottom:12px;">
                    <div class="suggestion-q" style="font-weight:500;color:#111827;margin-bottom:6px;">"${escapeHtml(s.question)}"</div>
                    ${s.answer ? '<div class="suggestion-a" style="font-size:14px;color:#6b7280;margin-bottom:10px;">Owner\'s answer: ' + escapeHtml(s.answer) + '</div>' : ''}
                    <div style="display:flex;gap:10px;flex-wrap:wrap;">
                        <button type="button" class="btn-primary approveSuggestionButton" data-tenant-id="${escapeHtml(tenant.id)}" data-suggestion-id="${s.id}">Approve & Add as FAQ</button>
                        <button type="button" class="btn-danger rejectSuggestionButton" data-tenant-id="${escapeHtml(tenant.id)}" data-suggestion-id="${s.id}">Reject</button>
                    </div>
                </div>
                `).join('')}
            </div>
            <div class="section">
                <h2>Widget install — choose a style</h2>
                <div class="form-group">
                    <label>Contact phone (for fallback message)</label>
                    <input type="text" id="installContactPhone" placeholder="0412 345 678" value="${escapeHtml(tenant.contact_phone || '')}" />
                </div>
                <div style="margin-top:16px;">
                    <p style="font-weight:600;color:#111827;margin-bottom:8px;">📌 Floating button (recommended for most sites)</p>
                    <p style="font-size:14px;color:#6b7280;margin-bottom:8px;">Shows a "Got a question?" button in the corner of every page.</p>
                    <code id="installSnippet" style="display:block;background:#f9fafb;padding:12px;border-radius:8px;font-size:13px;white-space:pre-wrap;word-break:break-all;"></code>
                    <button type="button" class="btn-primary copyInstallBtn" data-target="installSnippet" style="margin-top:8px;">Copy</button>
                </div>
                <div style="margin-top:24px;">
                    <p style="font-weight:600;color:#111827;margin-bottom:8px;">📋 Inline embed (recommended for landing pages)</p>
                    <p style="font-size:14px;color:#6b7280;margin-bottom:8px;">Embeds the Q&amp;A directly into your page where you place it.</p>
                    <code id="installSnippetInline" style="display:block;background:#f9fafb;padding:12px;border-radius:8px;font-size:13px;white-space:pre-wrap;word-break:break-all;"></code>
                    <button type="button" class="btn-primary copyInstallBtn" data-target="installSnippetInline" style="margin-top:8px;">Copy</button>
                </div>
                <p style="color:#6b7280;margin-top:12px;font-size:14px;">Paste the code before <code>&lt;/body&gt;</code> (inline: put the div where you want the widget).</p>
            </div>
        `;
        updateInstallSnippet();
        ['installContactPhone'].forEach(id => {
            const el = document.getElementById(id);
            if (el) el.addEventListener('input', updateInstallSnippet);
        });
        showPage('tenantDetailPage');
    } catch (e) {
        alert('Error: ' + e.message);
    }
}

function updateInstallSnippet() {
    const apiBase = API_BASE;
    const detail = document.getElementById('tenantDetail');
    const name = (detail && detail.getAttribute('data-tenant-name')) || '';
    const tenantId = (detail && detail.getAttribute('data-tenant-id')) || '';
    const phoneEl = document.getElementById('installContactPhone');
    const phone = (phoneEl && phoneEl.value.trim()) || (detail && detail.getAttribute('data-tenant-phone')) || '';
    const floatSnippet = '<!-- MotionMade AI - Instant Answers for ' + escapeHtml(name) + ' -->\n<script src="' + escapeHtml(apiBase) + '/widget.js"\n  data-tenant="' + escapeHtml(tenantId) + '"\n  data-name="' + escapeHtml(name) + '"\n  data-phone="' + escapeHtml(phone) + '"\n  data-color="#2563EB"\n  data-mode="float"\n  data-api="' + escapeHtml(apiBase) + '"><\/script>';
    const inlineSnippet = '<!-- MotionMade AI - Inline widget for ' + escapeHtml(name) + ' -->\n<div id="motionmade-widget"><\/div>\n<script src="' + escapeHtml(apiBase) + '/widget.js"\n  data-tenant="' + escapeHtml(tenantId) + '"\n  data-name="' + escapeHtml(name) + '"\n  data-phone="' + escapeHtml(phone) + '"\n  data-color="#2563EB"\n  data-mode="inline"\n  data-api="' + escapeHtml(apiBase) + '"><\/script>';
    const elFloat = document.getElementById('installSnippet');
    const elInline = document.getElementById('installSnippetInline');
    if (elFloat) elFloat.textContent = floatSnippet;
    if (elInline) elInline.textContent = inlineSnippet;
}

async function addDomain(tenantId) {
    const domain = document.getElementById('newDomain').value.trim();
    if (!domain) { alert('Domain required'); return; }
    try {
        const res = await fetch(API_BASE + '/admin/api/tenant/' + encodeURIComponent(tenantId) + '/domains', {
            method: 'POST', headers: getHeaders(), body: JSON.stringify({ domain })
        });
        if (!res.ok) throw new Error('HTTP ' + res.status);
        showTenantDetail(tenantId);
    } catch (e) { alert('Error: ' + e.message); }
}

async function removeDomain(tenantId, domain) {
    if (!confirm('Remove domain ' + domain + '?')) return;
    try {
        const res = await fetch(API_BASE + '/admin/api/tenant/' + encodeURIComponent(tenantId) + '/domains/' + encodeURIComponent(domain), {
            method: 'DELETE', headers: getHeaders()
        });
        if (!res.ok) throw new Error('HTTP ' + res.status);
        showTenantDetail(tenantId);
    } catch (e) { alert('Error: ' + e.message); }
}

async function createOwner(tenantId) {
    const errEl = document.getElementById('createOwnerError');
    const okEl = document.getElementById('createOwnerSuccess');
    if (errEl) errEl.textContent = '';
    if (okEl) okEl.textContent = '';
    const email = document.getElementById('createOwnerEmail')?.value?.trim();
    const password = document.getElementById('createOwnerPassword')?.value;
    const displayName = document.getElementById('createOwnerDisplayName')?.value?.trim();
    if (!email) { if (errEl) errEl.textContent = 'Email required'; return; }
    if (!password) { if (errEl) errEl.textContent = 'Temp password required'; return; }
    try {
        const res = await fetch(API_BASE + '/admin/api/create-owner', {
            method: 'POST', headers: getHeaders(),
            body: JSON.stringify({ tenant_id: tenantId, email, password, display_name: displayName || null })
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) { if (errEl) errEl.textContent = data.detail || 'HTTP ' + res.status; return; }
        if (okEl) okEl.textContent = 'Owner created. They can log in at /dashboard/login.';
        showTenantDetail(tenantId);
    } catch (e) { if (errEl) errEl.textContent = e.message; }
}

async function resetOwnerPassword(tenantId) {
    const box = document.getElementById('ownerNewPasswordBox');
    if (box) { box.style.display = 'none'; box.textContent = ''; }
    try {
        const res = await fetch(API_BASE + '/admin/api/tenant/' + encodeURIComponent(tenantId) + '/owner/reset-password', { method: 'POST', headers: getHeaders() });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) { alert(data.detail || 'HTTP ' + res.status); return; }
        if (box) {
            box.textContent = 'New password: ' + (data.new_password || '') + ' — share this with the owner';
            box.style.display = 'block';
        }
    } catch (e) { alert(e.message); }
}

async function deleteOwner(tenantId) {
    if (!confirm('Delete this owner account? They will no longer be able to log in to the dashboard.')) return;
    try {
        const res = await fetch(API_BASE + '/admin/api/tenant/' + encodeURIComponent(tenantId) + '/owner', { method: 'DELETE', headers: getHeaders() });
        if (!res.ok) { const data = await res.json().catch(() => ({})); throw new Error(data.detail || 'HTTP ' + res.status); }
        showTenantDetail(tenantId);
    } catch (e) { alert(e.message); }
}

async function approveSuggestion(tenantId, suggestionId) {
    try {
        const res = await fetch(API_BASE + '/admin/api/tenant/' + encodeURIComponent(tenantId) + '/suggestions/' + encodeURIComponent(suggestionId) + '/approve', {
            method: 'POST', headers: getHeaders(), body: JSON.stringify({})
        });
        if (!res.ok) { const data = await res.json().catch(() => ({})); throw new Error(data.detail || 'HTTP ' + res.status); }
        alert('Suggestion approved. FAQ added and promoted to live.');
        showTenantDetail(tenantId);
    } catch (e) { alert(e.message); }
}

async function rejectSuggestion(tenantId, suggestionId) {
    const note = window.prompt('Rejection note (optional, owner will see this):', '');
    if (note === null) return;
    try {
        const res = await fetch(API_BASE + '/admin/api/tenant/' + encodeURIComponent(tenantId) + '/suggestions/' + encodeURIComponent(suggestionId) + '/reject', {
            method: 'POST', headers: getHeaders(), body: JSON.stringify({ note: note })
        });
        if (!res.ok) { const data = await res.json().catch(() => ({})); throw new Error(data.detail || 'HTTP ' + res.status); }
        showTenantDetail(tenantId);
    } catch (e) { alert(e.message); }
}

async function uploadStagedFaqs(tenantId) {
    const jsonText = document.getElementById('stagedFaqsJson').value.trim();
    if (!jsonText) { document.getElementById('faqsError').textContent = 'FAQ JSON required'; return; }
    let items;
    try { items = JSON.parse(jsonText); } catch (e) { document.getElementById('faqsError').textContent = 'Invalid JSON'; return; }
    try {
        const res = await fetch(API_BASE + '/admin/api/tenant/' + encodeURIComponent(tenantId) + '/faqs/staged', {
            method: 'PUT', headers: getHeaders(), body: JSON.stringify(items)
        });
        if (!res.ok) { const err = await res.json(); throw new Error(err.detail || 'HTTP ' + res.status); }
        document.getElementById('faqsError').textContent = '';
        document.getElementById('faqsSuccess').textContent = 'Staged successfully.';
        setTimeout(() => showTenantDetail(tenantId), 1000);
    } catch (e) {
        document.getElementById('faqsError').textContent = e.message;
        document.getElementById('faqsSuccess').textContent = '';
    }
}

async function generateFaqsFromUrl(tenantId, url, businessName) {
    const errEl = document.getElementById('generateFaqsError');
    const resultEl = document.getElementById('generateFaqsResult');
    const listEl = document.getElementById('generatedFaqsList');
    const btn = document.getElementById('generateFaqsFromUrlButton');
    errEl.textContent = '';
    resultEl.style.display = 'none';
    btn.disabled = true;
    btn.textContent = 'Generating...';
    try {
        const res = await fetch(API_BASE + '/admin/api/generate-faqs-from-url', {
            method: 'POST', headers: getHeaders(),
            body: JSON.stringify({ url: url, business_type: 'other', business_name: businessName || '' })
        });
        const data = await res.json().catch(() => ({}));
        if (data.error) throw new Error(data.error);
        const suggested = data.suggested_faqs || [];
        generatedFaqsFromUrl = suggested.map(f => ({ question: f.question || '', answer: f.answer || '' }));
        listEl.innerHTML = generatedFaqsFromUrl.map((faq, i) => {
        const q = (faq.question || '').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
        const a = escapeHtml(faq.answer || '');
        return `<li style="margin-bottom:12px;padding:10px;background:#f9fafb;border-radius:6px;">
                <input type="text" class="generated-faq-q" data-i="${i}" value="${q}" placeholder="Question" style="width:100%;margin-bottom:6px;padding:6px 10px;" />
                <textarea class="generated-faq-a" data-i="${i}" rows="2" placeholder="Answer" style="width:100%;padding:6px 10px;resize:vertical;">${a}</textarea>
            </li>`;
    }).join('');
        resultEl.style.display = 'block';
    } catch (e) {
        errEl.textContent = e.message;
    }
    btn.disabled = false;
    btn.textContent = 'Generate';
}

function addGeneratedToStaged() {
    const listEl = document.getElementById('generatedFaqsList');
    if (!listEl) return;
    const items = [];
    listEl.querySelectorAll('li').forEach((li, i) => {
        const q = (li.querySelector('.generated-faq-q') || {}).value || '';
        const a = (li.querySelector('.generated-faq-a') || {}).value || '';
        if (q.trim()) items.push({ question: q.trim(), answer: a.trim() });
    });
    const textarea = document.getElementById('stagedFaqsJson');
    if (!textarea) return;
    let existing = [];
    try {
        const t = textarea.value.trim();
        if (t) existing = JSON.parse(t);
    } catch (e) {}
    const combined = Array.isArray(existing) ? existing.concat(items) : items;
    textarea.value = JSON.stringify(combined, null, 2);
    document.getElementById('faqsSuccess').textContent = 'Added ' + items.length + ' FAQs to the list above. Click "Upload Staged" to save.';
    document.getElementById('faqsError').textContent = '';
}

async function promoteStaged(tenantId) {
    document.getElementById('faqsError').textContent = '';
    document.getElementById('faqsSuccess').textContent = 'Going live...';
    try {
        const res = await fetch(API_BASE + '/admin/api/tenant/' + encodeURIComponent(tenantId) + '/promote', { method: 'POST', headers: getHeaders() });
        const data = await res.json();
        if (data.status === 'success') {
            document.getElementById('faqsSuccess').textContent = data.message || 'Live!';
        } else {
            document.getElementById('faqsError').textContent = data.message || 'Failed';
        }
        setTimeout(() => showTenantDetail(tenantId), 1500);
    } catch (e) {
        document.getElementById('faqsError').textContent = e.message;
        document.getElementById('faqsSuccess').textContent = '';
    }
}

async function rollbackTenant(tenantId) {
    if (!confirm('Rollback to last good FAQs?')) return;
    document.getElementById('faqsError').textContent = '';
    document.getElementById('faqsSuccess').textContent = 'Rolling back...';
    try {
        const res = await fetch(API_BASE + '/admin/api/tenant/' + encodeURIComponent(tenantId) + '/rollback', { method: 'POST', headers: getHeaders() });
        const data = await res.json();
        document.getElementById('faqsSuccess').textContent = data.status === 'success' ? data.message : '';
        document.getElementById('faqsError').textContent = data.status !== 'success' ? (data.message || 'Error') : '';
        setTimeout(() => showTenantDetail(tenantId), 1000);
    } catch (e) {
        document.getElementById('faqsError').textContent = e.message;
    }
}

function copyInstallSnippetTarget(targetId) {
    const el = document.getElementById(targetId);
    if (!el) return;
    const btn = document.querySelector('.copyInstallBtn[data-target="' + targetId + '"]');
    try {
        navigator.clipboard.writeText(el.textContent).then(function () {
            if (btn) { btn.textContent = 'Copied! ✓'; setTimeout(function () { btn.textContent = 'Copy'; }, 2000); }
        });
    } catch (e) {
        const ta = document.createElement('textarea');
        ta.value = el.textContent;
        ta.style.position = 'fixed';
        ta.style.opacity = '0';
        document.body.appendChild(ta);
        ta.select();
        document.execCommand('copy');
        document.body.removeChild(ta);
        if (btn) { btn.textContent = 'Copied! ✓'; setTimeout(function () { btn.textContent = 'Copy'; }, 2000); }
    }
}

// ---------- Onboarding wizard ----------
let wizardTenantId = '';
let wizardBusinessName = '';
let wizardContactPhone = '';
let wizardFaqs = [];
let wizardTempPassword = '';
let wizardSuggestedQuestions = [];
let wizardTemplateType = ''; // 'cleaner' | 'plumber' | 'electrician' when showing template step
let wizardTemplateVars = {};

function slugFromName(name) {
    return (name || '')
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, '_')
        .replace(/^_|_$/g, '') || 'business';
}

function randomTempPassword() {
    const chars = 'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghjkmnpqrstuvwxyz23456789';
    let s = 'Temp_';
    for (let i = 0; i < 6; i++) s += chars[Math.floor(Math.random() * chars.length)];
    return s;
}

function updateWizardWidgetIdPreview() {
    const name = document.getElementById('wizBusinessName')?.value?.trim() || '';
    const el = document.getElementById('wizWidgetIdPreview');
    if (el) el.textContent = name ? ('Your widget ID: ' + slugFromName(name)) : '';
}

function showWizard() {
    wizardTenantId = '';
    wizardBusinessName = '';
    wizardFaqs = [];
    wizardTempPassword = '';
    wizardTemplateType = '';
    wizardTemplateVars = {};
    document.getElementById('wizBusinessName').value = '';
    document.getElementById('wizBusinessType').value = 'Plumber';
    document.getElementById('wizWebsiteUrl').value = '';
    document.getElementById('wizOwnerName').value = '';
    document.getElementById('wizOwnerEmail').value = '';
    updateWizardWidgetIdPreview();
    document.getElementById('wizOwnerPhone').value = '';
    document.getElementById('wizFaqQuestion').value = '';
    document.getElementById('wizFaqAnswer').value = '';
    document.getElementById('wizTempPasswordBox').style.display = 'none';
    document.getElementById('wizStep1Error').textContent = '';
    document.getElementById('wizFaqList').innerHTML = '';
    document.getElementById('wizMinFaqMsg').textContent = '';
    document.getElementById('wizGoLiveProgress').style.display = 'none';
    document.getElementById('wizStep2Error').textContent = '';
    document.getElementById('wizPreviewBody').innerHTML = '';
    wizardSuggestedQuestions = [];
    const wizIntro = document.getElementById('wizStep2Intro');
    const wizNote = document.getElementById('wizWebsiteFaqsNote');
    if (wizIntro) wizIntro.style.display = '';
    if (wizNote) wizNote.style.display = 'none';
    document.querySelectorAll('.wizard-step').forEach(s => s.classList.remove('active'));
    document.getElementById('wizardStep1').classList.add('active');
    showPage('wizardPage');
}

function wizardStep1Next() {
    const name = document.getElementById('wizBusinessName').value.trim();
    const type = document.getElementById('wizBusinessType').value;
    const websiteUrl = document.getElementById('wizWebsiteUrl').value.trim();
    const ownerName = document.getElementById('wizOwnerName').value.trim();
    const ownerEmail = document.getElementById('wizOwnerEmail').value.trim().toLowerCase();
    const ownerPhone = document.getElementById('wizOwnerPhone').value.trim();
    const errEl = document.getElementById('wizStep1Error');
    const boxEl = document.getElementById('wizTempPasswordBox');
    const nextBtn = document.getElementById('wizStep1Next');
    errEl.textContent = '';
    boxEl.style.display = 'none';
    if (!name) { errEl.textContent = 'Business name required'; return; }
    if (!ownerEmail) { errEl.textContent = 'Owner email required'; return; }
    const tenantId = slugFromName(name);
    const tempPass = randomTempPassword();
    (async () => {
        try {
            const createRes = await fetch(API_BASE + '/admin/api/tenants', {
                method: 'POST', headers: getHeaders(),
                body: JSON.stringify({ id: tenantId, name: name, business_type: type, contact_phone: ownerPhone || null })
            });
            if (!createRes.ok) {
                const d = await createRes.json().catch(() => ({}));
                throw new Error(d.detail || 'HTTP ' + createRes.status);
            }
            const ownerRes = await fetch(API_BASE + '/admin/api/create-owner', {
                method: 'POST', headers: getHeaders(),
                body: JSON.stringify({
                    tenant_id: tenantId,
                    email: ownerEmail,
                    password: tempPass,
                    display_name: ownerName || null
                })
            });
            if (!ownerRes.ok) {
                const d = await ownerRes.json().catch(() => ({}));
                if (ownerRes.status !== 400 || !(d.detail && d.detail.includes('already'))) throw new Error(d.detail || 'HTTP ' + ownerRes.status);
            }
            wizardTenantId = tenantId;
            wizardBusinessName = name;
            wizardContactPhone = ownerPhone || '';
            wizardTempPassword = tempPass;
            boxEl.innerHTML = '<strong>Owner login (save this)</strong><br>Email: ' + escapeHtml(ownerEmail) + '<br>Password: ' + escapeHtml(tempPass);
            boxEl.style.display = 'block';
            const bizType = document.getElementById('wizBusinessType').value;
            const typeKey = bizType.toLowerCase();

            if (websiteUrl && (typeKey === 'cleaner' || typeKey === 'plumber' || typeKey === 'electrician' || typeKey === 'other')) {
                nextBtn.disabled = true;
                nextBtn.textContent = 'Reading website and generating FAQs...';
                try {
                    const faqRes = await fetch(API_BASE + '/admin/api/generate-faqs-from-url', {
                        method: 'POST', headers: getHeaders(),
                        body: JSON.stringify({ url: websiteUrl, business_type: typeKey, business_name: name })
                    });
                    const faqData = await faqRes.json().catch(() => ({}));
                    if (faqData.error) throw new Error(faqData.error);
                    const suggested = faqData.suggested_faqs || [];
                    if (suggested.length > 0) {
                        wizardFaqs = suggested.map(f => ({ question: f.question || '', answer: f.answer || '' }));
                        document.querySelectorAll('.wizard-step').forEach(s => s.classList.remove('active'));
                        document.getElementById('wizardStep2').classList.add('active');
                        document.getElementById('wizStep2Intro').style.display = 'none';
                        const noteEl = document.getElementById('wizWebsiteFaqsNote');
                        const noteText = document.getElementById('wizWebsiteFaqsNoteText');
                        if (typeKey === 'cleaner' || typeKey === 'plumber' || typeKey === 'electrician') {
                            wizardTemplateType = typeKey;
                            noteEl.style.display = 'block';
                            noteText.textContent = 'These FAQs were generated from the website. You can also load the ' + (typeKey.charAt(0).toUpperCase() + typeKey.slice(1)) + ' template instead.';
                            document.getElementById('wizLoadTemplateInsteadBtn').style.display = 'inline-block';
                        } else {
                            noteEl.style.display = 'none';
                        }
                        document.getElementById('wizSaveAndGoLive').disabled = wizardFaqs.length < 5;
                        renderWizardFaqList();
                        nextBtn.disabled = false;
                        nextBtn.textContent = 'Next →';
                        return;
                    }
                } catch (e) {
                    errEl.textContent = e.message || 'Website scrape failed. Continuing with template or blank.';
                }
                nextBtn.disabled = false;
                nextBtn.textContent = 'Next →';
            }

            if (typeKey === 'cleaner' || typeKey === 'plumber' || typeKey === 'electrician') {
                wizardTemplateType = typeKey;
                document.querySelectorAll('.wizard-step').forEach(s => s.classList.remove('active'));
                document.getElementById('wizardStep1b').classList.add('active');
                document.getElementById('wizStep2Intro').style.display = '';
                document.getElementById('wizWebsiteFaqsNote').style.display = 'none';
                loadWizardTemplateStep();
            } else {
                wizardFaqs = [];
                document.querySelectorAll('.wizard-step').forEach(s => s.classList.remove('active'));
                document.getElementById('wizardStep2').classList.add('active');
                document.getElementById('wizStep2Intro').style.display = '';
                document.getElementById('wizWebsiteFaqsNote').style.display = 'none';
                document.getElementById('wizSaveAndGoLive').disabled = wizardFaqs.length < 5;
                renderWizardFaqList();
            }
        } catch (e) {
            errEl.textContent = e.message;
            nextBtn.disabled = false;
            nextBtn.textContent = 'Next →';
        }
    })();
}

async function loadWizardTemplateStep() {
    const intro = document.getElementById('wizTemplateIntro');
    const form = document.getElementById('wizTemplateVarForm');
    if (!form) return;
    intro.textContent = 'Loading template...';
    form.innerHTML = '';
    try {
        const r = await fetch(API_BASE + '/admin/api/faq-templates/' + encodeURIComponent(wizardTemplateType), { headers: getHeaders() });
        if (!r.ok) throw new Error('Template not found');
        const data = await r.json();
        wizardTemplateVars = data.variables || {};
        const displayName = data.display_name || wizardTemplateType;
        intro.textContent = 'We have a template for ' + displayName.toLowerCase() + '! Pre-filled with common questions. Just fill in your details:';
        form.innerHTML = Object.keys(wizardTemplateVars).map(k => {
            const val = wizardTemplateVars[k] || '';
            const label = k.replace(/_/g, ' ');
            return '<div class="form-group" style="margin-bottom:12px;"><label style="display:block;margin-bottom:4px;font-size:14px;">' + escapeHtml(label) + '</label><input type="text" class="wiz-template-var" data-var="' + escapeHtml(k) + '" value="' + escapeHtml(val) + '" style="width:100%;max-width:320px;padding:8px 12px;border:1px solid #d1d5db;border-radius:6px;" /></div>';
        }).join('');
    } catch (e) {
        intro.textContent = 'Could not load template. Click "Write my own FAQs" to continue.';
    }
}

function wizardUseTemplate() {
    const vars = {};
    document.querySelectorAll('.wiz-template-var').forEach(input => {
        const k = input.getAttribute('data-var');
        if (k) vars[k] = input.value.trim() || wizardTemplateVars[k] || '';
    });
    const params = new URLSearchParams(vars).toString();
    fetch(API_BASE + '/admin/api/faq-templates/' + encodeURIComponent(wizardTemplateType) + (params ? '?' + params : ''), { headers: getHeaders() })
        .then(r => r.ok ? r.json() : Promise.reject(new Error('Failed to load template')))
        .then(data => {
            wizardFaqs = (data.faqs || []).map(f => ({ question: f.question, answer: f.answer }));
            document.querySelectorAll('.wizard-step').forEach(s => s.classList.remove('active'));
            document.getElementById('wizardStep2').classList.add('active');
            document.getElementById('wizWebsiteFaqsNote').style.display = 'none';
            document.getElementById('wizSaveAndGoLive').disabled = wizardFaqs.length < 5;
            renderWizardFaqList();
        })
        .catch(e => alert(e.message));
}

function wizardLoadTemplateInstead() {
    if (!wizardTemplateType) return;
    fetch(API_BASE + '/admin/api/faq-templates/' + encodeURIComponent(wizardTemplateType), { headers: getHeaders() })
        .then(r => r.ok ? r.json() : Promise.reject(new Error('Failed to load template')))
        .then(data => {
            wizardFaqs = (data.faqs || []).map(f => ({ question: f.question, answer: f.answer }));
            document.getElementById('wizWebsiteFaqsNote').style.display = 'none';
            document.getElementById('wizSaveAndGoLive').disabled = wizardFaqs.length < 5;
            renderWizardFaqList();
        })
        .catch(e => alert(e.message));
}

function wizardWriteOwnFaqs() {
    wizardFaqs = [];
    document.querySelectorAll('.wizard-step').forEach(s => s.classList.remove('active'));
    document.getElementById('wizardStep2').classList.add('active');
    document.getElementById('wizSaveAndGoLive').disabled = wizardFaqs.length < 5;
    renderWizardFaqList();
}

function wizardAddFaq() {
    const q = document.getElementById('wizFaqQuestion').value.trim();
    const a = document.getElementById('wizFaqAnswer').value.trim();
    if (!q || !a) return;
    wizardFaqs.push({ question: q, answer: a });
    document.getElementById('wizFaqQuestion').value = '';
    document.getElementById('wizFaqAnswer').value = '';
    renderWizardFaqList();
}

function wizardRemoveFaq(i) {
    wizardFaqs.splice(i, 1);
    renderWizardFaqList();
}

function renderWizardFaqList() {
    const list = document.getElementById('wizFaqList');
    list.innerHTML = wizardFaqs.map((faq, i) => `
        <li>
            <div><div class="q">${escapeHtml(faq.question)}</div><div class="a">${escapeHtml(faq.answer.substring(0, 80))}${faq.answer.length > 80 ? '…' : ''}</div></div>
            <div class="faq-actions"><button type="button" class="btn-danger" data-faq-i="${i}">Delete</button></div>
        </li>
    `).join('');
    list.querySelectorAll('[data-faq-i]').forEach(btn => {
        btn.addEventListener('click', () => wizardRemoveFaq(parseInt(btn.getAttribute('data-faq-i'), 10)));
    });
    const n = wizardFaqs.length;
    const msgEl = document.getElementById('wizMinFaqMsg');
    if (n < 5) msgEl.textContent = 'Add at least 5 FAQs for best results (you have ' + n + ').';
    else msgEl.textContent = '';
    document.getElementById('wizSaveAndGoLive').disabled = n < 5;
}

async function wizardSaveAndGoLive() {
    if (wizardFaqs.length < 5) return;
    const progressEl = document.getElementById('wizGoLiveProgress');
    const errEl = document.getElementById('wizStep2Error');
    progressEl.style.display = 'block';
    progressEl.className = 'wizard-progress';
    progressEl.textContent = 'Setting up your widget...';
    errEl.textContent = '';
    try {
        const putRes = await fetch(API_BASE + '/admin/api/tenant/' + encodeURIComponent(wizardTenantId) + '/faqs/staged', {
            method: 'PUT', headers: getHeaders(), body: JSON.stringify(wizardFaqs)
        });
        if (!putRes.ok) { const d = await putRes.json(); throw new Error(d.detail || 'HTTP ' + putRes.status); }
        progressEl.textContent = 'Generating smart matching...';
        const promoteRes = await fetch(API_BASE + '/admin/api/tenant/' + encodeURIComponent(wizardTenantId) + '/promote', {
            method: 'POST', headers: getHeaders()
        });
        const data = await promoteRes.json();
        if (data.status !== 'success') throw new Error(data.message || 'Promote failed');
        progressEl.textContent = 'Waiting for embeddings (15s)...';
        await new Promise(r => setTimeout(r, 15000));
        progressEl.textContent = 'Done! ✓';
        progressEl.classList.add('done');
        document.querySelectorAll('.wizard-step').forEach(s => s.classList.remove('active'));
        document.getElementById('wizardStep3').classList.add('active');
        document.getElementById('wizLiveTitle').textContent = '✓ ' + escapeHtml(wizardBusinessName) + ' is live!';
        loadWizardSuggested();
        var floatSnippet = '<!-- MotionMade AI - Instant Answers for ' + escapeHtml(wizardBusinessName) + ' -->\n<script src="' + escapeHtml(API_BASE) + '/widget.js"\n  data-tenant="' + escapeHtml(wizardTenantId) + '"\n  data-name="' + escapeHtml(wizardBusinessName) + '"\n  data-phone="' + escapeHtml(wizardContactPhone) + '"\n  data-color="#2563EB"\n  data-mode="float"\n  data-api="' + escapeHtml(API_BASE) + '"><\/script>';
        var inlineSnippet = '<!-- MotionMade AI - Inline widget -->\n<div id="motionmade-widget"><\/div>\n<script src="' + escapeHtml(API_BASE) + '/widget.js"\n  data-tenant="' + escapeHtml(wizardTenantId) + '"\n  data-name="' + escapeHtml(wizardBusinessName) + '"\n  data-phone="' + escapeHtml(wizardContactPhone) + '"\n  data-color="#2563EB"\n  data-mode="inline"\n  data-api="' + escapeHtml(API_BASE) + '"><\/script>';
        document.getElementById('wizEmbedCode').textContent = floatSnippet;
        var elInline = document.getElementById('wizEmbedCodeInline');
        if (elInline) elInline.textContent = inlineSnippet;
    } catch (e) {
        errEl.textContent = e.message;
        progressEl.style.display = 'none';
    }
}

async function loadWizardSuggested() {
    if (!wizardTenantId) return;
    try {
        const r = await fetch(API_BASE + '/api/v2/tenant/' + encodeURIComponent(wizardTenantId) + '/suggested-questions');
        const data = await r.json();
        wizardSuggestedQuestions = data.questions || [];
    } catch (e) {
        wizardSuggestedQuestions = [];
    }
    wizardRenderPreviewMain();
}

function wizardRenderPreviewMain() {
    const body = document.getElementById('wizPreviewBody');
    if (!body) return;
    body.innerHTML = '';
    body.innerHTML += '<div class="mm-suggest" style="font-size:13px;color:#6b7280;margin-bottom:10px">Common questions:</div>';
    var ul = document.createElement('ul');
    ul.className = 'mm-qlist';
    ul.style.cssText = 'list-style:none;margin:0 0 16px;padding:0';
    wizardSuggestedQuestions.forEach(function (q) {
        var li = document.createElement('li');
        li.style.cssText = 'margin:0 0 6px;padding:10px 12px;background:#f3f4f6;border-radius:8px;cursor:pointer;font-size:14px';
        li.textContent = q;
        li.onclick = function () { wizardAskQuestion(q); };
        ul.appendChild(li);
    });
    body.appendChild(ul);
    body.innerHTML += '<div class="mm-or" style="font-size:13px;color:#6b7280;margin:12px 0 8px">Or ask your own:</div>';
    var row = document.createElement('div');
    row.className = 'mm-inrow';
    row.style.cssText = 'display:flex;gap:8px;margin-top:8px';
    var input = document.createElement('input');
    input.type = 'text';
    input.placeholder = 'Type your question...';
    input.style.cssText = 'flex:1;padding:10px 12px;border:1px solid #d1d5db;border-radius:8px;font-size:14px';
    var askBtn = document.createElement('button');
    askBtn.type = 'button';
    askBtn.textContent = 'Ask';
    askBtn.style.cssText = 'padding:10px 16px;background:#2563EB;color:#fff;border:none;border-radius:8px;cursor:pointer;font-size:14px';
    askBtn.onclick = function () { var t = input.value.trim(); if (t) wizardAskQuestion(t); };
    input.onkeydown = function (e) { if (e.key === 'Enter') { e.preventDefault(); askBtn.click(); } };
    row.appendChild(input);
    row.appendChild(askBtn);
    body.appendChild(row);
}

function wizardAskQuestion(questionText) {
    const body = document.getElementById('wizPreviewBody');
    if (!body || !wizardTenantId) return;
    body.innerHTML = '<div class="mm-your-q" style="font-size:13px;color:#6b7280;margin-bottom:6px">Your question:</div><q style="font-style:normal;color:#374151">' + escapeHtml(questionText) + '</q><div class="mm-answer-block" style="margin-top:12px"><div class="mm-spinner" style="height:24px;width:24px;border:3px solid #e5e7eb;border-top-color:#2563EB;border-radius:50%;animation:mm-spin .6s linear infinite"></div></div><div class="mm-again" style="margin-top:14px"><button type="button" class="btn-secondary">Ask another question</button></div>';
    body.querySelector('.mm-again button').onclick = function () { wizardRenderPreviewMain(); loadWizardSuggested(); };
    fetch(API_BASE + '/api/v2/generate-quote-reply', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tenantId: wizardTenantId, customerMessage: questionText })
    })
        .then(function (r) { return r.json(); })
        .then(function (data) {
            var block = body.querySelector('.mm-answer-block');
            if (block) block.innerHTML = '<div class="mm-ans-box" style="padding:12px;background:#f0f9ff;border:1px solid #bae6fd;border-radius:8px;font-size:14px;color:#0c4a6e;white-space:pre-wrap">' + escapeHtml((data.replyText || '').trim() || 'No reply.') + '</div>';
        })
        .catch(function () {
            var block = body.querySelector('.mm-answer-block');
            if (block) block.innerHTML = '<div class="mm-err" style="color:#dc2626;font-size:14px">Something went wrong. Try again.</div>';
        });
}

function wizardCopyEmbed(targetId, btnId) {
    targetId = targetId || 'wizEmbedCode';
    btnId = btnId || 'wizCopyEmbed';
    const el = document.getElementById(targetId);
    const btn = document.getElementById(btnId);
    if (!el || !btn) return;
    navigator.clipboard.writeText(el.textContent).then(() => {
        btn.textContent = 'Copied! ✓';
        btn.classList.add('copied');
        setTimeout(() => { btn.textContent = 'Copy Code'; btn.classList.remove('copied'); }, 2000);
    }).catch(() => {
        const ta = document.createElement('textarea');
        ta.value = el.textContent;
        ta.style.position = 'fixed';
        ta.style.opacity = '0';
        document.body.appendChild(ta);
        ta.select();
        document.execCommand('copy');
        document.body.removeChild(ta);
        btn.textContent = 'Copied! ✓';
        setTimeout(() => { btn.textContent = 'Copy Code'; }, 2000);
    });
}

// ---------- DOM ready ----------
(function initDomReady() {
    const domEl = document.getElementById('debugDomReady');
    if (domEl) { domEl.textContent = 'yes'; }
    const jsEl = document.getElementById('debugJsRunning');
    if (jsEl) { jsEl.textContent = 'yes'; }
})();

document.addEventListener('DOMContentLoaded', function () {
    document.getElementById('loginButton').addEventListener('click', function (e) { e.preventDefault(); login(); });
    document.getElementById('adminToken').addEventListener('keydown', function (e) { if (e.key === 'Enter') login(); });
    document.getElementById('backToListLink').addEventListener('click', function (e) { e.preventDefault(); loadTenants(); });
    document.getElementById('showNewBusinessButton').addEventListener('click', showWizard);
    document.getElementById('wizBusinessName').addEventListener('input', updateWizardWidgetIdPreview);
    document.getElementById('backFromWizardLink').addEventListener('click', function (e) { e.preventDefault(); loadTenants(); });
    document.getElementById('wizStep1Next').addEventListener('click', wizardStep1Next);
    document.getElementById('wizUseTemplateBtn').addEventListener('click', wizardUseTemplate);
    document.getElementById('wizWriteOwnFaqsBtn').addEventListener('click', wizardWriteOwnFaqs);
    const loadTemplateInsteadBtn = document.getElementById('wizLoadTemplateInsteadBtn');
    if (loadTemplateInsteadBtn) loadTemplateInsteadBtn.addEventListener('click', wizardLoadTemplateInstead);
    document.getElementById('wizAddFaq').addEventListener('click', wizardAddFaq);
    document.getElementById('wizFaqAnswer').addEventListener('keydown', function (e) { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); wizardAddFaq(); } });
    document.getElementById('wizSaveAndGoLive').addEventListener('click', wizardSaveAndGoLive);
    document.getElementById('wizCopyEmbed').addEventListener('click', function () { wizardCopyEmbed('wizEmbedCode', 'wizCopyEmbed'); });
    var wizCopyInline = document.getElementById('wizCopyEmbedInline');
    if (wizCopyInline) wizCopyInline.addEventListener('click', function () { wizardCopyEmbed('wizEmbedCodeInline', 'wizCopyEmbedInline'); });
    document.getElementById('wizBackToBusinesses').addEventListener('click', loadTenants);

    document.addEventListener('click', function (e) {
        if (e.target.classList.contains('viewTenantButton') || e.target.classList.contains('editFaqsButton')) {
            e.preventDefault();
            const id = e.target.getAttribute('data-tenant-id');
            if (id) showTenantDetail(id);
        }
        if (e.target.classList.contains('deleteTenantButton')) {
            e.preventDefault();
            const id = e.target.getAttribute('data-tenant-id');
            if (id) deleteTenant(id);
        }
        if (e.target.id === 'addDomainButton') {
            e.preventDefault();
            const id = e.target.getAttribute('data-tenant-id');
            if (id) addDomain(id);
        }
        if (e.target.classList.contains('removeDomainButton')) {
            e.preventDefault();
            const id = e.target.getAttribute('data-tenant-id');
            const domain = e.target.getAttribute('data-domain');
            if (id && domain) removeDomain(id, domain);
        }
        if (e.target.id === 'uploadStagedFaqsButton') {
            e.preventDefault();
            const id = e.target.getAttribute('data-tenant-id');
            if (id) uploadStagedFaqs(id);
        }
        if (e.target.id === 'promoteStagedButton') {
            e.preventDefault();
            const id = e.target.getAttribute('data-tenant-id');
            if (id) promoteStaged(id);
        }
        if (e.target.id === 'rollbackTenantButton') {
            e.preventDefault();
            const id = e.target.getAttribute('data-tenant-id');
            if (id) rollbackTenant(id);
        }
        if (e.target.id === 'generateFaqsFromUrlButton') {
            e.preventDefault();
            const tenantId = e.target.getAttribute('data-tenant-id');
            const url = document.getElementById('tenantWebsiteUrl')?.value?.trim();
            const detail = document.getElementById('tenantDetail');
            const name = (detail && detail.getAttribute('data-tenant-name')) || '';
            if (tenantId && url) generateFaqsFromUrl(tenantId, url, name);
            else document.getElementById('generateFaqsError').textContent = 'Enter a website URL';
        }
        if (e.target.id === 'addGeneratedToStagedButton') {
            e.preventDefault();
            addGeneratedToStaged();
        }
        if (e.target.id === 'createOwnerAccountButton') {
            e.preventDefault();
            const form = document.getElementById('createOwnerForm');
            if (form) form.style.display = form.style.display === 'none' ? 'block' : 'none';
        }
        if (e.target.id === 'createOwnerButton') {
            e.preventDefault();
            const id = e.target.getAttribute('data-tenant-id');
            if (id) createOwner(id);
        }
        if (e.target.id === 'resetOwnerPasswordButton') {
            e.preventDefault();
            const id = e.target.getAttribute('data-tenant-id');
            if (id) resetOwnerPassword(id);
        }
        if (e.target.id === 'deleteOwnerButton') {
            e.preventDefault();
            const id = e.target.getAttribute('data-tenant-id');
            if (id) deleteOwner(id);
        }
        if (e.target.classList.contains('approveSuggestionButton')) {
            e.preventDefault();
            const tid = e.target.getAttribute('data-tenant-id');
            const sid = e.target.getAttribute('data-suggestion-id');
            if (tid && sid) approveSuggestion(tid, sid);
        }
        if (e.target.classList.contains('rejectSuggestionButton')) {
            e.preventDefault();
            const tid = e.target.getAttribute('data-tenant-id');
            const sid = e.target.getAttribute('data-suggestion-id');
            if (tid && sid) rejectSuggestion(tid, sid);
        }
        if (e.target.classList.contains('copyInstallBtn')) {
            e.preventDefault();
            const targetId = e.target.getAttribute('data-target');
            if (targetId) copyInstallSnippetTarget(targetId);
        }
    });
});
