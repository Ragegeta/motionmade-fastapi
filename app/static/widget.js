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
    '#mm-widget-root .mm-panel{position:fixed;bottom:86px;right:20px;width:min(380px,calc(100vw - 32px));max-height:min(520px,calc(100vh - 110px));z-index:99997;background:#fff;border-radius:16px;box-shadow:0 12px 48px rgba(0,0,0,0.15),0 2px 8px rgba(0,0,0,0.08);display:flex;flex-direction:column;overflow:hidden;transform:translateY(16px) scale(0.96);opacity:0;pointer-events:none;transition:transform 0.35s cubic-bezier(0.34,1.56,0.64,1),opacity 0.25s ease}',
    '#mm-widget-root .mm-panel.mm-visible{transform:translateY(0) scale(1);opacity:1;pointer-events:auto}',

    /* Inline overrides */
    '#mm-widget-root.mm-inline .mm-panel{position:relative;bottom:auto;right:auto;width:100%;max-width:520px;max-height:none;overflow:visible;margin:0 auto;box-shadow:0 1px 4px rgba(0,0,0,0.08);border:1px solid #e5e7eb;transform:none;opacity:1;pointer-events:auto;border-radius:14px}',
    '#mm-widget-root.mm-inline .mm-chat{overflow:visible;flex:none;max-height:none}',
    '#mm-widget-root.mm-inline .mm-hdr .mm-close{display:none}',

    /* Header */
    '#mm-widget-root .mm-hdr{padding:16px 18px;background:var(--mm-color);color:#fff;display:flex;justify-content:space-between;align-items:center;flex-shrink:0}',
    '#mm-widget-root .mm-hdr-info h3{margin:0;font-size:15px;font-weight:600;color:#fff;line-height:1.3}',
    '#mm-widget-root .mm-hdr-info .mm-sub{font-size:12px;opacity:0.75;margin-top:1px}',
    '#mm-widget-root .mm-close{background:none;border:none;cursor:pointer;color:rgba(255,255,255,0.7);font-size:22px;line-height:1;padding:4px;transition:color 0.15s}',
    '#mm-widget-root .mm-close:hover{color:#fff}',

    /* Chat area */
    '#mm-widget-root .mm-chat{flex:1;overflow-y:auto;padding:16px 14px;display:flex;flex-direction:column;gap:10px;scrollbar-width:thin;scrollbar-color:#d1d5db transparent}',
    '#mm-widget-root .mm-chat::-webkit-scrollbar{width:4px}',
    '#mm-widget-root .mm-chat::-webkit-scrollbar-thumb{background:#d1d5db;border-radius:2px}',

    /* Messages */
    '#mm-widget-root .mm-msg{max-width:85%;padding:10px 14px;border-radius:14px;font-size:14px;line-height:1.55;white-space:pre-wrap;word-break:break-word;animation:mm-msgIn 0.3s cubic-bezier(0.22,1,0.36,1) both}',
    '#mm-widget-root .mm-msg.mm-ai{align-self:flex-start;background:#f3f4f6;color:#1f2937;border-bottom-left-radius:4px}',
    '#mm-widget-root .mm-msg.mm-user{align-self:flex-end;background:var(--mm-color);color:#fff;border-bottom-right-radius:4px}',
    '@keyframes mm-msgIn{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:translateY(0)}}',

    /* Typing indicator */
    '#mm-widget-root .mm-typing{align-self:flex-start;display:flex;gap:4px;padding:12px 16px;background:#f3f4f6;border-radius:14px;border-bottom-left-radius:4px}',
    '#mm-widget-root .mm-typing span{width:7px;height:7px;background:#94a3b8;border-radius:50%;animation:mm-dot 1.4s ease-in-out infinite}',
    '#mm-widget-root .mm-typing span:nth-child(2){animation-delay:0.16s}',
    '#mm-widget-root .mm-typing span:nth-child(3){animation-delay:0.32s}',
    '@keyframes mm-dot{0%,60%,100%{transform:translateY(0);opacity:0.4}30%{transform:translateY(-6px);opacity:1}}',

    /* Quick replies */
    '#mm-widget-root .mm-quick-wrap{display:flex;flex-wrap:wrap;gap:6px;padding:0 2px}',
    '#mm-widget-root .mm-quick{padding:7px 13px;border-radius:20px;font-size:13px;cursor:pointer;background:#fff;color:var(--mm-color);border:1.5px solid rgba(var(--mm-color-rgb),0.3);font-family:inherit;transition:all 0.15s;line-height:1.3}',
    '#mm-widget-root .mm-quick:hover{background:rgba(var(--mm-color-rgb),0.08);border-color:var(--mm-color)}',

    /* Input area */
    '#mm-widget-root .mm-input-area{padding:12px 14px;border-top:1px solid #f1f5f9;display:flex;gap:8px;align-items:flex-end;flex-shrink:0}',
    '#mm-widget-root .mm-input{flex:1;min-height:40px;max-height:100px;padding:9px 14px;font-size:14px;border:1.5px solid #e2e8f0;border-radius:22px;background:#f8fafc;color:#1f2937;resize:none;outline:none;font-family:inherit;line-height:1.4;transition:border-color 0.15s,box-shadow 0.15s}',
    '#mm-widget-root .mm-input:focus{border-color:var(--mm-color);box-shadow:0 0 0 3px rgba(var(--mm-color-rgb),0.1);background:#fff}',
    '#mm-widget-root .mm-input::placeholder{color:#94a3b8}',
    '#mm-widget-root .mm-send{width:38px;height:38px;border:none;border-radius:50%;background:var(--mm-color);color:#fff;cursor:pointer;display:flex;align-items:center;justify-content:center;transition:transform 0.15s,opacity 0.15s;flex-shrink:0;padding:0}',
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
    '#mm-widget-root .mm-err{color:#dc2626;font-size:13px;padding:8px 14px;background:#fef2f2;border-radius:10px;border:1px solid #fecaca;align-self:flex-start}'
  ].join('\n');
  root.appendChild(sheet);

  var open = false;
  var suggested = [];
  var apiLoadFailed = false;
  var chatEl, inputEl, sendBtn;
  var hasGreeted = false;

  function escapeHtml(s) { var d = document.createElement('div'); d.textContent = s; return d.innerHTML; }
  function networkErrorMessage() {
    return phone ? ("Couldn't load right now. Call " + phone + " instead.") : "Couldn't load right now. Try again later.";
  }

  function scrollToBottom() {
    if (chatEl) setTimeout(function () { chatEl.scrollTop = chatEl.scrollHeight; }, 50);
  }

  function addMessage(text, type) {
    var div = document.createElement('div');
    div.className = 'mm-msg ' + (type === 'user' ? 'mm-user' : 'mm-ai');
    div.textContent = text;
    chatEl.appendChild(div);
    scrollToBottom();
  }

  function showTyping() {
    var div = document.createElement('div');
    div.className = 'mm-typing';
    div.id = 'mm-typing';
    div.innerHTML = '<span></span><span></span><span></span>';
    chatEl.appendChild(div);
    scrollToBottom();
  }

  function hideTyping() {
    var el = chatEl.querySelector('#mm-typing');
    if (el) el.remove();
  }

  function showQuickReplies(questions) {
    var wrap = document.createElement('div');
    wrap.className = 'mm-quick-wrap';
    wrap.id = 'mm-quick-wrap';
    questions.forEach(function (q) {
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'mm-quick';
      btn.textContent = q;
      btn.onclick = function () {
        removeQuickReplies();
        sendQuestion(q);
      };
      wrap.appendChild(btn);
    });
    chatEl.appendChild(wrap);
    scrollToBottom();
  }

  function removeQuickReplies() {
    var el = chatEl.querySelector('#mm-quick-wrap');
    if (el) el.remove();
  }

  function showGreeting() {
    if (hasGreeted) return;
    hasGreeted = true;
    addMessage(greeting, 'ai');
    if (suggested.length > 0) {
      showQuickReplies(suggested.slice(0, 4));
    }
  }

  function renderButton() {
    var btn = document.createElement('button');
    btn.className = 'mm-btn';
    btn.type = 'button';
    btn.setAttribute('aria-label', 'Chat with us');
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
    hdr.innerHTML = '<div class="mm-hdr-info"><h3>' + escapeHtml(name) + '</h3><div class="mm-sub">Ask us anything</div></div>';
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

    chatEl = document.createElement('div');
    chatEl.className = 'mm-chat';
    panel.appendChild(chatEl);

    var inputArea = document.createElement('div');
    inputArea.className = 'mm-input-area';
    inputEl = document.createElement('textarea');
    inputEl.className = 'mm-input';
    inputEl.placeholder = 'Type your question...';
    inputEl.setAttribute('aria-label', 'Type your question');
    inputEl.rows = 1;
    inputEl.onkeydown = function (e) {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        doSend();
      }
    };
    inputEl.oninput = function () {
      this.style.height = 'auto';
      this.style.height = Math.min(this.scrollHeight, 100) + 'px';
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
    sendQuestion(text);
  }

  function sendQuestion(text) {
    inputEl.value = '';
    inputEl.style.height = 'auto';
    sendBtn.disabled = true;
    removeQuickReplies();
    addMessage(text, 'user');
    showTyping();

    var xhr = new XMLHttpRequest();
    xhr.open('POST', apiBase + '/api/v2/generate-quote-reply', true);
    xhr.setRequestHeader('Content-Type', 'application/json');
    xhr.onload = function () {
      hideTyping();
      sendBtn.disabled = false;
      if (xhr.status === 200) {
        try {
          var data = JSON.parse(xhr.responseText);
          var ans = (data.replyText || '').trim();
          if (ans) addMessage(ans, 'ai');
          else addMessage('Sorry, I couldn\'t find an answer. Please call ' + (phone || 'the business') + ' directly.', 'ai');
        } catch (e) {
          addMessage('Something went wrong. Please try again.', 'ai');
        }
      } else {
        addMessage(networkErrorMessage(), 'ai');
      }
      if (inputEl) inputEl.focus();
    };
    xhr.onerror = function () {
      hideTyping();
      sendBtn.disabled = false;
      addMessage(networkErrorMessage(), 'ai');
    };
    xhr.send(JSON.stringify({ tenantId: tenant, customerMessage: text }));
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
