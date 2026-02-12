(function () {
  'use strict';
  var script = document.currentScript;
  if (!script) return;
  var tenant = (script.getAttribute('data-tenant') || '').trim();
  var color = (script.getAttribute('data-color') || '#2563EB').trim();
  var name = (script.getAttribute('data-name') || 'this business').trim();
  var phone = (script.getAttribute('data-phone') || '').trim();
  var apiBase = (script.getAttribute('data-api') || '').trim().replace(/\/$/, '');
  if (!apiBase) apiBase = window.location.origin;
  if (!tenant) return;

  var root = document.createElement('div');
  root.id = 'mm-widget-root';
  root.setAttribute('data-motionmade', '1');
  document.body.appendChild(root);

  var sheet = document.createElement('style');
  sheet.textContent = [
    '#mm-widget-root *{box-sizing:border-box}',
    '#mm-widget-root .mm-btn{position:fixed;bottom:20px;right:20px;z-index:99998;padding:12px 20px;border:none;border-radius:999px;font-size:15px;font-weight:500;cursor:pointer;box-shadow:0 4px 12px rgba(0,0,0,0.15);transition:transform .15s,box-shadow .15s}',
    '#mm-widget-root .mm-btn:hover{transform:translateY(-1px);box-shadow:0 6px 16px rgba(0,0,0,0.2)}',
    '#mm-widget-root .mm-panel{position:fixed;bottom:80px;right:20px;width:min(380px,calc(100vw - 40px));max-height:min(420px,calc(100vh - 120px));z-index:99997;background:#fff;border-radius:12px;box-shadow:0 8px 32px rgba(0,0,0,0.12);display:flex;flex-direction:column;overflow:hidden;font-family:-apple-system,BlinkMacSystemFont,\'Segoe UI\',Roboto,sans-serif;font-size:15px}',
    '#mm-widget-root .mm-panel-hdr{padding:14px 16px;background:#f9fafb;border-bottom:1px solid #e5e7eb;display:flex;justify-content:space-between;align-items:center}',
    '#mm-widget-root .mm-panel-hdr h3{margin:0;font-size:16px;font-weight:600;color:#111827}',
    '#mm-widget-root .mm-panel-hdr .mm-sub{font-size:12px;color:#6b7280;margin-top:2px}',
    '#mm-widget-root .mm-panel-close{background:none;border:none;cursor:pointer;padding:4px;color:#6b7280;font-size:20px;line-height:1}',
    '#mm-widget-root .mm-panel-body{flex:1;overflow-y:auto;padding:16px}',
    '#mm-widget-root .mm-suggest{font-size:13px;color:#6b7280;margin-bottom:10px}',
    '#mm-widget-root .mm-qlist{list-style:none;margin:0 0 16px;padding:0}',
    '#mm-widget-root .mm-qlist li{margin:0 0 6px;padding:10px 12px;background:#f3f4f6;border-radius:8px;cursor:pointer;font-size:14px;color:#111827;border:1px solid transparent}',
    '#mm-widget-root .mm-qlist li:hover{background:#e5e7eb}',
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
  var currentQuestion = '';
  var currentAnswer = '';

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
    panel.style.display = 'none';

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
    var xhr = new XMLHttpRequest();
    xhr.open('GET', apiBase + '/api/v2/tenant/' + encodeURIComponent(tenant) + '/suggested-questions', true);
    xhr.onload = function () {
      if (xhr.status === 200) {
        try {
          var data = JSON.parse(xhr.responseText);
          suggested = data.questions || [];
        } catch (e) { suggested = []; }
      }
      renderMain();
    };
    xhr.onerror = function () { suggested = []; renderMain(); };
    xhr.send();
  }

  function renderMain() {
    var body = panelBody;
    body.innerHTML = '';
    state = 'main';
    currentQuestion = '';
    currentAnswer = '';

    body.innerHTML += '<div class="mm-suggest">Common questions:</div>';
    var ul = document.createElement('ul');
    ul.className = 'mm-qlist';
    suggested.forEach(function (q) {
      var li = document.createElement('li');
      li.textContent = q;
      li.onclick = function () { ask(q); };
      ul.appendChild(li);
    });
    body.appendChild(ul);
    body.innerHTML += '<div class="mm-or">Or ask your own:</div>';
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
        err = phone ? 'Answers are temporarily unavailable. Call ' + phone + ' directly.' : 'Answers are temporarily unavailable. Try again later.';
      }
      var block = panelBody.querySelector('.mm-answer-block');
      if (block) {
        if (err) block.innerHTML = '<div class="mm-err">' + escapeHtml(err) + '</div>';
        else block.innerHTML = '<div class="mm-ans-box">' + escapeHtml(ans) + '</div>';
      }
    };
    xhr.onerror = function () {
      var block = panelBody.querySelector('.mm-answer-block');
      if (block) block.innerHTML = '<div class="mm-err">' + (phone ? 'Answers are temporarily unavailable. Call ' + escapeHtml(phone) + ' directly.' : 'Answers are temporarily unavailable. Try again later.') + '</div>';
    };
    xhr.send(JSON.stringify({ tenantId: tenant, customerMessage: questionText }));
  }

  renderButton();
  var out = renderPanel();
  var panel = out.panel;
  var panelBody = out.body;
})();
