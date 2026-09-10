/* ════════════════════════════════════════════════════
   DocuMind AI  ·  app.js
   ════════════════════════════════════════════════════ */

// Firebase removed
const API = 'https://e31796cd8172df.lhr.life';
let queryMode = 'auto';
let isLoading = false;
let authToken = localStorage.getItem('documind_token') || null;

// ── Configure marked ─────────────────────────────────────────────
marked.setOptions({ breaks: true, gfm: true });

// ── DOM Refs ─────────────────────────────────────────────────────
const $ = id => document.getElementById(id);
const sidebar       = $('sidebar');
const sidebarToggle = $('sidebar-toggle');
const statusPill    = $('status-pill');
const statusDot     = $('status-dot');
const statusText    = $('status-text');
const modeLabel     = $('mode-label');
const modeBtns      = document.querySelectorAll('.mode-btn');
const messages      = $('messages');
const messagesWrap  = $('messages-wrap');
const welcomeState  = $('welcome-state');
const chatForm      = $('chat-form');
const queryInput    = $('query-input');
const sendBtn       = $('send-btn');
const charCount     = $('char-count');
const uploadModal   = $('upload-modal');
const uploadBtn     = $('upload-btn');
const quickUploadBtn= $('quick-upload-btn');
const closeModal    = $('close-modal');
const dropZone      = $('drop-zone');
const fileInput     = $('file-input');
const browseBtn     = $('browse-btn');
const uploadProgress= $('upload-progress');
const progressFilename = $('progress-filename');
const progressPct   = $('progress-pct');
const progressFill  = $('progress-fill');
const progressStatus= $('progress-status');
const documentList  = $('document-list');
const historyList   = $('history-list');
const newChatBtn    = $('new-chat-btn');
const clearChatBtn  = $('clear-chat-btn');
const chips         = document.querySelectorAll('.chip');
const toastContainer= $('toast-container');
const themeToggleBtn= $('theme-toggle-btn');
const sunIcon       = themeToggleBtn.querySelector('.sun-icon');
const moonIcon      = themeToggleBtn.querySelector('.moon-icon');

// ── Auth Logic ───────────────────────────────────────────────────
const authOverlay = document.getElementById('auth-overlay');
const authForm = document.getElementById('auth-form');
const authUsername = document.getElementById('auth-username');
const authSubmitBtn = document.getElementById('auth-submit-btn');
const signoutBtn = document.getElementById('signout-btn');
const userEmailDisplay = document.getElementById('user-email-display');

