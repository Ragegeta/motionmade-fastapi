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
  var greeting = (script.getAttribute('data-greeting') || '').trim();
  if (!apiBase) apiBase = window.location.origin;
  if (!tenant) return;
  if (!greeting) greeting = 'Hi! I can help with common questions about ' + name + '. Ask me anything or tap a question below.';

  var isInline = (mode === 'inline');
  var root = document.createElement('div');
  root.id = 'mm-widget-root';
  root.setAttribute('data-motionmade', '1');
  if (isInline) {
    var container = document.getElementById('motionmade-widget');
    if (container) container.appendChild(root);
    else document.body.appendChild(root);
  } else {
    document.body.appendChild(root);
  }
  if (isInline) root.classList.add('mm-inline');

  function hexToRgb(hex) {
    var r = parseInt(hex.slice(1, 3), 16), g = parseInt(hex.slice(3, 5), 16), b = parseInt(hex.slice(5, 7), 16);
    return r + ',' + g + ',' + b;
  }
  var colorRgb = hexToRgb(color);

  var sheet = document.createElement('style');
  sheet.textContent = [
    '#mm-widget-root{--mm-color:' + color + ';--mm-color-rgb:' + colorRgb + ';font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Helvetica Neue",sans-serif;font-size:15px;line-height:1.5}',
    '#mm-widget-root *{box-sizing:border-box}',

    /* Float button */
    '#mm-widget-root .mm-btn{position:fixed;bottom:20px;right:20px;z-index:99998;width:56px;height:56px;border:none;border-radius:50%;cursor:pointer;background:var(--mm-color);color:#fff;box-shadow:0 4px 16px rgba(var(--mm-color-rgb),0.4);transition:transform 0.2s cubic-bezier(0.34,1.56,0.64,1),box-shadow 0.2s;display:flex;align-items:center;justify-content:center;padding:0}',
    '#mm-widget-root .mm-btn:hover{transform:scale(1.08);box-shadow:0 6px 24px rgba(var(--mm-color-rgb),0.5)}',
    '#mm-widget-root .mm-btn svg{width:26px;height:26px;fill:currentColor;transition:transform 0.3s}',
    '#mm-widget-root .mm-btn.mm-open svg{transform:rotate(90deg) scale(0.9)}',

    /* Panel */
    '#mm-widget-root .mm-panel{position:fixed;bottom:86px;right:20px;width:min(400px,calc(100vw - 32px));max-height:min(520px,calc(100vh - 110px));z-index:99997;background:#fff;border-radius:16px;box-shadow:0 12px 48px rgba(0,0,0,0.15),0 2px 8px rgba(0,0,0,0.08);display:flex;flex-direction:column;overflow:hidden;transform:translateY(16px) scale(0.96);opacity:0;pointer-events:none;transition:transform 0.35s cubic-bezier(0.34,1.56,0.64,1),opacity 0.25s ease}',
    '#mm-widget-root .mm-panel.mm-visible{transform:translateY(0) scale(1);opacity:1;pointer-events:auto}',

    /* Inline overrides */
    '#mm-widget-root.mm-inline .mm-panel{position:relative;bottom:auto;right:auto;width:100%;max-width:520px;max-height:none;overflow:visible;margin:0 auto;box-shadow:0 1px 4px rgba(0,0,0,0.08);border:1px solid #e5e7eb;transform:none;opacity:1;pointer-events:auto;border-radius:14px}',
    '#mm-widget-root.mm-inline .mm-body{overflow:visible;flex:none;max-height:none}',
    '#mm-widget-root.mm-inline .mm-hdr .mm-close{display:none}',

    /* Header */
    '#mm-widget-root .mm-hdr{padding:16px 18px;background:var(--mm-color);color:#fff;display:flex;justify-content:space-between;align-items:center;flex-shrink:0}',
    '#mm-widget-root .mm-hdr-info h3{margin:0;font-size:15px;font-weight:600;color:#fff;line-height:1.3}',
    '#mm-widget-root .mm-hdr-info .mm-sub{font-size:12px;opacity:0.75;margin-top:1px}',
    '#mm-widget-root .mm-close{background:none;border:none;cursor:pointer;color:rgba(255,255,255,0.7);font-size:22px;line-height:1;padding:4px;transition:color 0.15s}',
    '#mm-widget-root .mm-close:hover{color:#fff}',

    /* Body */
    '#mm-widget-root .mm-body{flex:1;overflow-y:auto;padding:20px 18px;display:flex;flex-direction:column;gap:14px;scrollbar-width:thin;scrollbar-color:#d1d5db transparent}',
    '#mm-widget-root .mm-body::-webkit-scrollbar{width:4px}',
    '#mm-widget-root .mm-body::-webkit-scrollbar-thumb{background:#d1d5db;border-radius:2px}',

    /* Greeting */
    '#mm-widget-root .mm-greeting{font-size:15px;color:#475569;line-height:1.6;animation:mm-fadeIn 0.3s ease both}',
    '@keyframes mm-fadeIn{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:translateY(0)}}',

    /* Quick replies */
    '#mm-widget-root .mm-quick-wrap{display:flex;flex-wrap:wrap;gap:10px}',
    '#mm-widget-root .mm-quick{padding:9px 16px;border-radius:20px;font-size:14px;cursor:pointer;background:#fff;color:var(--mm-color);border:1.5px solid rgba(var(--mm-color-rgb),0.3);font-family:inherit;transition:all 0.15s;line-height:1.35}',
    '#mm-widget-root .mm-quick:hover{background:rgba(var(--mm-color-rgb),0.08);border-color:var(--mm-color)}',

    /* Result area */
    '#mm-widget-root .mm-result{animation:mm-fadeIn 0.3s ease both}',
    '#mm-widget-root .mm-you-asked{font-size:12px;color:#94a3b8;margin-bottom:8px}',
    '#mm-widget-root .mm-you-asked q{font-style:normal;color:#475569;font-weight:500}',
    '#mm-widget-root .mm-answer{padding:16px 18px;background:#f3f4f6;border-radius:12px;font-size:16px;line-height:1.65;color:#1f2937;white-space:pre-wrap;word-break:break-word;border-left:3px solid var(--mm-color)}',
    '#mm-widget-root .mm-ask-again{margin-top:18px;padding:10px 18px;border-radius:8px;font-size:14px;cursor:pointer;background:none;color:var(--mm-color);border:1.5px solid rgba(var(--mm-color-rgb),0.3);font-family:inherit;transition:all 0.15s;font-weight:500}',
    '#mm-widget-root .mm-ask-again:hover{background:rgba(var(--mm-color-rgb),0.08);border-color:var(--mm-color)}',

    /* Typing indicator */
    '#mm-widget-root .mm-typing{display:flex;gap:4px;padding:12px 16px;background:#f3f4f6;border-radius:12px;align-self:flex-start;border-left:3px solid var(--mm-color)}',
    '#mm-widget-root .mm-typing span{width:7px;height:7px;background:#94a3b8;border-radius:50%;animation:mm-dot 1.4s ease-in-out infinite}',
    '#mm-widget-root .mm-typing span:nth-child(2){animation-delay:0.16s}',
    '#mm-widget-root .mm-typing span:nth-child(3){animation-delay:0.32s}',
    '@keyframes mm-dot{0%,60%,100%{transform:translateY(0);opacity:0.4}30%{transform:translateY(-6px);opacity:1}}',

    /* Input area */
    '#mm-widget-root .mm-input-area{padding:14px 18px;border-top:1px solid #f1f5f9;display:flex;gap:10px;align-items:center;flex-shrink:0}',
    '#mm-widget-root .mm-input{flex:1;height:48px;padding:13px 16px;font-size:15px;border:1.5px solid #e2e8f0;border-radius:24px;background:#f8fafc;color:#1f2937;outline:none;font-family:inherit;line-height:1.4;transition:border-color 0.15s,box-shadow 0.15s}',
    '#mm-widget-root .mm-input:focus{border-color:var(--mm-color);box-shadow:0 0 0 3px rgba(var(--mm-color-rgb),0.1);background:#fff}',
    '#mm-widget-root .mm-input::placeholder{color:#94a3b8}',
    '#mm-widget-root .mm-send{width:44px;height:44px;border:none;border-radius:50%;background:var(--mm-color);color:#fff;cursor:pointer;display:flex;align-items:center;justify-content:center;transition:transform 0.15s,opacity 0.15s;flex-shrink:0;padding:0}',
    '#mm-widget-root .mm-send:hover{transform:scale(1.06)}',
    '#mm-widget-root .mm-send:disabled{opacity:0.4;cursor:not-allowed;transform:none}',
    '#mm-widget-root .mm-send svg{width:18px;height:18px;fill:currentColor}',

    /* Footer */
    '#mm-widget-root .mm-foot{padding:6px 14px;text-align:center;font-size:10px;color:#b0b8c4;flex-shrink:0}',
    '#mm-widget-root .mm-foot a{color:#94a3b8;text-decoration:none}',
    '#mm-widget-root .mm-foot a:hover{color:#64748b;text-decoration:underline}',

    /* Mobile */
    '@media (max-width: 480px){' +
      '#mm-widget-root .mm-panel{bottom:0;right:0;left:0;width:100%;max-height:100vh;border-radius:0;max-height:calc(100vh - 60px)}' +
      '#mm-widget-root .mm-btn{bottom:12px;right:12px}' +
    '}',

    /* Error */
    '#mm-widget-root .mm-err{color:#dc2626;font-size:13px;padding:8px 14px;background:#fef2f2;border-radius:10px;border:1px solid #fecaca}'
  ].join('\n');
  root.appendChild(sheet);

  var open = false;
  var suggested = [];
  var apiLoadFailed = false;
  var bodyEl, inputEl, sendBtn;
  var hasGreeted = false;

  function escapeHtml(s) { var d = document.createElement('div'); d.textContent = s; return d.innerHTML; }
  function networkErrorMessage() {
    return phone ? ("Couldn't load right now. Call " + phone + " instead.") : "Couldn't load right now. Try again later.";
  }

  function resetToGreeting() {
    bodyEl.innerHTML = '';
    var greet = document.createElement('div');
    greet.className = 'mm-greeting';
    greet.textContent = greeting;
    bodyEl.appendChild(greet);
    if (suggested.length > 0) {
      var wrap = document.createElement('div');
      wrap.className = 'mm-quick-wrap';
      suggested.slice(0, 4).forEach(function (q) {
        var btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'mm-quick';
        btn.textContent = q;
        btn.onclick = function () { askQuestion(q); };
        wrap.appendChild(btn);
      });
      bodyEl.appendChild(wrap);
    }
    if (inputEl) { inputEl.value = ''; inputEl.disabled = false; }
    if (sendBtn) sendBtn.disabled = false;
  }

  function showGreeting() {
    if (hasGreeted) return;
    hasGreeted = true;
    resetToGreeting();
  }

  function askQuestion(text) {
    bodyEl.innerHTML = '';
    if (inputEl) { inputEl.value = ''; inputEl.disabled = true; }
    if (sendBtn) sendBtn.disabled = true;

    var youAsked = document.createElement('div');
    youAsked.className = 'mm-you-asked';
    youAsked.innerHTML = 'You asked: <q>' + escapeHtml(text) + '</q>';
    bodyEl.appendChild(youAsked);

    var typing = document.createElement('div');
    typing.className = 'mm-typing';
    typing.innerHTML = '<span></span><span></span><span></span>';
    bodyEl.appendChild(typing);

    var xhr = new XMLHttpRequest();
    xhr.open('POST', apiBase + '/api/v2/generate-quote-reply', true);
    xhr.setRequestHeader('Content-Type', 'application/json');
    xhr.onload = function () {
      typing.remove();
      if (inputEl) inputEl.disabled = false;
      if (sendBtn) sendBtn.disabled = false;

      var result = document.createElement('div');
      result.className = 'mm-result';

      if (xhr.status === 200) {
        try {
          var data = JSON.parse(xhr.responseText);
          var ans = (data.replyText || '').trim();
          if (ans) {
            var ansEl = document.createElement('div');
            ansEl.className = 'mm-answer';
            ansEl.textContent = ans;
            result.appendChild(ansEl);
          } else {
            var errEl = document.createElement('div');
            errEl.className = 'mm-err';
            errEl.textContent = 'Sorry, I couldn\'t find an answer. Please call ' + (phone || 'the business') + ' directly.';
            result.appendChild(errEl);
          }
        } catch (e) {
          var errEl2 = document.createElement('div');
          errEl2.className = 'mm-err';
          errEl2.textContent = 'Something went wrong. Please try again.';
          result.appendChild(errEl2);
        }
      } else {
        var errEl3 = document.createElement('div');
        errEl3.className = 'mm-err';
        errEl3.textContent = networkErrorMessage();
        result.appendChild(errEl3);
      }

      var againBtn = document.createElement('button');
      againBtn.type = 'button';
      againBtn.className = 'mm-ask-again';
      againBtn.textContent = 'Ask another question';
      againBtn.onclick = function () { resetToGreeting(); if (inputEl) inputEl.focus(); };
      result.appendChild(againBtn);

      bodyEl.appendChild(result);
      if (inputEl) inputEl.focus();
    };
    xhr.onerror = function () {
      typing.remove();
      if (inputEl) inputEl.disabled = false;
      if (sendBtn) sendBtn.disabled = false;
      var result = document.createElement('div');
      result.className = 'mm-result';
      var errEl = document.createElement('div');
      errEl.className = 'mm-err';
      errEl.textContent = networkErrorMessage();
      result.appendChild(errEl);
      var againBtn = document.createElement('button');
      againBtn.type = 'button';
      againBtn.className = 'mm-ask-again';
      againBtn.textContent = 'Ask another question';
      againBtn.onclick = function () { resetToGreeting(); if (inputEl) inputEl.focus(); };
      result.appendChild(againBtn);
      bodyEl.appendChild(result);
    };
    xhr.send(JSON.stringify({ tenantId: tenant, customerMessage: text }));
  }

  function renderButton() {
    var btn = document.createElement('button');
    btn.className = 'mm-btn';
    btn.type = 'button';
    btn.setAttribute('aria-label', 'Got a question?');
    btn.innerHTML = '<svg viewBox="0 0 24 24"><path d="M20 2H4c-1.1 0-2 .9-2 2v18l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2zm0 14H5.17L4 17.17V4h16v12z"/><path d="M7 9h2v2H7zm4 0h2v2h-2zm4 0h2v2h-2z"/></svg>';
    btn.onclick = function () {
      open = !open;
      panel.classList.toggle('mm-visible', open);
      btn.classList.toggle('mm-open', open);
      if (open) {
        if (suggested.length === 0 && !apiLoadFailed) fetchSuggested();
        else showGreeting();
        if (inputEl) inputEl.focus();
      }
    };
    root.appendChild(btn);
    return btn;
  }

  function renderPanel() {
    var panel = document.createElement('div');
    panel.className = 'mm-panel' + (isInline ? ' mm-visible' : '');

    var hdr = document.createElement('div');
    hdr.className = 'mm-hdr';
    hdr.innerHTML = '<div class="mm-hdr-info"><h3>' + escapeHtml(name) + '</h3><div class="mm-sub">Get instant answers</div></div>';
    var closeBtn = document.createElement('button');
    closeBtn.type = 'button';
    closeBtn.className = 'mm-close';
    closeBtn.setAttribute('aria-label', 'Close');
    closeBtn.innerHTML = '&times;';
    closeBtn.onclick = function () {
      open = false;
      panel.classList.remove('mm-visible');
      var floatBtn = root.querySelector('.mm-btn');
      if (floatBtn) floatBtn.classList.remove('mm-open');
    };
    hdr.appendChild(closeBtn);
    panel.appendChild(hdr);

    bodyEl = document.createElement('div');
    bodyEl.className = 'mm-body';
    panel.appendChild(bodyEl);

    var inputArea = document.createElement('div');
    inputArea.className = 'mm-input-area';
    inputEl = document.createElement('input');
    inputEl.type = 'text';
    inputEl.className = 'mm-input';
    inputEl.placeholder = 'Ask a question...';
    inputEl.setAttribute('aria-label', 'Ask a question');
    inputEl.onkeydown = function (e) {
      if (e.key === 'Enter') {
        e.preventDefault();
        doSend();
      }
    };
    sendBtn = document.createElement('button');
    sendBtn.type = 'button';
    sendBtn.className = 'mm-send';
    sendBtn.setAttribute('aria-label', 'Send');
    sendBtn.innerHTML = '<svg viewBox="0 0 24 24"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/></svg>';
    sendBtn.onclick = doSend;
    inputArea.appendChild(inputEl);
    inputArea.appendChild(sendBtn);
    panel.appendChild(inputArea);

    var foot = document.createElement('div');
    foot.className = 'mm-foot';
    foot.innerHTML = '<a href="https://motionmadebne.com.au" target="_blank" rel="noopener">Powered by MotionMade</a>';
    panel.appendChild(foot);

    root.appendChild(panel);
    return panel;
  }

  function doSend() {
    var text = (inputEl.value || '').trim();
    if (!text) return;
    askQuestion(text);
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
        showGreeting();
      })
      .catch(function () {
        suggested = [];
        apiLoadFailed = true;
        showGreeting();
      });
  }

  var floatBtn = null;
  if (!isInline) floatBtn = renderButton();
  var panel = renderPanel();
  if (isInline) {
    open = true;
    fetchSuggested();
  }
})();
