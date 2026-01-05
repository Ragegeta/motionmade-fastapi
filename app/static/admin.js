// API base URL - use current origin
const API_BASE = window.location.origin;

let adminToken = '';

// ========================================
// UI DEBUG - ALWAYS RUNS FIRST
// ========================================

// Mark JS as running immediately
(function() {
    const jsRunningEl = document.getElementById('debugJsRunning');
    if (jsRunningEl) {
        jsRunningEl.textContent = 'yes';
        jsRunningEl.style.color = '#28a745';
    }
})();

// Update time every second
function updateDebugTime() {
    const timeEl = document.getElementById('debugTime');
    if (timeEl) {
        timeEl.textContent = new Date().toLocaleTimeString();
    }
}
setInterval(updateDebugTime, 1000);
updateDebugTime(); // Initial update

// Track all clicks
document.addEventListener('click', function(e) {
    const clickEl = document.getElementById('debugLastClick');
    if (clickEl) {
        const target = e.target.id || e.target.className || e.target.tagName;
        clickEl.textContent = `${new Date().toLocaleTimeString()} - ${target}`;
    }
}, true); // Use capture phase to catch all clicks

// Global error capture
window.onerror = function(message, source, lineno, colno, error) {
    const errorEl = document.getElementById('uiErrors');
    const errorText = `[${new Date().toLocaleTimeString()}] ERROR: ${message}\n  Source: ${source}:${lineno}:${colno}\n  Stack: ${error ? error.stack : 'No stack'}\n\n`;
    if (errorEl) {
        errorEl.textContent = errorText + errorEl.textContent;
    }
    console.error('UI Error:', message, source, lineno, colno, error);
    return false; // Don't prevent default error handling
};

window.onunhandledrejection = function(event) {
    const errorEl = document.getElementById('uiErrors');
    const errorText = `[${new Date().toLocaleTimeString()}] UNHANDLED REJECTION: ${event.reason}\n  Stack: ${event.reason && event.reason.stack ? event.reason.stack : 'No stack'}\n\n`;
    if (errorEl) {
        errorEl.textContent = errorText + errorEl.textContent;
    }
    console.error('Unhandled Rejection:', event.reason);
};

// Test button handler
function handleTestButton() {
    alert("JS works!");
    const banner = document.getElementById('uiDebugBanner');
    if (banner) {
        const currentBg = banner.style.background;
        banner.style.background = currentBg === '#d4edda' ? '#fff3cd' : '#d4edda';
    }
}

function getHeaders() {
    return {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${adminToken}`
    };
}

function showPage(pageId) {
    document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
    document.getElementById(pageId).classList.add('active');
}

function login() {
    // IMMEDIATE VISUAL FEEDBACK
    const loginButton = document.getElementById('loginButton');
    if (loginButton) {
        loginButton.textContent = 'Clicked ✓';
        setTimeout(() => {
            loginButton.textContent = 'Login';
        }, 2000);
    }
    
    // Append to diagnostics immediately
    const diagnosticsEl = document.getElementById('loginDiagnostics');
    const timestamp = new Date().toLocaleTimeString();
    const clickStatusEl = document.getElementById('loginClickStatus');
    if (clickStatusEl) {
        clickStatusEl.textContent = `[${timestamp}] ✓ Login button clicked`;
    }
    
    const token = document.getElementById('adminToken').value;
    if (!token) {
        const tokenMissingMsg = `[${new Date().toLocaleTimeString()}] ✗ Token missing - input field is empty`;
        if (clickStatusEl) {
            clickStatusEl.textContent = tokenMissingMsg;
            clickStatusEl.style.color = '#dc3545';
        }
        document.getElementById('authError').textContent = 'Token required';
        document.getElementById('loginTestStatus').textContent = 'Skipped - no token';
        return;
    }
    
    // Clear previous errors
    document.getElementById('loginTestStatus').textContent = `[${new Date().toLocaleTimeString()}] Testing GET /admin/api/tenants...`;
    document.getElementById('loginResponse').textContent = '';
    document.getElementById('loginError').textContent = '';
    
    // Test the token with a real API call
    adminToken = token;
    
    fetch(`${API_BASE}/admin/api/tenants`, {
        headers: getHeaders()
    })
    .then(async res => {
        const statusText = `[${new Date().toLocaleTimeString()}] Status: ${res.status} ${res.statusText}`;
        const statusEl = document.getElementById('loginTestStatus');
        if (statusEl) {
            statusEl.textContent = statusText;
        }
        
        const bodyText = await res.text();
        const preview = bodyText.length > 200 ? bodyText.substring(0, 200) + '...' : bodyText;
        document.getElementById('loginResponse').textContent = `Response (first 200 chars): ${preview}`;
        
        if (res.ok) {
            if (statusEl) {
                statusEl.style.color = '#28a745';
            }
            document.getElementById('authSection').style.display = 'none';
            loadTenants();
        } else {
            if (statusEl) {
                statusEl.style.color = '#dc3545';
            }
            document.getElementById('authError').textContent = `Login failed: ${res.status} ${res.statusText}`;
        }
    })
    .catch(err => {
        const errorMsg = `[${new Date().toLocaleTimeString()}] Error: ${err.message}`;
        const statusEl = document.getElementById('loginTestStatus');
        if (statusEl) {
            statusEl.textContent = errorMsg;
            statusEl.style.color = '#dc3545';
        }
        document.getElementById('loginError').textContent = `Stack: ${err.stack || 'No stack trace'}`;
        document.getElementById('authError').textContent = `Login failed: ${err.message}`;
    });
}

function copyCurlCommand() {
    const token = document.getElementById('adminToken').value || '';
    const curlCmd = `curl.exe -i "${API_BASE}/admin/api/tenants" -H "Authorization: Bearer ${token}"`;
    
    // Copy to clipboard
    navigator.clipboard.writeText(curlCmd).then(() => {
        alert('Curl command copied to clipboard!');
    }).catch(() => {
        // Fallback
        const textArea = document.createElement('textarea');
        textArea.value = curlCmd;
        textArea.style.position = 'fixed';
        textArea.style.opacity = '0';
        document.body.appendChild(textArea);
        textArea.select();
        document.execCommand('copy');
        document.body.removeChild(textArea);
        alert('Curl command copied to clipboard!');
    });
}

async function loadTenants() {
    try {
        const res = await fetch(`${API_BASE}/admin/api/tenants`, {
            headers: getHeaders()
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        
        const tbody = document.getElementById('tenantsTable');
        tbody.innerHTML = '';
        
        data.tenants.forEach(t => {
            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td>${escapeHtml(t.id)}</td>
                <td>${escapeHtml(t.name)}</td>
                <td>${t.created_at ? new Date(t.created_at).toLocaleDateString() : ''}</td>
                <td><button class="viewTenantButton" data-tenant-id="${escapeHtml(t.id)}">View</button></td>
            `;
            tbody.appendChild(tr);
        });
        
        showPage('tenantsPage');
    } catch (e) {
        document.getElementById('authError').textContent = `Error: ${e.message}`;
        document.getElementById('authSection').style.display = 'block';
    }
}