authForm.addEventListener('submit', async (e) => {
  e.preventDefault();
  const username = authUsername.value.trim();
  if (!username) return;

  authSubmitBtn.disabled = true;
  authSubmitBtn.textContent = 'Please wait...';

  try {
    const res = await fetch(`${API}/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Bypass-Tunnel-Reminder': 'true' },
      body: JSON.stringify({ username })
    });
    
    if (res.ok) {
      const data = await res.json();
      authToken = data.token;
      localStorage.setItem('documind_token', authToken);
      userEmailDisplay.textContent = data.username;
      
      authOverlay.classList.remove('active');
      showToast('Successfully logged in!', 'success');
      
      checkHealth(); // load data
    } else {
      const err = await res.json();
      showToast(err.detail || 'Authentication failed', 'error');
    }
  } catch {
    showToast('Cannot connect to server.', 'error');
  } finally {
    authSubmitBtn.disabled = false;
    authSubmitBtn.textContent = 'Start Chatting';
  }
});

if (signoutBtn) {
  signoutBtn.addEventListener('click', () => {
    authToken = null;
    localStorage.removeItem('documind_token');
    documentList.innerHTML = '<li class="side-empty-item">No documents yet</li>';
    historyList.innerHTML = '<li class="side-empty-item">No history yet</li>';
    messages.innerHTML = '';
    if (welcomeState) {
      messages.appendChild(welcomeState);
      welcomeState.style.display = '';
    }
    authOverlay.classList.add('active');
  });
}

// Firebase login removed

async function apiFetch(path, options = {}) {
  if (!options.headers) options.headers = {};
  if (authToken) Object.assign(options.headers, { 'Authorization': `Bearer ${authToken}` });
  Object.assign(options.headers, { 'Bypass-Tunnel-Reminder': 'true' });
  
  const res = await fetch(`${API}${path}`, options);
  if (res.status === 401) {
    authToken = null;
    localStorage.removeItem('documind_token');
    authOverlay.classList.add('active');
  }
  return res;
}

// Check initial auth state
if (!authToken) {
  authOverlay.classList.add('active');
} else {
  // Validate token
  apiFetch('/auth/me').then(async res => {
    if (res.ok) {
      const data = await res.json();
      userEmailDisplay.textContent = data.username;
      authOverlay.classList.remove('active');
      checkHealth();
    } else {
      authOverlay.classList.add('active');
    }
  }).catch(() => {
    authOverlay.classList.add('active');
  });
}

// ── Mode Labels Map ───────────────────────────────────────────────
const modeLabels = {
  auto:    'Auto mode — uses your documents + AI knowledge',
  docs:    'Documents only — answers strictly from uploaded files',
  general: 'General AI — answers from world knowledge (ignores docs)',
};

// ── Health Check & Status ─────────────────────────────────────────
async function checkHealth() {
  if (!authToken) return;
  try {
    const res = await apiFetch('/health', { signal: AbortSignal.timeout(4000) });
    if (res.ok) {
      statusPill.className = 'status-pill online';
      statusText.textContent = 'Connected';
      loadDocuments();
      loadHistory();
      return true;
    }
  } catch {}
  statusPill.className = 'status-pill offline';
  statusText.textContent = 'Server offline';
  return false;
}

setInterval(checkHealth, 8000);

// ── Mode Toggle ───────────────────────────────────────────────────
modeBtns.forEach(btn => {
  btn.addEventListener('click', () => {
    modeBtns.forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    queryMode = btn.dataset.mode;
    modeLabel.textContent = modeLabels[queryMode];
    showToast(`Mode: ${btn.textContent.trim()}`, 'info');
  });
});

// ── Sidebar Toggle ────────────────────────────────────────────────
sidebarToggle.addEventListener('click', () => sidebar.classList.toggle('hidden'));

// ── Theme Toggle ──────────────────────────────────────────────────
const savedTheme = localStorage.getItem('theme') || 'dark';
if (savedTheme === 'light') {
  document.documentElement.classList.add('light-theme');
  document.body.classList.add('light-theme');
  sunIcon.style.display = 'none';
  moonIcon.style.display = 'block';
}

themeToggleBtn.addEventListener('click', () => {
  const isLight = document.body.classList.toggle('light-theme');
  document.documentElement.classList.toggle('light-theme');
  
  if (isLight) {
    sunIcon.style.display = 'none';
    moonIcon.style.display = 'block';
    localStorage.setItem('theme', 'light');
    showToast('Switched to Light Theme', 'info');
  } else {
    sunIcon.style.display = 'block';
    moonIcon.style.display = 'none';
    localStorage.setItem('theme', 'dark');
    showToast('Switched to Dark Theme', 'info');
  }
});

// ── Textarea Auto-resize & Send Enable ───────────────────────────
queryInput.addEventListener('input', () => {
  queryInput.style.height = 'auto';
  queryInput.style.height = Math.min(queryInput.scrollHeight, 180) + 'px';
  charCount.textContent = `${queryInput.value.length} / 4000`;
  sendBtn.disabled = queryInput.value.trim().length === 0 || isLoading;
});

queryInput.addEventListener('keydown', e => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    if (!sendBtn.disabled) chatForm.dispatchEvent(new Event('submit'));
  }
});

// ── Suggestion Chips ──────────────────────────────────────────────
chips.forEach(chip => {
  chip.addEventListener('click', () => {
    queryInput.value = chip.dataset.query;
    queryInput.dispatchEvent(new Event('input'));
    queryInput.focus();
  });
});

// ── New Chat ──────────────────────────────────────────────────────
newChatBtn.addEventListener('click', () => {
  messages.innerHTML = '';
  welcomeState && messages.appendChild(welcomeState);
  welcomeState.style.display = '';
});

// ── Chat Submit ───────────────────────────────────────────────────
chatForm.addEventListener('submit', async e => {
  e.preventDefault();
  const query = queryInput.value.trim();
  if (!query || isLoading) return;

  hideWelcome();
  appendUserMessage(query);
  queryInput.value = '';
  queryInput.style.height = 'auto';
  charCount.textContent = '0 / 4000';
  sendBtn.disabled = true;

  isLoading = true;
  const typingId = appendTyping();

  try {
    const res = await apiFetch('/query', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query, mode: queryMode }),
    });

    removeTyping(typingId);

    if (res.ok) {
      const data = await res.json();
      appendAIMessage(data.answer, data.mode_used, data.sources || [], data.model);
      loadHistory();
    } else {
      const err = await res.json();
      appendAIMessage(`⚠️ **Error:** ${err.detail || 'Something went wrong.'}`, 'general', []);
    }
  } catch {
    removeTyping(typingId);
    appendAIMessage('⚠️ **Cannot connect to server.** Make sure the backend is running:\n```\ncd backend && source venv/bin/activate && uvicorn main:app --reload\n```', 'general', []);
  } finally {
    isLoading = false;
    sendBtn.disabled = queryInput.value.trim().length === 0;
  }
});

// ── Message Renderers ─────────────────────────────────────────────
function hideWelcome() {
  if (welcomeState) welcomeState.style.display = 'none';
}

function appendUserMessage(text) {
  const div = document.createElement('div');
  div.className = 'message user';
  div.innerHTML = `
    <div class="avatar">U</div>
    <div class="bubble">${escHtml(text)}</div>
  `;
  messages.appendChild(div);
  scrollToBottom();
}

function appendAIMessage(markdown, modeUsed, sources, modelName) {
  const div = document.createElement('div');
  div.className = 'message ai';

  const htmlContent = marked.parse(markdown);

  // Sources
  let sourcesHtml = '';
  if (sources && sources.length) {
    sourcesHtml = sources.map(s =>
      `<span class="source-badge">📄 ${escHtml(s)}</span>`
    ).join('');
  }

  // Mode badge
  const modeBadge = modeUsed === 'rag'
    ? `<span class="mode-badge rag">📚 From Documents</span>`
    : `<span class="mode-badge general">🌐 General AI</span>`;

  // Model badge
  const modelBadge = modelName
    ? `<span class="mode-badge" style="background:rgba(34,211,238,.1);color:#22d3ee;border:1px solid rgba(34,211,238,.3)">🤖 ${escHtml(modelName)}</span>`
    : '';

  div.innerHTML = `
    <div class="avatar">AI</div>
    <div>
      <div class="bubble">${htmlContent}</div>
      <div class="bubble-meta">
        ${modeBadge}
        ${sourcesHtml}
        <button class="copy-btn" title="Copy answer">
          <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>
          Copy
        </button>
      </div>
    </div>
  `;

  // Copy btn
  div.querySelector('.copy-btn').addEventListener('click', function () {
    navigator.clipboard.writeText(markdown).then(() => {
      this.textContent = '✓ Copied!';
      this.classList.add('copied');
      setTimeout(() => { this.innerHTML = `<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg> Copy`; this.classList.remove('copied'); }, 2000);
    });
  });

  messages.appendChild(div);
  scrollToBottom();
}

function appendTyping() {
  const id = 'typing-' + Date.now();
  const div = document.createElement('div');
  div.className = 'typing-indicator';
  div.id = id;
  div.innerHTML = `
    <div class="avatar" style="background:linear-gradient(135deg,#8b5cf6,#22d3ee);color:#fff">AI</div>
    <div class="typing-dots"><span></span><span></span><span></span></div>
  `;
  messages.appendChild(div);
  scrollToBottom();
  return id;
}

function removeTyping(id) {
  const el = $(id);
  if (el) el.remove();
}

function scrollToBottom() {
  messagesWrap.scrollTop = messagesWrap.scrollHeight;
}

// ── Upload Modal ──────────────────────────────────────────────────
function openUpload() { uploadModal.classList.add('open'); }
function closeUploadModal() {
  uploadModal.classList.remove('open');
  uploadProgress.hidden = true;
  dropZone.hidden = false;
  fileInput.value = '';
}

uploadBtn.addEventListener('click', openUpload);
quickUploadBtn.addEventListener('click', openUpload);
closeModal.addEventListener('click', closeUploadModal);
uploadModal.addEventListener('click', e => { if (e.target === uploadModal) closeUploadModal(); });

browseBtn.addEventListener('click', () => fileInput.click());
fileInput.addEventListener('change', e => { if (e.target.files[0]) handleUpload(e.target.files[0]); });

dropZone.addEventListener('dragover', e => { e.preventDefault(); dropZone.classList.add('dragover'); });
dropZone.addEventListener('dragleave', () => dropZone.classList.remove('dragover'));
dropZone.addEventListener('drop', e => {
  e.preventDefault();
  dropZone.classList.remove('dragover');
  if (e.dataTransfer.files[0]) handleUpload(e.dataTransfer.files[0]);
});
dropZone.addEventListener('click', e => {
  if (e.target !== browseBtn) fileInput.click();
});

async function handleUpload(file) {
  const ext = file.name.split('.').pop().toLowerCase();
  if (!['pdf','txt'].includes(ext)) {
    showToast('Only PDF and TXT files are supported.', 'error');
    return;
  }

  // Show progress UI
  dropZone.hidden = true;
  uploadProgress.hidden = false;
  progressFilename.textContent = file.name;
  setProgress(10, 'Uploading…');

  const formData = new FormData();
  formData.append('file', file);

  try {
    // Simulate progress
    let prog = 10;
    const ticker = setInterval(() => {
      prog = Math.min(prog + Math.random() * 12, 80);
      setProgress(Math.round(prog), 'Processing document…');
    }, 400);

    const res = await apiFetch('/upload', { method: 'POST', body: formData });

    clearInterval(ticker);

    if (res.ok) {
      const data = await res.json();
      setProgress(100, `Done! ${data.chunks} chunks indexed.`);
      showToast(`"${file.name}" uploaded — ${data.chunks} chunks ready!`, 'success');
      loadDocuments();
      setTimeout(closeUploadModal, 1400);
    } else {
      const err = await res.json();
      setProgress(0, `Error: ${err.detail}`);
      showToast(err.detail || 'Upload failed.', 'error');
    }
  } catch {
    setProgress(0, 'Cannot connect to server.');
    showToast('Cannot connect to server. Is the backend running?', 'error');
  }
}

function setProgress(pct, msg) {
  progressFill.style.width = pct + '%';
  progressPct.textContent = pct + '%';
  progressStatus.textContent = msg;
}

// ── Load Documents ────────────────────────────────────────────────
async function loadDocuments() {
  try {
    const res = await apiFetch('/documents');
    if (!res.ok) return;
    const docs = await res.json();
    documentList.innerHTML = '';
    if (!docs.length) {
      documentList.innerHTML = '<li class="side-empty-item">No documents yet</li>';
      return;
    }
    docs.forEach(doc => {
      const li = document.createElement('li');
      li.innerHTML = `
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14,2 14,8 20,8"/></svg>
        <span style="overflow:hidden;text-overflow:ellipsis">${escHtml(doc.filename)}</span>
        <button class="delete-btn" data-id="${doc.id}" title="Remove">
          <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
        </button>
      `;
      li.title = doc.filename;
      li.querySelector('.delete-btn').addEventListener('click', async e => {
        e.stopPropagation();
        await apiFetch(`/documents/${doc.id}`, { method: 'DELETE' });
        showToast(`"${doc.filename}" removed.`, 'info');
        loadDocuments();
      });
      documentList.appendChild(li);
    });
  } catch {}
}

// ── Load History ──────────────────────────────────────────────────
async function loadHistory() {
  try {
    const res = await apiFetch('/history');
    if (!res.ok) return;
    const items = await res.json();
    historyList.innerHTML = '';
    if (!items.length) {
      historyList.innerHTML = '<li class="side-empty-item">No history yet</li>';
      return;
    }
    items.slice(0, 20).forEach(item => {
      const li = document.createElement('li');
      const truncated = item.question.length > 36 ? item.question.slice(0, 36) + '…' : item.question;
      li.innerHTML = `
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
        <span style="overflow:hidden;text-overflow:ellipsis">${escHtml(truncated)}</span>
        <button class="delete-btn" data-id="${item.id}" title="Delete">
          <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
        </button>
      `;
      li.title = item.question;
      li.querySelector('.delete-btn').addEventListener('click', async e => {
        e.stopPropagation();
        await apiFetch(`/history/${item.id}`, { method: 'DELETE' });
        loadHistory();
      });
      // Click to replay
      li.addEventListener('click', () => {
        queryInput.value = item.question;
        queryInput.dispatchEvent(new Event('input'));
        queryInput.focus();
      });
      historyList.appendChild(li);
    });
  } catch {}
}

// ── Clear Chat ────────────────────────────────────────────────────
clearChatBtn.addEventListener('click', async () => {
  try {
    const res = await apiFetch('/history');
    const items = await res.json();
    await Promise.all(items.map(i => apiFetch(`/history/${i.id}`, { method: 'DELETE' })));
    loadHistory();
    showToast('Chat history cleared.', 'info');
  } catch {
    showToast('Could not clear history.', 'error');
  }
});

// ── Toast Notifications ───────────────────────────────────────────
function showToast(msg, type = 'info') {
  const icons = {
    success: `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"><polyline points="20,6 9,17 4,12"/></svg>`,
    error:   `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>`,
    info:    `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>`,
  };
  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  toast.innerHTML = `<div class="toast-icon">${icons[type]}</div><span>${escHtml(msg)}</span>`;
  toastContainer.appendChild(toast);
  setTimeout(() => {
    toast.classList.add('toast-leaving');
    setTimeout(() => toast.remove(), 300);
  }, 4000);
}

// ── Utility ───────────────────────────────────────────────────────
function escHtml(str) {
  return String(str)
    .replace(/&/g,'&amp;').replace(/</g,'&lt;')
    .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
