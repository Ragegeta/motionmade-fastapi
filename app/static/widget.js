(function () {
  'use strict';
  var script = document.currentScript;
  if (!script) return;
  var tenant = (script.getAttribute('data-tenant') || '').trim();
  var color = (script.getAttribute('data-color') || '#2563EB').trim();
  var name = (script.getAttribute('data-name') || 'this business').trim();
  var phone = (script.getAttribute('data-phone') || '').trim();
  var apiBase = (script.getAttribute('data-api') || '').trim().replace(/\/$/, '');
  var mode = (script.getAttribute('data-mode') || 'float').trim().toLowerCase();
  if (!apiBase) apiBase = window.location.origin;
  if (!tenant) return;

  var isInline = (mode === 'inline');
  var root = document.createElement('div');
  root.id = 'mm-widget-root';
  root.setAttribute('data-motionmade', '1');
  if (isInline) {
    var container = document.getElementById('motionmade-widget');
    if (container) {
      container.appendChild(root);
    } else {
      document.body.appendChild(root);
    }
  } else {
    document.body.appendChild(root);
  }
  if (isInline) root.classList.add('mm-inline');

  var sheet = document.createElement('style');
  sheet.textContent = [
    '#mm-widget-root *{box-sizing:border-box}',
    '#mm-widget-root .mm-btn{position:fixed;bottom:20px;right:20px;z-index:99998;padding:12px 20px;border:none;border-radius:999px;font-size:15px;font-weight:500;cursor:pointer;box-shadow:0 4px 12px rgba(0,0,0,0.15);transition:transform .15s,box-shadow .15s}',
    '#mm-widget-root .mm-btn:hover{transform:translateY(-1px);box-shadow:0 6px 16px rgba(0,0,0,0.2)}',
    '#mm-widget-root .mm-panel{position:fixed;bottom:80px;right:20px;width:min(380px,calc(100vw - 40px));max-height:min(420px,calc(100vh - 120px));z-index:99997;background:#fff;border-radius:12px;box-shadow:0 8px 32px rgba(0,0,0,0.12);display:flex;flex-direction:column;overflow:hidden;font-family:-apple-system,BlinkMacSystemFont,\'Segoe UI\',Roboto,sans-serif;font-size:15px}',
    '#mm-widget-root.mm-inline .mm-panel{position:relative;bottom:auto;right:auto;width:100%;max-width:500px;max-height:none;overflow:visible;margin:0 auto;box-shadow:0 1px 3px rgba(0,0,0,0.1);border:1px solid #e5e7eb}',
    '#mm-widget-root.mm-inline .mm-panel-body{overflow:visible;flex:none}',
    '#mm-widget-root.mm-inline .mm-panel-hdr .mm-panel-close{display:none}',
    '#mm-widget-root.mm-inline .mm-panel-hdr>div{text-align:left}',
    '#mm-widget-root.mm-inline .mm-foot{font-size:10px;color:#b0b8c4}',
    '#mm-widget-root .mm-panel-hdr{padding:14px 16px;background:#f9fafb;border-bottom:1px solid #e5e7eb;display:flex;justify-content:space-between;align-items:center}',
    '#mm-widget-root .mm-panel-hdr h3{margin:0;font-size:16px;font-weight:600;color:#111827}',
    '#mm-widget-root .mm-panel-hdr .mm-sub{font-size:12px;color:#6b7280;margin-top:2px}',
    '#mm-widget-root .mm-panel-close{background:none;border:none;cursor:pointer;padding:4px;color:#6b7280;font-size:20px;line-height:1}',
    '#mm-widget-root .mm-panel-body{flex:1;overflow-y:auto;padding:16px}',
    '#mm-widget-root .mm-inrow{display:flex;gap:8px;align-items:stretch;margin-top:0}',
    '#mm-widget-root .mm-input-wrap{position:relative;flex:1;min-width:0}',
    '#mm-widget-root .mm-input{width:100%;min-height:44px;padding:10px 40px 10px 12px;font-size:16px;border:1px solid #d1d5db;border-radius:8px;background:#fff;color:#111827}',
    '#mm-widget-root .mm-input-arrow{position:absolute;right:12px;top:50%;transform:translateY(-50%);cursor:pointer;color:#6b7280;font-size:12px;pointer-events:auto;user-select:none}',
    '#mm-widget-root .mm-input-arrow:hover{color:#111827}',
    '#mm-widget-root .mm-dropdown{position:absolute;left:0;right:0;top:100%;margin-top:4px;background:#fff;border:1px solid #e5e7eb;border-radius:8px;box-shadow:0 4px 12px rgba(0,0,0,0.1);max-height:220px;overflow-y:auto;z-index:10;display:none}',
    '#mm-widget-root .mm-dropdown.open{display:block}',
    '#mm-widget-root .mm-dropdown-item{padding:10px 12px;font-size:14px;color:#111827;cursor:pointer;border-bottom:1px solid #f3f4f6}',
    '#mm-widget-root .mm-dropdown-item:last-child{border-bottom:none}',
    '#mm-widget-root .mm-dropdown-item:hover{background:#f3f4f6}',
    '#mm-widget-root .mm-ask-btn{padding:10px 20px;min-height:44px;background:#2563EB;color:#fff;border:none;border-radius:8px;font-weight:500;cursor:pointer;font-size:15px}',
    '#mm-widget-root .mm-foot{padding:10px 16px;border-top:1px solid #e5e7eb;text-align:center;font-size:11px;color:#9ca3af}',
    '#mm-widget-root .mm-answer-slot{margin-top:14px;min-height:0}',
    '#mm-widget-root .mm-loading{font-size:14px;color:#6b7280}',
    '#mm-widget-root .mm-ans-box{padding:12px;background:#f0f9ff;border:1px solid #bae6fd;border-radius:8px;font-size:14px;color:#0c4a6e;white-space:pre-wrap}',
    '#mm-widget-root .mm-spinner{height:24px;width:24px;border:3px solid #e5e7eb;border-top-color:#2563EB;border-radius:50%;animation:mm-spin .6s linear infinite}',
    '@keyframes mm-spin{to{transform:rotate(360deg)}}',
    '#mm-widget-root .mm-err{color:#dc2626;font-size:14px}'
  ].join('\n');
  root.appendChild(sheet);

  var open = false;
  var suggested = [];
  var apiLoadFailed = false;

  function networkErrorMessage() {
    return phone ? ("Couldn't load right now. Call " + phone + " instead.") : "Couldn't load right now. Try again later.";
  }

  function get(id) { return root.querySelector(id); }
  function all(sel) { return root.querySelectorAll(sel); }

  function renderButton() {
    var btn = document.createElement('button');
    btn.className = 'mm-btn';
    btn.type = 'button';
    btn.textContent = 'Got a question?';
    btn.style.background = color;
    btn.style.color = '#fff';
    btn.onclick = function () {
      open = !open;
      panel.style.display = open ? 'flex' : 'none';
      if (open && suggested.length === 0) fetchSuggested();
    };
    root.appendChild(btn);
  }

  function renderPanel() {
    var panel = document.createElement('div');
    panel.className = 'mm-panel';
    panel.style.display = isInline ? 'flex' : 'none';

    var hdr = document.createElement('div');
    hdr.className = 'mm-panel-hdr';
    hdr.innerHTML = '<div><h3>' + escapeHtml(name) + '</h3><div class="mm-sub">Get instant answers</div></div>';
    var closeBtn = document.createElement('button');
    closeBtn.type = 'button';
    closeBtn.className = 'mm-panel-close';
    closeBtn.setAttribute('aria-label', 'Close');
    closeBtn.textContent = '\u00D7';
    closeBtn.onclick = function () { open = false; panel.style.display = 'none'; };
    hdr.appendChild(closeBtn);
    panel.appendChild(hdr);

    var body = document.createElement('div');
    body.className = 'mm-panel-body';
    panel.appendChild(body);

    var foot = document.createElement('div');
    foot.className = 'mm-foot';
    foot.textContent = 'Powered by MotionMade';
    panel.appendChild(foot);

    root.appendChild(panel);
    return { panel: panel, body: body };
  }

  function escapeHtml(s) {
    var d = document.createElement('div');
    d.textContent = s;
    return d.innerHTML;
  }

  function fetchSuggested() {
    var url = apiBase + '/api/v2/tenant/' + encodeURIComponent(tenant) + '/suggested-questions';
    fetch(url, { method: 'GET', mode: 'cors', credentials: 'omit' })
      .then(function (res) {
        if (res.ok) return res.json();
        apiLoadFailed = true;
        return { questions: [] };
      })
      .then(function (data) {
        suggested = (data && Array.isArray(data.questions)) ? data.questions : [];
        renderMain();
      })
      .catch(function () {
        suggested = [];
        apiLoadFailed = true;
        renderMain();
      });
  }

  function renderMain() {
    var body = panelBody;
    body.innerHTML = '';

    if (apiLoadFailed && suggested.length === 0) {
      body.appendChild((function () {
        var d = document.createElement('div');
        d.className = 'mm-err';
        d.style.marginBottom = '12px';
        d.textContent = networkErrorMessage();
        return d;
      })());
    }
    var row = document.createElement('div');
    row.className = 'mm-inrow';
    var wrap = document.createElement('div');
    wrap.className = 'mm-input-wrap';
    var input = document.createElement('input');
    input.type = 'text';
    input.className = 'mm-input';
    input.placeholder = 'Ask a question...';
    input.setAttribute('aria-label', 'Ask a question');
    var arrow = document.createElement('span');
    arrow.className = 'mm-input-arrow';
    arrow.setAttribute('aria-label', 'Common questions');
    arrow.textContent = '\u25BC';
    var dropdown = document.createElement('div');
    dropdown.className = 'mm-dropdown';
    dropdown.setAttribute('role', 'listbox');
    suggested.forEach(function (q) {
      var item = document.createElement('div');
      item.className = 'mm-dropdown-item';
      item.textContent = q;
      item.setAttribute('role', 'option');
      item.onclick = function () {
        input.value = q;
        dropdown.classList.remove('open');
        ask(input, q);
      };
      dropdown.appendChild(item);
    });
    arrow.onclick = function (e) {
      e.preventDefault();
      e.stopPropagation();
      var open = dropdown.classList.toggle('open');
      if (open) {
        setTimeout(function () {
          document.addEventListener('click', function closeHandler(ev) {
            if (!wrap.contains(ev.target)) {
              dropdown.classList.remove('open');
              document.removeEventListener('click', closeHandler);
            }
          });
        }, 0);
      }
    };
    var askBtn = document.createElement('button');
    askBtn.type = 'button';
    askBtn.className = 'mm-ask-btn';
    askBtn.textContent = 'Ask';
    askBtn.onclick = function () {
      var t = input.value.trim();
      if (t) ask(input, t);
    };
    input.onkeydown = function (e) {
      if (e.key === 'Enter') {
        e.preventDefault();
        askBtn.click();
      }
    };
    wrap.appendChild(input);
    wrap.appendChild(arrow);
    wrap.appendChild(dropdown);
    row.appendChild(wrap);
    row.appendChild(askBtn);
    body.appendChild(row);
    var answerSlot = document.createElement('div');
    answerSlot.className = 'mm-answer-slot';
    body.appendChild(answerSlot);
  }

  function ask(inputEl, questionText) {
    inputEl.value = '';
    var slot = panelBody.querySelector('.mm-answer-slot');
    if (!slot) return;
    slot.innerHTML = '<div class="mm-loading">Getting answer...</div>';
    var xhr = new XMLHttpRequest();
    xhr.open('POST', apiBase + '/api/v2/generate-quote-reply', true);
    xhr.setRequestHeader('Content-Type', 'application/json');
    xhr.onload = function () {
      var ans = '';
      var err = '';
      if (xhr.status === 200) {
        try {
          var data = JSON.parse(xhr.responseText);
          ans = (data.replyText || '').trim();
        } catch (e) { err = 'Invalid response.'; }
      } else {
        err = networkErrorMessage();
      }
      if (slot.parentNode) {
        if (err) slot.innerHTML = '<div class="mm-err">' + escapeHtml(err) + '</div>';
        else slot.innerHTML = '<div class="mm-ans-box">' + escapeHtml(ans) + '</div>';
      }
    };
    xhr.onerror = function () {
      if (slot.parentNode) slot.innerHTML = '<div class="mm-err">' + escapeHtml(networkErrorMessage()) + '</div>';
    };
    xhr.send(JSON.stringify({ tenantId: tenant, customerMessage: questionText }));
  }

  if (!isInline) renderButton();
  var out = renderPanel();
  var panel = out.panel;
  var panelBody = out.body;
  if (isInline) {
    open = true;
    fetchSuggested();
  }
})();