async function showTenantDetail(tenantId) {
    try {
        const [tenantRes, statsRes] = await Promise.all([
            fetch(`${API_BASE}/admin/api/tenant/${tenantId}`, { headers: getHeaders() }),
            fetch(`${API_BASE}/admin/api/tenant/${tenantId}/stats`, { headers: getHeaders() }).catch(() => null)
        ]);
        
        if (!tenantRes.ok) throw new Error(`HTTP ${tenantRes.status}`);
        const tenant = await tenantRes.json();
        const stats = statsRes && statsRes.ok ? await statsRes.json() : null;
        
        const detailDiv = document.getElementById('tenantDetail');
        detailDiv.innerHTML = `
            <h1>${escapeHtml(tenant.name || tenant.id)}</h1>
            <p style="color: #666; margin-bottom: 20px;">ID: ${escapeHtml(tenant.id)}</p>
            
            <div class="section">
                <h2>Domains</h2>
                <div class="form-group" style="display: flex; gap: 10px;">
                    <input type="text" id="newDomain" placeholder="example.com" style="flex: 1;" />
                    <button class="primary" id="addDomainButton" data-tenant-id="${escapeHtml(tenant.id)}">Add Domain</button>
                </div>
                <ul class="domains-list" id="domainsList">
                    ${tenant.domains.map(d => `
                        <li>
                            <span>${escapeHtml(d.domain)} ${d.enabled ? '✓' : '✗'}</span>
                            <button class="removeDomainButton" data-tenant-id="${escapeHtml(tenant.id)}" data-domain="${escapeHtml(d.domain)}">Remove</button>
                        </li>
                    `).join('')}
                </ul>
            </div>
            
            <div class="section">
                <h2>FAQs</h2>
                <div style="margin-bottom: 15px;">
                    <p style="color: #666; margin-bottom: 10px;">
                        Live: ${tenant.live_faq_count || 0} | 
                        Staged: ${tenant.staged_faq_count || 0} | 
                        Last Good: ${tenant.last_good_count || 0}
                    </p>
                    ${tenant.last_run ? `
                        <p style="margin-bottom: 10px;">
                            <strong>Last Run:</strong> 
                            <span style="color: ${tenant.last_run.status === 'success' ? '#28a745' : '#dc3545'};">
                                ${tenant.last_run.status.toUpperCase()}
                            </span>
                            ${tenant.last_run.created_at ? `(${new Date(tenant.last_run.created_at).toLocaleString()})` : ''}
                        </p>
                    ` : ''}
                </div>
                <div class="form-group">
                    <label>Upload Staged FAQs (JSON)</label>
                    <textarea id="stagedFaqsJson" placeholder='[{"question": "Q1", "answer": "A1", "variants": ["v1"]}]'></textarea>
                </div>
                <div style="display: flex; gap: 10px; margin-bottom: 10px;">
                    <button class="primary" id="uploadStagedFaqsButton" data-tenant-id="${escapeHtml(tenant.id)}">Upload Staged</button>
                    <button class="secondary" id="runSuiteButton" data-tenant-id="${escapeHtml(tenant.id)}">Run Suite</button>
                    <button class="primary" id="promoteStagedButton" data-tenant-id="${escapeHtml(tenant.id)}" ${tenant.staged_faq_count == 0 ? 'disabled' : ''}>Promote</button>
                    <button class="secondary" id="rollbackTenantButton" data-tenant-id="${escapeHtml(tenant.id)}" ${tenant.last_good_count == 0 ? 'disabled' : ''}>Rollback</button>
                </div>
                <div id="faqsError" class="error"></div>
                <div id="faqsSuccess" class="success"></div>
            </div>
            
            <div class="section">
                <h2>Stats (Last 24 Hours)</h2>
                ${stats ? `
                    <div class="stats-grid">
                        <div class="stat-card">
                            <div class="label">Total Queries</div>
                            <div class="value">${stats.total_queries}</div>
                        </div>
                        <div class="stat-card">
                            <div class="label">FAQ Hit Rate</div>
                            <div class="value">${(stats.faq_hit_rate * 100).toFixed(1)}%</div>
                        </div>
                        <div class="stat-card">
                            <div class="label">Clarify Rate</div>
                            <div class="value">${(stats.clarify_rate * 100).toFixed(1)}%</div>
                        </div>
                        <div class="stat-card">
                            <div class="label">Fallback Rate</div>
                            <div class="value">${(stats.fallback_rate * 100).toFixed(1)}%</div>
                        </div>
                        <div class="stat-card">
                            <div class="label">Rewrite Rate</div>
                            <div class="value">${(stats.rewrite_rate * 100).toFixed(1)}%</div>
                        </div>
                        <div class="stat-card">
                            <div class="label">Avg Latency</div>
                            <div class="value">${stats.avg_latency_ms}ms</div>
                        </div>
                    </div>
                ` : '<p style="color: #666;">No stats available</p>'}
            </div>
            
            <div class="section">
                <h2>Install Snippet</h2>
                <p style="color: #666; margin-bottom: 15px;">Copy and paste this script tag into your website, just before the closing <code>&lt;/body&gt;</code> tag:</p>
                
                <div class="form-group">
                    <label>Widget URL</label>
                    <input type="text" id="installApiBase" value="https://api.motionmadebne.com.au" placeholder="API base URL" />
                </div>
                <div class="form-group">
                    <label>Greeting Message</label>
                    <input type="text" id="installGreeting" value="Hi! How can I help you today?" placeholder="Initial greeting" />
                </div>
                <div class="form-group">
                    <label>Header Text</label>
                    <input type="text" id="installHeader" value="Chat with us" placeholder="Chat header" />
                </div>
                <div class="form-group">
                    <label>Color (hex)</label>
                    <input type="text" id="installColor" value="#2563eb" placeholder="#2563eb" />
                </div>
                <div class="form-group">
                    <label>Position</label>
                    <select id="installPosition">
                        <option value="bottom-right" selected>Bottom Right</option>
                        <option value="bottom-left">Bottom Left</option>
                        <option value="top-right">Top Right</option>
                        <option value="top-left">Top Left</option>
                    </select>
                </div>
                
                <div style="margin-top: 15px; margin-bottom: 10px;">
                    <div style="display: flex; align-items: center; gap: 10px; margin-bottom: 10px;">
                        <code id="installSnippet" style="background: #f8f9fa; padding: 12px; display: block; flex: 1; border-radius: 4px; font-family: monospace; font-size: 13px; white-space: pre-wrap; word-break: break-all;"></code>
                        <button id="copyButton" class="primary" style="white-space: nowrap;">Copy</button>
                    </div>
                    <div id="copySuccess" style="color: #28a745; font-size: 12px; display: none;">✓ Copied!</div>
                </div>
                
                <div style="background: #fff3cd; border: 1px solid #ffc107; border-radius: 4px; padding: 10px; margin-top: 10px; font-size: 13px;">
                    <strong>Note:</strong> Paste this snippet before the closing <code>&lt;/body&gt;</code> tag. If you use Content Security Policy (CSP), allowlist:
                    <ul style="margin: 8px 0 0 20px; padding: 0;">
                        <li><code>https://mm-client1-creator-ui.pages.dev</code> (widget.js source)</li>
                        <li><code>https://api.motionmadebne.com.au</code> (API endpoint)</li>
                    </ul>
                </div>
            </div>
            
            <div class="section">
                <h2>Actions</h2>
                <p style="color: #666; margin-bottom: 10px;">For suite runs and promote/rollback, use the pipeline script:</p>
                <code style="background: #f8f9fa; padding: 10px; display: block; border-radius: 4px; margin-bottom: 10px;">
                    .\run_faq_pipeline.ps1 -TenantId ${escapeHtml(tenant.id)}
                </code>
            </div>
        `;
        
        // Initialize install snippet
        updateInstallSnippet();
        
        showPage('tenantDetailPage');
    } catch (e) {
        alert(`Error: ${e.message}`);
    }
}

