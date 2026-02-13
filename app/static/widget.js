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
    '#mm-widget-root.mm-inline .mm-panel{position:relative;bottom:auto;right:auto;width:100%;max-width:500px;max-height:none;margin:0 auto;box-shadow:0 1px 3px rgba(0,0,0,0.1);border:1px solid #e5e7eb}',
    '#mm-widget-root.mm-inline .mm-panel-hdr .mm-panel-close{display:none}',
    '#mm-widget-root .mm-panel-hdr{padding:14px 16px;background:#f9fafb;border-bottom:1px solid #e5e7eb;display:flex;justify-content:space-between;align-items:center}',
    '#mm-widget-root .mm-panel-hdr h3{margin:0;font-size:16px;font-weight:600;color:#111827}',
    '#mm-widget-root .mm-panel-hdr .mm-sub{font-size:12px;color:#6b7280;margin-top:2px}',
    '#mm-widget-root .mm-panel-close{background:none;border:none;cursor:pointer;padding:4px;color:#6b7280;font-size:20px;line-height:1}',
    '#mm-widget-root .mm-panel-body{flex:1;overflow-y:auto;padding:16px}',
    '#mm-widget-root .mm-suggest{font-size:13px;color:#6b7280;margin-bottom:10px}',
    '#mm-widget-root .mm-select-wrap{margin-bottom:16px}',
    '#mm-widget-root .mm-select{width:100%;min-height:44px;padding:10px 12px;font-size:16px;border:1px solid #d1d5db;border-radius:8px;background:#fff;color:#111827;cursor:pointer;-webkit-appearance:none;appearance:none;background-image:url("data:image/svg+xml,%3Csvg xmlns=\'http://www.w3.org/2000/svg\' width=\'12\' height=\'12\' viewBox=\'0 0 12 12\'%3E%3Cpath fill=\'%236b7280\' d=\'M6 8L1 3h10z\'/%3E%3C/svg%3E");background-repeat:no-repeat;background-position:right 12px center;padding-right:36px}',
    '#mm-widget-root .mm-select option{font-size:16px}',
    '#mm-widget-root .mm-or{font-size:13px;color:#6b7280;margin:12px 0 8px}',
    '#mm-widget-root .mm-inrow{display:flex;gap:8px;margin-top:8px}',
    '#mm-widget-root .mm-inrow input{flex:1;padding:10px 12px;border:1px solid #d1d5db;border-radius:8px;font-size:14px}',
    '#mm-widget-root .mm-inrow button{padding:10px 16px;background:#2563EB;color:#fff;border:none;border-radius:8px;font-weight:500;cursor:pointer;font-size:14px}',
    '#mm-widget-root .mm-foot{padding:10px 16px;border-top:1px solid #e5e7eb;text-align:center;font-size:11px;color:#9ca3af}',
    '#mm-widget-root .mm-answer-block{margin-top:12px}',
    '#mm-widget-root .mm-your-q{font-size:13px;color:#6b7280;margin-bottom:6px}',
    '#mm-widget-root .mm-your-q q{font-style:normal;color:#374151}',
    '#mm-widget-root .mm-ans-box{padding:12px;background:#f0f9ff;border:1px solid #bae6fd;border-radius:8px;font-size:14px;color:#0c4a6e;white-space:pre-wrap}',
    '#mm-widget-root .mm-spinner{height:24px;width:24px;border:3px solid #e5e7eb;border-top-color:#2563EB;border-radius:50%;animation:mm-spin .6s linear infinite}',
    '@keyframes mm-spin{to{transform:rotate(360deg)}}',
    '#mm-widget-root .mm-again{margin-top:14px}',
    '#mm-widget-root .mm-again button{padding:8px 14px;background:#f3f4f6;color:#374151;border:1px solid #e5e7eb;border-radius:6px;cursor:pointer;font-size:14px}',
    '#mm-widget-root .mm-again button:hover{background:#e5e7eb}',
    '#mm-widget-root .mm-err{color:#dc2626;font-size:14px}'
  ].join('\n');
  root.appendChild(sheet);

  var open = false;
  var state = 'main'; // 'main' | 'answer'
  var suggested = [];
  var apiLoadFailed = false;
  var currentQuestion = '';
  var currentAnswer = '';

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
      if (open && state === 'main' && suggested.length === 0) fetchSuggested();
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
    state = 'main';
    currentQuestion = '';
    currentAnswer = '';

    if (apiLoadFailed && suggested.length === 0) {
      body.appendChild((function () {
        var d = document.createElement('div');
        d.className = 'mm-err';
        d.style.marginBottom = '12px';
        d.textContent = networkErrorMessage();
        return d;
      })());
    }
    var selectWrap = document.createElement('div');
    selectWrap.className = 'mm-select-wrap';
    var selectEl = document.createElement('select');
    selectEl.className = 'mm-select';
    selectEl.setAttribute('aria-label', 'Select a common question');
    var placeholder = document.createElement('option');
    placeholder.value = '';
    placeholder.textContent = 'Select a common question...';
    placeholder.disabled = true;
    placeholder.selected = true;
    selectEl.appendChild(placeholder);
    suggested.forEach(function (q) {
      var opt = document.createElement('option');
      opt.value = q;
      opt.textContent = q;
      selectEl.appendChild(opt);
    });
    selectEl.onchange = function () {
      var v = (selectEl.value || '').trim();
      if (v) {
        ask(v);
        selectEl.value = '';
        selectEl.selectedIndex = 0;
      }
    };
    selectWrap.appendChild(selectEl);
    body.appendChild(selectWrap);
    var orLabel = document.createElement('div');
    orLabel.className = 'mm-or';
    orLabel.textContent = 'Or ask your own:';
    body.appendChild(orLabel);
    var row = document.createElement('div');
    row.className = 'mm-inrow';
    var input = document.createElement('input');
    input.type = 'text';
    input.placeholder = 'Type your question...';
    input.setAttribute('aria-label', 'Your question');
    var askBtn = document.createElement('button');
    askBtn.type = 'button';
    askBtn.textContent = 'Ask';
    askBtn.onclick = function () {
      var t = input.value.trim();
      if (t) ask(t);
    };
    input.onkeydown = function (e) {
      if (e.key === 'Enter') { e.preventDefault(); askBtn.click(); }
    };
    row.appendChild(input);
    row.appendChild(askBtn);
    body.appendChild(row);
  }

  function ask(questionText) {
    currentQuestion = questionText;
    state = 'answer';
    panelBody.innerHTML = '<div class="mm-your-q">Your question:</div><q>' + escapeHtml(questionText) + '</q><div class="mm-answer-block" style="margin-top:12px"><div class="mm-spinner"></div></div><div class="mm-again" style="margin-top:14px"><button type="button">Ask another question</button></div>';
    panelBody.querySelector('.mm-again button').onclick = renderMain;

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
      var block = panelBody.querySelector('.mm-answer-block');
      if (block) {
        if (err) block.innerHTML = '<div class="mm-err">' + escapeHtml(err) + '</div>';
        else block.innerHTML = '<div class="mm-ans-box">' + escapeHtml(ans) + '</div>';
      }
    };
    xhr.onerror = function () {
      var block = panelBody.querySelector('.mm-answer-block');
      if (block) block.innerHTML = '<div class="mm-err">' + escapeHtml(networkErrorMessage()) + '</div>';
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