async function addDomain(tenantId) {
    const domain = document.getElementById('newDomain').value.trim();
    if (!domain) {
        alert('Domain required');
        return;
    }
    
    try {
        const res = await fetch(`${API_BASE}/admin/api/tenant/${tenantId}/domains`, {
            method: 'POST',
            headers: getHeaders(),
            body: JSON.stringify({ domain })
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        showTenantDetail(tenantId);
    } catch (e) {
        alert(`Error: ${e.message}`);
    }
}

async function removeDomain(tenantId, domain) {
    if (!confirm(`Remove domain ${domain}?`)) return;
    
    try {
        const res = await fetch(`${API_BASE}/admin/api/tenant/${tenantId}/domains/${encodeURIComponent(domain)}`, {
            method: 'DELETE',
            headers: getHeaders()
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        showTenantDetail(tenantId);
    } catch (e) {
        alert(`Error: ${e.message}`);
    }
}

async function uploadStagedFaqs(tenantId) {
    const jsonText = document.getElementById('stagedFaqsJson').value.trim();
    if (!jsonText) {
        document.getElementById('faqsError').textContent = 'FAQ JSON required';
        return;
    }
    
    let items;
    try {
        items = JSON.parse(jsonText);
    } catch (e) {
        document.getElementById('faqsError').textContent = `Invalid JSON: ${e.message}`;
        return;
    }
    
    try {
        const res = await fetch(`${API_BASE}/admin/api/tenant/${tenantId}/faqs/staged`, {
            method: 'PUT',
            headers: getHeaders(),
            body: JSON.stringify(items)
        });
        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.detail || `HTTP ${res.status}`);
        }
        const data = await res.json();
        document.getElementById('faqsError').textContent = '';
        document.getElementById('faqsSuccess').textContent = `Staged ${data.staged_count} FAQs successfully`;
        setTimeout(() => showTenantDetail(tenantId), 1000);
    } catch (e) {
        document.getElementById('faqsError').textContent = `Error: ${e.message}`;
        document.getElementById('faqsSuccess').textContent = '';
    }
}

async function runSuite(tenantId) {
    document.getElementById('faqsError').textContent = '';
    document.getElementById('faqsSuccess').textContent = 'Running suite...';
    
    try {
        // Run suite by promoting (which runs suite internally)
        const res = await fetch(`${API_BASE}/admin/api/tenant/${tenantId}/promote`, {
            method: 'POST',
            headers: getHeaders()
        });
        const data = await res.json();
        
        if (data.status === 'success') {
            document.getElementById('faqsSuccess').textContent = `Suite passed: ${data.suite_result.passed_count}/${data.suite_result.total} tests`;
        } else {
            document.getElementById('faqsError').textContent = `Suite failed: ${data.suite_result.failed_count}/${data.suite_result.total} tests failed`;
            if (data.first_failure) {
                document.getElementById('faqsError').textContent += `\nFirst failure: ${data.first_failure.test_name || 'unknown'}`;
            }
        }
        setTimeout(() => showTenantDetail(tenantId), 2000);
    } catch (e) {
        document.getElementById('faqsError').textContent = `Error: ${e.message}`;
        document.getElementById('faqsSuccess').textContent = '';
    }
}

async function promoteStaged(tenantId) {
    if (!confirm('Promote staged FAQs to live? This will run the test suite first.')) return;
    
    document.getElementById('faqsError').textContent = '';
    document.getElementById('faqsSuccess').textContent = 'Promoting...';
    
    try {
        const res = await fetch(`${API_BASE}/admin/api/tenant/${tenantId}/promote`, {
            method: 'POST',
            headers: getHeaders()
        });
        const data = await res.json();
        
        if (data.status === 'success') {
            document.getElementById('faqsSuccess').textContent = data.message;
        } else {
            document.getElementById('faqsError').textContent = data.message;
            if (data.first_failure) {
                document.getElementById('faqsError').textContent += `\nFirst failure: ${data.first_failure.test_name || 'unknown'}`;
            }
        }
        setTimeout(() => showTenantDetail(tenantId), 2000);
    } catch (e) {
        document.getElementById('faqsError').textContent = `Error: ${e.message}`;
        document.getElementById('faqsSuccess').textContent = '';
    }
}

async function rollbackTenant(tenantId) {
    if (!confirm('Rollback to last_good FAQs? This will replace current live FAQs.')) return;
    
    document.getElementById('faqsError').textContent = '';
    document.getElementById('faqsSuccess').textContent = 'Rolling back...';
    
    try {
        const res = await fetch(`${API_BASE}/admin/api/tenant/${tenantId}/rollback`, {
            method: 'POST',
            headers: getHeaders()
        });
        const data = await res.json();
        
        if (data.status === 'success') {
            document.getElementById('faqsSuccess').textContent = data.message;
        } else {
            document.getElementById('faqsError').textContent = `Error: ${data.message || 'Unknown error'}`;
        }
        setTimeout(() => showTenantDetail(tenantId), 1000);
    } catch (e) {
        document.getElementById('faqsError').textContent = `Error: ${e.message}`;
        document.getElementById('faqsSuccess').textContent = '';
    }
}

function showCreateTenant() {
    showPage('createTenantPage');
}

async function createTenant() {
    const id = document.getElementById('newTenantId').value.trim();
    const name = document.getElementById('newTenantName').value.trim();
    
    if (!id) {
        document.getElementById('createError').textContent = 'Tenant ID required';
        return;
    }
    
    try {
        const res = await fetch(`${API_BASE}/admin/api/tenants`, {
            method: 'POST',
            headers: getHeaders(),
            body: JSON.stringify({ id, name: name || id })
        });
        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.detail || `HTTP ${res.status}`);
        }
        loadTenants();
    } catch (e) {
        document.getElementById('createError').textContent = `Error: ${e.message}`;
    }
}

function showTenantsList() {
    loadTenants();
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function updateInstallSnippet() {
    const apiBase = document.getElementById('installApiBase')?.value || 'https://api.motionmadebne.com.au';
    const greeting = document.getElementById('installGreeting')?.value || 'Hi! How can I help you today?';
    const header = document.getElementById('installHeader')?.value || 'Chat with us';
    const color = document.getElementById('installColor')?.value || '#2563eb';
    const position = document.getElementById('installPosition')?.value || 'bottom-right';
    
    const snippet = `<script src="https://mm-client1-creator-ui.pages.dev/widget.js"
          data-api="${escapeHtml(apiBase)}"
          data-greeting="${escapeHtml(greeting)}"
          data-header="${escapeHtml(header)}"
          data-color="${escapeHtml(color)}"
          data-position="${escapeHtml(position)}"></script>`;
    
    const snippetEl = document.getElementById('installSnippet');
    if (snippetEl) {
        snippetEl.textContent = snippet;
    }
}

async function copyInstallSnippet() {
    const snippetEl = document.getElementById('installSnippet');
    const copySuccess = document.getElementById('copySuccess');
    if (!snippetEl) return;
    
    try {
        await navigator.clipboard.writeText(snippetEl.textContent);
        if (copySuccess) {
            copySuccess.style.display = 'block';
            setTimeout(() => {
                copySuccess.style.display = 'none';
            }, 2000);
        }
    } catch (err) {
        // Fallback for older browsers
        const textArea = document.createElement('textarea');
        textArea.value = snippetEl.textContent;
        textArea.style.position = 'fixed';
        textArea.style.opacity = '0';
        document.body.appendChild(textArea);
        textArea.select();
        try {
            document.execCommand('copy');
            if (copySuccess) {
                copySuccess.style.display = 'block';
                setTimeout(() => {
                    copySuccess.style.display = 'none';
                }, 2000);
            }
        } catch (e) {
            alert('Failed to copy. Please select and copy manually.');
        }
        document.body.removeChild(textArea);
    }
}

// Onboarding functions
function showOnboarding() {
    showPage('onboardingPage');
    loadOnboardingTenants();
}

async function loadOnboardingTenants() {
    try {
        const res = await fetch(`${API_BASE}/admin/api/tenants`, {
            headers: getHeaders()
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        
        const select = document.getElementById('onboardTenantSelect');
        select.innerHTML = '<option value="">-- Select Tenant --</option>';
        data.tenants.forEach(t => {
            const opt = document.createElement('option');
            opt.value = t.id;
            opt.textContent = `${t.id} (${t.name || t.id})`;
            select.appendChild(opt);
        });
        
        select.onchange = function() {
            const tenantId = this.value;
            if (tenantId) {
                document.getElementById('onboardTenantInfo').style.display = 'block';
                document.getElementById('onboardTenantName').textContent = tenantId;
                loadOnboardingDomains(tenantId);
            } else {
                document.getElementById('onboardTenantInfo').style.display = 'none';
            }
        };
    } catch (e) {
        alert(`Error loading tenants: ${e.message}`);
    }
}

async function loadOnboardingDomains(tenantId) {
    try {
        const res = await fetch(`${API_BASE}/admin/api/tenant/${tenantId}`, {
            headers: getHeaders()
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        
        const list = document.getElementById('onboardDomainsList');
        list.innerHTML = '';
        if (data.domains && data.domains.length > 0) {
            data.domains.forEach(d => {
                const li = document.createElement('li');
                li.innerHTML = `<span>${escapeHtml(d.domain)}</span> <button class="onboardRemoveDomainButton" data-tenant-id="${escapeHtml(tenantId)}" data-domain="${escapeHtml(d.domain)}" style="font-size: 12px;">Remove</button>`;
                list.appendChild(li);
            });
        }
    } catch (e) {
        console.error('Error loading domains:', e);
    }
}

async function onboardAddDomain() {
    const tenantId = document.getElementById('onboardTenantSelect').value;
    const domain = document.getElementById('onboardDomain').value.trim();
    
    if (!tenantId) {
        alert('Please select a tenant first');
        return;
    }
    if (!domain) {
        alert('Please enter a domain');
        return;
    }
    
    try {
        const res = await fetch(`${API_BASE}/admin/api/tenant/${tenantId}/domains`, {
            method: 'POST',
            headers: getHeaders(),
            body: JSON.stringify({ domain })
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        document.getElementById('onboardDomain').value = '';
        loadOnboardingDomains(tenantId);
    } catch (e) {
        alert(`Error adding domain: ${e.message}`);
    }
}

async function onboardRemoveDomain(tenantId, domain) {
    if (!confirm(`Remove domain ${domain}?`)) return;
    
    try {
        const res = await fetch(`${API_BASE}/admin/api/tenant/${tenantId}/domains/${encodeURIComponent(domain)}`, {
            method: 'DELETE',
            headers: getHeaders()
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        loadOnboardingDomains(tenantId);
    } catch (e) {
        alert(`Error removing domain: ${e.message}`);
    }
}

// Initialize diagnostic banner
function updateDiagnosticBanner() {
    // Show API base
    const apiBaseEl = document.getElementById('apiBaseDisplay');
    if (apiBaseEl) {
        apiBaseEl.textContent = API_BASE;
    }
    
    // Test health endpoint
    fetch(`${API_BASE}/api/health`)
        .then(res => res.json())
        .then(data => {
            const healthEl = document.getElementById('healthStatus');
            const gitShaEl = document.getElementById('gitShaDisplay');
            if (healthEl) {
                healthEl.textContent = `✓ ${data.ok ? 'OK' : 'Error'}`;
                healthEl.style.color = data.ok ? '#28a745' : '#dc3545';
            }
            if (gitShaEl && data.gitSha) {
                gitShaEl.textContent = data.gitSha;
            }
        })
        .catch(err => {
            const healthEl = document.getElementById('healthStatus');
            if (healthEl) {
                healthEl.textContent = `✗ Error: ${err.message}`;
                healthEl.style.color = '#dc3545';
            }
        });
}

// Initialize event listeners after DOM is ready
document.addEventListener('DOMContentLoaded', function() {
    // Mark DOM as ready
    const domReadyEl = document.getElementById('debugDomReady');
    if (domReadyEl) {
        domReadyEl.textContent = 'yes';
        domReadyEl.style.color = '#28a745';
    }
    
    // Update diagnostic banner
    updateDiagnosticBanner();
    
    // Test button
    const testButton = document.getElementById('debugTestButton');
    if (testButton) {
        testButton.addEventListener('click', handleTestButton);
    }
    
    // Login button - BULLETPROOF WIRING
    const loginButton = document.getElementById('loginButton');
    if (loginButton) {
        loginButton.addEventListener('click', function(e) {
            e.preventDefault();
            login();
        });
    } else {
        // Log error if button not found
        const errorEl = document.getElementById('uiErrors');
        if (errorEl) {
            errorEl.textContent = '[ERROR] loginButton not found in DOM!\n' + errorEl.textContent;
        }
        console.error('loginButton not found!');
    }
    
    // Copy curl button
    const copyCurlButton = document.getElementById('copyCurlButton');
    if (copyCurlButton) {
        copyCurlButton.addEventListener('click', copyCurlCommand);
    }
    
    // Navigation buttons
    const showOnboardingButton = document.getElementById('showOnboardingButton');
    if (showOnboardingButton) {
        showOnboardingButton.addEventListener('click', showOnboarding);
    }
    
    const showCreateTenantButton = document.getElementById('showCreateTenantButton');
    if (showCreateTenantButton) {
        showCreateTenantButton.addEventListener('click', showCreateTenant);
    }
    
    const backToTenantsLink1 = document.getElementById('backToTenantsLink1');
    if (backToTenantsLink1) {
        backToTenantsLink1.addEventListener('click', function(e) {
            e.preventDefault();
            showTenantsList();
        });
    }
    
    const backToTenantsButton = document.getElementById('backToTenantsButton');
    if (backToTenantsButton) {
        backToTenantsButton.addEventListener('click', showTenantsList);
    }
    
    // Create tenant button
    const createTenantButton = document.getElementById('createTenantButton');
    if (createTenantButton) {
        createTenantButton.addEventListener('click', createTenant);
    }
    
    // Onboarding buttons
    const onboardShowCreateButton = document.getElementById('onboardShowCreateButton');
    if (onboardShowCreateButton) {
        onboardShowCreateButton.addEventListener('click', showCreateTenant);
    }
    
    const onboardAddDomainButton = document.getElementById('onboardAddDomainButton');
    if (onboardAddDomainButton) {
        onboardAddDomainButton.addEventListener('click', onboardAddDomain);
    }
    
    const onboardUploadStagedButton = document.getElementById('onboardUploadStagedButton');
    if (onboardUploadStagedButton) {
        onboardUploadStagedButton.addEventListener('click', onboardUploadStaged);
    }
    
    const onboardPromoteBtn = document.getElementById('onboardPromoteBtn');
    if (onboardPromoteBtn) {
        onboardPromoteBtn.addEventListener('click', onboardPromote);
    }
    
    const onboardBenchmarkBtn = document.getElementById('onboardBenchmarkBtn');
    if (onboardBenchmarkBtn) {
        onboardBenchmarkBtn.addEventListener('click', onboardRunBenchmark);
    }
    
    const onboardSyncBtn = document.getElementById('onboardSyncBtn');
    if (onboardSyncBtn) {
        onboardSyncBtn.addEventListener('click', onboardSyncWorker);
    }
    
    const onboardCheckReadinessButton = document.getElementById('onboardCheckReadinessButton');
    if (onboardCheckReadinessButton) {
        onboardCheckReadinessButton.addEventListener('click', onboardCheckReadiness);
    }
    
    const copyOnboardSnippetButton = document.getElementById('copyOnboardSnippetButton');
    if (copyOnboardSnippetButton) {
        copyOnboardSnippetButton.addEventListener('click', copyOnboardSnippet);
    }
    
    // Install snippet inputs (for live updates)
    const installInputs = ['installApiBase', 'installGreeting', 'installHeader', 'installColor', 'installPosition'];
    installInputs.forEach(id => {
        const el = document.getElementById(id);
        if (el) {
            el.addEventListener('input', updateInstallSnippet);
            el.addEventListener('change', updateInstallSnippet);
        }
    });
    
    // Copy install snippet button
    const copyButton = document.getElementById('copyButton');
    if (copyButton) {
        copyButton.addEventListener('click', copyInstallSnippet);
    }
    
    // File upload for onboarding FAQs
    const onboardFaqsFile = document.getElementById('onboardFaqsFile');
    if (onboardFaqsFile) {
        onboardFaqsFile.addEventListener('change', function(e) {
            const file = e.target.files[0];
            if (file) {
                const reader = new FileReader();
                reader.onload = function(e) {
                    document.getElementById('onboardFaqsJson').value = e.target.result;
                };
                reader.readAsText(file);
            }
        });
    }
    
    // Event delegation for dynamically added buttons
    document.addEventListener('click', function(e) {
        // View tenant button
        if (e.target.classList.contains('viewTenantButton')) {
            e.preventDefault();
            const tenantId = e.target.getAttribute('data-tenant-id');
            if (tenantId) showTenantDetail(tenantId);
        }
        
        // Add domain button
        if (e.target.id === 'addDomainButton') {
            e.preventDefault();
            const tenantId = e.target.getAttribute('data-tenant-id');
            if (tenantId) addDomain(tenantId);
        }
        
        // Remove domain button
        if (e.target.classList.contains('removeDomainButton')) {
            e.preventDefault();
            const tenantId = e.target.getAttribute('data-tenant-id');
            const domain = e.target.getAttribute('data-domain');
            if (tenantId && domain) removeDomain(tenantId, domain);
        }
        
        // Upload staged FAQs button
        if (e.target.id === 'uploadStagedFaqsButton') {
            e.preventDefault();
            const tenantId = e.target.getAttribute('data-tenant-id');
            if (tenantId) uploadStagedFaqs(tenantId);
        }
        
        // Run suite button
        if (e.target.id === 'runSuiteButton') {
            e.preventDefault();
            const tenantId = e.target.getAttribute('data-tenant-id');
            if (tenantId) runSuite(tenantId);
        }
        
        // Promote staged button
        if (e.target.id === 'promoteStagedButton') {
            e.preventDefault();
            const tenantId = e.target.getAttribute('data-tenant-id');
            if (tenantId) promoteStaged(tenantId);
        }
        
        // Rollback tenant button
        if (e.target.id === 'rollbackTenantButton') {
            e.preventDefault();
            const tenantId = e.target.getAttribute('data-tenant-id');
            if (tenantId) rollbackTenant(tenantId);
        }
        
        // Onboard remove domain button
        if (e.target.classList.contains('onboardRemoveDomainButton')) {
            e.preventDefault();
            const tenantId = e.target.getAttribute('data-tenant-id');
            const domain = e.target.getAttribute('data-domain');
            if (tenantId && domain) onboardRemoveDomain(tenantId, domain);
        }
    });
});

async function onboardUploadStaged() {
    const tenantId = document.getElementById('onboardTenantSelect').value;
    const faqsJson = document.getElementById('onboardFaqsJson').value.trim();
    
    if (!tenantId) {
        alert('Please select a tenant first');
        return;
    }
    if (!faqsJson) {
        alert('Please paste or upload FAQ JSON');
        return;
    }
    
    let faqs;
    try {
        faqs = JSON.parse(faqsJson);
    } catch (e) {
        alert(`Invalid JSON: ${e.message}`);
        return;
    }
    
    const statusEl = document.getElementById('onboardUploadStatus');
    statusEl.innerHTML = 'Uploading...';
    
    try {
        const res = await fetch(`${API_BASE}/admin/api/tenant/${tenantId}/faqs/staged`, {
            method: 'PUT',
            headers: getHeaders(),
            body: JSON.stringify(faqs)
        });
        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.detail || `HTTP ${res.status}`);
        }
        const result = await res.json();
        statusEl.innerHTML = `<span style="color: #28a745;">✓ Staged ${result.staged_count} FAQs</span>`;
    } catch (e) {
        statusEl.innerHTML = `<span style="color: #dc3545;">✗ Error: ${e.message}</span>`;
    }
}

async function onboardPromote() {
    const tenantId = document.getElementById('onboardTenantSelect').value;
    if (!tenantId) {
        alert('Please select a tenant first');
        return;
    }
    
    const btn = document.getElementById('onboardPromoteBtn');
    const statusEl = document.getElementById('onboardPromoteStatus');
    btn.disabled = true;
    btn.textContent = 'Promoting...';
    statusEl.innerHTML = 'Running suite and promoting...';
    
    try {
        const res = await fetch(`${API_BASE}/admin/api/tenant/${tenantId}/promote`, {
            method: 'POST',
            headers: getHeaders()
        });
        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.detail || `HTTP ${res.status}`);
        }
        const result = await res.json();
        
        if (result.status === 'success') {
            statusEl.innerHTML = `<span style="color: #28a745;">✓ Promoted successfully</span>`;
            if (result.suite_result) {
                const suite = result.suite_result;
                statusEl.innerHTML += `<br><small>Suite: ${suite.passed}/${suite.total} tests passed</small>`;
            }
        } else {
            statusEl.innerHTML = `<span style="color: #dc3545;">✗ Promote failed: ${result.message}</span>`;
            if (result.first_failure) {
                statusEl.innerHTML += `<br><small>First failure: ${result.first_failure.name}</small>`;
            }
        }
    } catch (e) {
        statusEl.innerHTML = `<span style="color: #dc3545;">✗ Error: ${e.message}</span>`;
    } finally {
        btn.disabled = false;
        btn.textContent = 'Promote to Live';
    }
}

async function onboardRunBenchmark() {
    const tenantId = document.getElementById('onboardTenantSelect').value;
    if (!tenantId) {
        alert('Please select a tenant first');
        return;
    }
    
    const btn = document.getElementById('onboardBenchmarkBtn');
    const statusEl = document.getElementById('onboardBenchmarkStatus');
    btn.disabled = true;
    btn.textContent = 'Running...';
    statusEl.innerHTML = 'Running benchmark...';
    
    try {
        const res = await fetch(`${API_BASE}/admin/api/tenant/${tenantId}/benchmark`, {
            method: 'POST',
            headers: getHeaders()
        });
        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.detail || `HTTP ${res.status}`);
        }
        const result = await res.json();
        
        let html = `<div style="background: ${result.gate_pass ? '#d4edda' : '#f8d7da'}; padding: 15px; border-radius: 4px;">`;
        html += `<strong>Results:</strong><br>`;
        html += `Hit rate: ${(result.hit_rate * 100).toFixed(1)}% (threshold: ${(result.thresholds.min_hit_rate * 100)}%)<br>`;
        html += `Fallback rate: ${(result.fallback_rate * 100).toFixed(1)}% (threshold: ${(result.thresholds.max_fallback_rate * 100)}%)<br>`;
        html += `Wrong hit rate: ${(result.wrong_hit_rate * 100).toFixed(1)}% (threshold: ${(result.thresholds.max_wrong_hit_rate * 100)}%)<br>`;
        html += `<strong>Gate: ${result.gate_pass ? 'PASS' : 'FAIL'}</strong><br>`;
        
        if (result.worst_misses && result.worst_misses.length > 0) {
            html += `<br><strong>Worst misses:</strong><ul>`;
            result.worst_misses.slice(0, 5).forEach(miss => {
                html += `<li>"${escapeHtml(miss.question)}" (score: ${miss.score?.toFixed(3) || 'n/a'})</li>`;
            });
            html += `</ul>`;
        }
        html += `</div>`;
        
        statusEl.innerHTML = html;
    } catch (e) {
        statusEl.innerHTML = `<span style="color: #dc3545;">✗ Error: ${e.message}</span>`;
    } finally {
        btn.disabled = false;
        btn.textContent = 'Run Benchmark';
    }
}

async function onboardSyncWorker() {
    const tenantId = document.getElementById('onboardTenantSelect').value;
    if (!tenantId) {
        alert('Please select a tenant first');
        return;
    }
    
    const btn = document.getElementById('onboardSyncBtn');
    const statusEl = document.getElementById('onboardSyncStatus');
    btn.disabled = true;
    btn.textContent = 'Syncing...';
    statusEl.innerHTML = 'Syncing domains to Worker D1...';
    
    try {
        const res = await fetch(`${API_BASE}/admin/api/tenant/${tenantId}/domains/sync-worker`, {
            method: 'POST',
            headers: getHeaders()
        });
        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.detail || `HTTP ${res.status}`);
        }
        const result = await res.json();
        
        if (result.synced) {
            statusEl.innerHTML = `<span style="color: #28a745;">✓ ${result.message}</span>`;
            if (result.synced_domains) {
                statusEl.innerHTML += `<br><small>Synced: ${result.synced_domains.join(', ')}</small>`;
            }
        } else {
            statusEl.innerHTML = `<span style="color: #ffc107;">⚠ ${result.message}</span>`;
        }
        if (result.errors && result.errors.length > 0) {
            statusEl.innerHTML += `<br><small style="color: #dc3545;">Errors: ${result.errors.map(e => e.domain).join(', ')}</small>`;
        }
    } catch (e) {
        statusEl.innerHTML = `<span style="color: #dc3545;">✗ Error: ${e.message}</span>`;
    } finally {
        btn.disabled = false;
        btn.textContent = 'Sync to Worker D1';
    }
}

async function onboardCheckReadiness() {
    const tenantId = document.getElementById('onboardTenantSelect').value;
    if (!tenantId) {
        alert('Please select a tenant first');
        return;
    }
    
    const statusEl = document.getElementById('onboardReadinessStatus');
    statusEl.innerHTML = 'Checking...';
    
    try {
        const res = await fetch(`${API_BASE}/admin/api/tenant/${tenantId}/readiness`, {
            headers: getHeaders()
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const result = await res.json();
        
        let html = `<div style="background: ${result.ready ? '#d4edda' : '#fff3cd'}; padding: 15px; border-radius: 4px;">`;
        html += `<strong>Ready: ${result.ready ? '✓ YES' : '✗ NO'}</strong><br><br>`;
        result.checks.forEach(check => {
            html += `${check.passed ? '✓' : '✗'} ${check.check}: ${check.message}<br>`;
        });
        html += `</div>`;
        
        statusEl.innerHTML = html;
        
        // Show install snippet if ready
        if (result.ready) {
            const snippetEl = document.getElementById('onboardInstallSnippet');
            const codeEl = document.getElementById('onboardSnippetCode');
            snippetEl.style.display = 'block';
            codeEl.textContent = `<script 
  src="https://mm-client1-creator-ui.pages.dev/widget.js"
  data-greeting="Hi! How can I help you today?"
  data-header="${tenantId}"
  data-color="#2563eb"
></script>`;
        }
    } catch (e) {
        statusEl.innerHTML = `<span style="color: #dc3545;">✗ Error: ${e.message}</span>`;
    }
}

async function copyOnboardSnippet() {
    const codeEl = document.getElementById('onboardSnippetCode');
    const successEl = document.getElementById('onboardCopySuccess');
    
    try {
        await navigator.clipboard.writeText(codeEl.textContent);
        successEl.style.display = 'block';
        setTimeout(() => {
            successEl.style.display = 'none';
        }, 2000);
    } catch (e) {
        alert('Failed to copy. Please select and copy manually.');
    }
}

