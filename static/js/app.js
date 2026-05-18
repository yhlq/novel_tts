/** 小说多角色语音合成 - 前端 */
let currentProjectId = null;
let voicesCache = [];

function toast(msg, isError = false) {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.className = 'toast show' + (isError ? ' error' : '');
  setTimeout(() => el.classList.remove('show'), 3500);
}

async function api(url, options = {}) {
  const res = await fetch(url, options);
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(typeof err.detail === 'string' ? err.detail : JSON.stringify(err.detail));
  }
  const ct = res.headers.get('content-type') || '';
  if (ct.includes('application/json')) return res.json();
  return res;
}

function audioUrl(path) {
  if (!path) return '';
  if (path.startsWith('http') || path.startsWith('/')) return path;
  return '/' + path;
}

function escapeHtml(s) {
  if (!s) return '';
  const d = document.createElement('div');
  d.textContent = s;
  return d.innerHTML;
}

function statusBadge(status) {
  const map = { pending: '待处理', parsed: '已解析', generating: '生成中', completed: '已完成' };
  return `<span class="badge badge-${status}">${map[status] || status}</span>`;
}

const LINE_STATUS = {
  pending: { text: '待生成', cls: 'badge-pending' },
  generating: { text: '生成中…', cls: 'badge-generating' },
  done: { text: '已生成', cls: 'badge-completed' },
  failed: { text: '失败', cls: 'badge-failed' },
};

function lineStatusBadge(status) {
  const s = LINE_STATUS[status] || LINE_STATUS.pending;
  return `<span class="badge line-status ${s.cls}" data-status="${status}">${s.text}</span>`;
}

function setProjectWsStatus(status) {
  const el = document.getElementById('wsStatus');
  if (!el) return;
  const map = { pending: '待处理', parsed: '已解析', generating: '生成中', completed: '已完成' };
  el.className = 'badge badge-' + status;
  el.textContent = map[status] || status;
}

function setLineStatus(lineId, status, audioPath, errorMsg) {
  const item = document.querySelector(`.line-item[data-line-id="${lineId}"]`);
  if (!item) return;
  item.classList.remove('generating', 'done', 'failed');
  if (status === 'generating') item.classList.add('generating');
  if (status === 'done') item.classList.add('done');
  if (status === 'failed') item.classList.add('failed');

  const badge = item.querySelector('.line-status');
  if (badge) {
    const s = LINE_STATUS[status] || LINE_STATUS.pending;
    badge.className = `badge line-status ${s.cls}`;
    badge.dataset.status = status;
    badge.textContent = errorMsg ? `失败: ${errorMsg.slice(0, 20)}` : s.text;
  }

  const slot = item.querySelector('.line-audio-slot');
  if (!slot) return;
  if (status === 'generating') {
    slot.innerHTML = '<span style="color:var(--warning);font-size:0.85rem">正在合成…</span>';
  } else if (status === 'done' && audioPath) {
    slot.innerHTML = `<audio controls src="${audioUrl(audioPath)}?t=${Date.now()}"></audio>`;
  } else if (status === 'failed') {
    slot.innerHTML = `<span style="color:var(--danger);font-size:0.85rem">${escapeHtml(errorMsg || '生成失败')}</span>`;
  }
}

// ---------- Tab ----------
document.querySelectorAll('#mainTabs .tab').forEach(tab => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('#mainTabs .tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
    tab.classList.add('active');
    document.getElementById('panel-' + tab.dataset.panel).classList.add('active');
    if (tab.dataset.panel === 'voices') loadVoices();
    if (tab.dataset.panel === 'inference') loadInferenceConfig();
  });
});

// ---------- 项目 ----------
async function loadProjects() {
  const projects = await api('/api/projects');
  const el = document.getElementById('projectsList');
  if (!projects.length) {
    el.innerHTML = '<p class="empty">暂无项目，请创建</p>';
    return;
  }
  el.innerHTML = `<table>
    <tr><th>ID</th><th>名称</th><th>状态</th><th>操作</th></tr>
    ${projects.map(p => `<tr>
      <td>${p.id}</td>
      <td>${escapeHtml(p.name)}</td>
      <td>${statusBadge(p.status)}</td>
      <td>
        <button class="btn btn-sm btn-primary" onclick="openWorkspace(${p.id})">打开</button>
        <button class="btn btn-sm btn-danger" onclick="deleteProject(${p.id})">删除</button>
      </td>
    </tr>`).join('')}
  </table>`;
}

document.getElementById('btnCreateProject').addEventListener('click', async () => {
  const name = document.getElementById('projectName').value.trim();
  const text = document.getElementById('textContent').value.trim();
  const fileInput = document.getElementById('fileUpload');
  if (!name) return toast('请输入项目名称', true);

  try {
    let result;
    if (fileInput.files.length) {
      const fd = new FormData();
      fd.append('name', name);
      fd.append('file', fileInput.files[0]);
      result = await api('/api/projects/upload', { method: 'POST', body: fd });
    } else if (text) {
      const fd = new FormData();
      fd.append('name', name);
      fd.append('text_content', text);
      result = await api('/api/projects', { method: 'POST', body: fd });
    } else {
      return toast('请输入文本或选择文件', true);
    }
    toast('项目创建成功');
    currentProjectId = result.id;
    await loadProjects();
    openWorkspace(result.id);
  } catch (e) {
    toast('创建失败: ' + e.message, true);
  }
});

document.getElementById('btnLoadExample').addEventListener('click', async () => {
  try {
    const res = await fetch('/novel_example.txt');
    if (!res.ok) throw new Error('not found');
    document.getElementById('textContent').value = await res.text();
    toast('示例已加载');
  } catch (_) {
    toast('请将 novel_example.txt 放在项目根目录', true);
  }
});

async function deleteProject(id) {
  if (!confirm('确定删除？')) return;
  await api(`/api/projects/${id}`, { method: 'DELETE' });
  if (currentProjectId === id) {
    currentProjectId = null;
    document.getElementById('workspaceSection').style.display = 'none';
  }
  loadProjects();
  toast('已删除');
}

// ---------- 工作台 ----------
async function openWorkspace(projectId) {
  currentProjectId = projectId;
  document.getElementById('workspaceSection').style.display = 'block';
  await refreshWorkspace();
  document.getElementById('workspaceSection').scrollIntoView({ behavior: 'smooth' });
}

async function refreshWorkspace() {
  if (!currentProjectId) return;
  const ws = await api(`/api/projects/${currentProjectId}/workspace`);
  document.getElementById('wsProjectName').textContent = ws.project.name;
  setProjectWsStatus(ws.project.status);

  await loadVoicesCache();
  renderCharacters(ws.characters);
  renderLines(ws.lines);
}

function renderCharacters(characters) {
  const el = document.getElementById('charactersList');
  if (!characters.length) {
    el.innerHTML = '<p class="empty">请先解析文本</p>';
    return;
  }
  el.innerHTML = characters.map(c => {
    const opts = voicesCache.map(v =>
      `<option value="${v.id}" ${v.id === c.voice_id ? 'selected' : ''}>${escapeHtml(v.name)} (${v.type_label})</option>`
    ).join('');
    return `<div class="char-row">
      <strong style="min-width:80px">${escapeHtml(c.name)}</strong>
      <select data-char-id="${c.id}" class="char-voice-select">
        <option value="">— 选择声音 —</option>${opts}
      </select>
      <button class="btn btn-sm btn-secondary" onclick="saveCharacterVoice(${c.id})">保存</button>
    </div>`;
  }).join('');
}

async function saveCharacterVoice(charId) {
  const sel = document.querySelector(`select[data-char-id="${charId}"]`);
  const voiceId = sel.value;
  if (!voiceId) return toast('请选择声音', true);
  const fd = new FormData();
  fd.append('voice_id', voiceId);
  await api(`/api/projects/${currentProjectId}/characters/${charId}`, { method: 'PUT', body: fd });
  toast('角色声音已保存');
  refreshWorkspace();
}

function renderLines(lines) {
  const el = document.getElementById('linesList');
  if (!lines.length) {
    el.innerHTML = '<p class="empty">请先解析文本</p>';
    return;
  }
  el.innerHTML = lines.map(line => {
    const st = line.status || (line.has_audio ? 'done' : 'pending');
    const itemCls = st === 'done' ? 'done' : (st === 'failed' ? 'failed' : '');
    const audioHtml = line.has_audio
      ? `<audio controls src="${audioUrl(line.audio_path)}?t=${line.id}"></audio>`
      : '<span style="color:var(--muted);font-size:0.85rem">未生成</span>';
    return `<div class="line-item ${itemCls}" data-line-id="${line.id}">
      <div class="line-header">
        <span class="badge">#${line.order + 1}</span>
        ${lineStatusBadge(st)}
        <strong>${escapeHtml(line.character_name)}</strong>
        ${line.voice_name ? `<span style="color:var(--muted);font-size:0.85rem"> → ${escapeHtml(line.voice_name)}</span>` : ''}
      </div>
      <div class="line-content">${escapeHtml(line.content)}</div>
      <div class="line-actions">
        <input type="text" placeholder="情感（可选）" value="${escapeHtml(line.emotion)}" data-emotion-line="${line.id}">
        <button class="btn btn-sm btn-primary" onclick="generateLine(${line.id}, this)">生成</button>
        <button class="btn btn-sm btn-secondary" onclick="regenerateLine(${line.id}, this)">重新生成</button>
        <button class="btn btn-sm btn-secondary" onclick="saveLineEmotion(${line.id})">保存情感</button>
        <span class="line-audio-slot">${audioHtml}</span>
      </div>
    </div>`;
  }).join('');
}

async function saveLineEmotion(lineId) {
  const input = document.querySelector(`input[data-emotion-line="${lineId}"]`);
  const fd = new FormData();
  fd.append('emotion', input.value);
  await api(`/api/projects/${currentProjectId}/lines/${lineId}/emotion`, { method: 'PUT', body: fd });
  toast('情感已保存');
}

async function generateLine(lineId, btn) {
  if (btn) { btn.disabled = true; btn.textContent = '生成中…'; }
  setLineStatus(lineId, 'generating');
  try {
    const r = await api(`/api/projects/${currentProjectId}/lines/${lineId}/generate`, { method: 'POST' });
    const path = r.audio_path?.startsWith('/') ? r.audio_path : '/' + (r.audio_path || '');
    setLineStatus(lineId, 'done', path);
    toast('生成成功');
  } catch (e) {
    setLineStatus(lineId, 'failed', null, e.message);
    toast('生成失败: ' + e.message, true);
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = '生成'; }
  }
}

async function regenerateLine(lineId, btn) {
  await generateLine(lineId, btn);
  if (btn) btn.textContent = '重新生成';
}

document.getElementById('btnParse').addEventListener('click', async () => {
  if (!currentProjectId) return;
  const btn = document.getElementById('btnParse');
  btn.disabled = true;
  btn.textContent = '解析中…';
  try {
    const r = await api(`/api/projects/${currentProjectId}/parse`, { method: 'POST' });
    toast(`解析完成：${r.characters.join('、')}，共 ${r.lines_count} 条`);
    await refreshWorkspace();
  } catch (e) {
    toast('解析失败: ' + e.message, true);
  } finally {
    btn.disabled = false;
    btn.textContent = '解析角色';
  }
});

document.getElementById('btnGenerateAll').addEventListener('click', async () => {
  if (!currentProjectId) return;
  const ws = await api(`/api/projects/${currentProjectId}/workspace`);
  if (!ws.lines.length) return toast('请先解析文本', true);
  if (!confirm(`将为 ${ws.lines.length} 条台词逐条生成音频，继续？`)) return;

  const btn = document.getElementById('btnGenerateAll');
  btn.disabled = true;
  btn.textContent = `生成中 0/${ws.lines.length}`;
  setProjectWsStatus('generating');

  try {
    toast('正在预热角色音色缓存…');
    await api(`/api/projects/${currentProjectId}/warmup-voices`, { method: 'POST' });
  } catch (e) {
    console.warn('音色预热:', e.message);
  }

  let success = 0;
  let failed = 0;

  for (let i = 0; i < ws.lines.length; i++) {
    const line = ws.lines[i];
    btn.textContent = `生成中 ${i + 1}/${ws.lines.length}`;
    setLineStatus(line.id, 'generating');
    try {
      const r = await api(`/api/projects/${currentProjectId}/lines/${line.id}/generate`, { method: 'POST' });
      const path = r.audio_path?.startsWith('/') ? r.audio_path : '/' + (r.audio_path || '');
      setLineStatus(line.id, 'done', path);
      success++;
    } catch (e) {
      setLineStatus(line.id, 'failed', null, e.message);
      failed++;
    }
  }

  try {
    if (success > 0) {
      await api(`/api/projects/${currentProjectId}/merge`, { method: 'POST' });
      setProjectWsStatus('completed');
    }
  } catch (_) { /* 合并不阻断 */ }

  toast(`完成：成功 ${success}，失败 ${failed}`);
  btn.disabled = false;
  btn.textContent = '一键生成全部音频';
  await refreshWorkspace();
});

document.getElementById('btnDownloadMerged').addEventListener('click', () => {
  if (currentProjectId) window.open(`/api/projects/${currentProjectId}/download`, '_blank');
});

document.getElementById('btnRefreshWs').addEventListener('click', refreshWorkspace);

// ---------- 声音库 ----------
async function loadVoicesCache() {
  voicesCache = await api('/api/voices');
}

async function loadVoices() {
  await loadVoicesCache();
  const el = document.getElementById('voicesGrid');
  if (!voicesCache.length) {
    el.innerHTML = '<p class="empty">暂无声音</p>';
    return;
  }
  el.innerHTML = voicesCache.map(v => `
    <div class="voice-card">
      <h3>${escapeHtml(v.name)} <span class="badge">${v.type_label}</span></h3>
      <div class="meta">${escapeHtml(v.description || '无描述')}</div>
      ${v.emotion ? `<p style="font-size:0.85rem;margin:4px 0">默认情感：${escapeHtml(v.emotion)}</p>` : ''}
      ${v.instruct ? `<p style="font-size:0.8rem;color:var(--muted)">指令：${escapeHtml(v.instruct.slice(0, 100))}</p>` : ''}
      <div class="btn-row">
        <input type="text" placeholder="试听文本" value="你好，这是试听。" data-preview-text="${v.id}">
        <input type="text" placeholder="情感" style="max-width:90px" data-preview-emotion="${v.id}">
        <button class="btn btn-sm btn-primary" onclick="previewVoice(${v.id})">试听</button>
        ${v.type !== 'predefined' ? `<button class="btn btn-sm btn-secondary" onclick="warmupVoice(${v.id})">预热音色</button>` : ''}
        ${v.type !== 'predefined' ? `<button class="btn btn-sm btn-danger" onclick="deleteVoice(${v.id})">删除</button>` : ''}
      </div>
      <audio id="preview-audio-${v.id}" controls style="width:100%;margin-top:8px;display:none"></audio>
    </div>
  `).join('');
}

async function previewVoice(voiceId) {
  const text = document.querySelector(`[data-preview-text="${voiceId}"]`)?.value || '你好';
  const emotion = document.querySelector(`[data-preview-emotion="${voiceId}"]`)?.value || '';
  const fd = new FormData();
  fd.append('text', text);
  fd.append('emotion', emotion);
  try {
    const r = await api(`/api/voices/${voiceId}/preview`, { method: 'POST', body: fd });
    const audio = document.getElementById(`preview-audio-${voiceId}`);
    audio.src = audioUrl(r.audio_path);
    audio.style.display = 'block';
    audio.play();
  } catch (e) {
    toast('试听失败: ' + e.message, true);
  }
}

async function deleteVoice(id) {
  if (!confirm('确定删除此声音？')) return;
  await api(`/api/voices/${id}`, { method: 'DELETE' });
  loadVoices();
  toast('已删除');
}

document.getElementById('btnRefreshVoices').addEventListener('click', loadVoices);

document.getElementById('btnShowDesignModal').addEventListener('click', () => {
  document.getElementById('designModal').classList.add('show');
});
document.getElementById('btnShowCloneModal').addEventListener('click', () => {
  document.getElementById('cloneModal').classList.add('show');
});
document.querySelectorAll('.modal-close').forEach(b => {
  b.addEventListener('click', () => b.closest('.modal-overlay').classList.remove('show'));
});

document.getElementById('designForm').addEventListener('submit', async e => {
  e.preventDefault();
  try {
    await api('/api/voices/design', { method: 'POST', body: new FormData(e.target) });
    document.getElementById('designModal').classList.remove('show');
    e.target.reset();
    loadVoices();
    toast('设计声音已创建');
  } catch (err) {
    toast('创建失败: ' + err.message, true);
  }
});

document.getElementById('cloneForm').addEventListener('submit', async e => {
  e.preventDefault();
  try {
    await api('/api/voices/clone', { method: 'POST', body: new FormData(e.target) });
    document.getElementById('cloneModal').classList.remove('show');
    e.target.reset();
    loadVoices();
    toast('克隆声音已创建');
  } catch (err) {
    toast('创建失败: ' + err.message, true);
  }
});

// ---------- 推理设置 ----------
async function loadInferenceConfig() {
  const cfg = await api('/api/config');
  const inf = cfg.inference || cfg;
  const con = cfg.consistency || {};
  const form = document.getElementById('inferenceForm');
  ['temperature', 'top_p', 'top_k', 'repetition_penalty', 'max_new_tokens', 'language'].forEach(k => {
    const input = form.elements[k];
    if (input && inf[k] !== undefined) input.value = inf[k];
  });
  if (form.elements.pause_duration && cfg.audio) {
    form.elements.pause_duration.value = cfg.audio.pause_duration ?? 0.5;
  }
  if (form.elements.consistency_enabled) form.elements.consistency_enabled.checked = con.enabled !== false;
  if (form.elements.design_via_clone) form.elements.design_via_clone.checked = con.design_via_clone !== false;
  if (form.elements.stable_instruct) form.elements.stable_instruct.checked = con.stable_instruct !== false;
  if (form.elements.consistency_temperature && con.temperature != null) {
    form.elements.consistency_temperature.value = con.temperature;
  }
}

document.getElementById('inferenceForm').addEventListener('submit', async e => {
  e.preventDefault();
  const form = e.target;
  const body = {
    temperature: parseFloat(form.temperature.value),
    top_p: parseFloat(form.top_p.value),
    top_k: parseInt(form.top_k.value, 10),
    repetition_penalty: parseFloat(form.repetition_penalty.value),
    max_new_tokens: parseInt(form.max_new_tokens.value, 10),
    language: form.language.value,
    audio: { pause_duration: parseFloat(form.pause_duration.value) },
    consistency: {
      enabled: form.consistency_enabled?.checked ?? true,
      design_via_clone: form.design_via_clone?.checked ?? true,
      stable_instruct: form.stable_instruct?.checked ?? true,
      temperature: parseFloat(form.consistency_temperature?.value || '0.65'),
    },
  };
  try {
    await api('/api/config/inference', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    toast('推理参数已保存');
  } catch (err) {
    toast('保存失败: ' + err.message, true);
  }
});

document.getElementById('btnReloadConfig').addEventListener('click', async () => {
  await api('/api/config/reload', { method: 'POST' });
  loadInferenceConfig();
  toast('配置已重新加载');
});

document.addEventListener('DOMContentLoaded', () => {
  loadProjects();
  loadVoicesCache();
});

window.openWorkspace = openWorkspace;
window.deleteProject = deleteProject;
window.saveCharacterVoice = saveCharacterVoice;
window.generateLine = generateLine;
window.regenerateLine = regenerateLine;
window.saveLineEmotion = saveLineEmotion;
window.previewVoice = previewVoice;
window.deleteVoice = deleteVoice;

async function warmupVoice(voiceId) {
  try {
    const r = await api(`/api/voices/${voiceId}/warmup`, { method: 'POST' });
    toast(r.message || '预热完成');
  } catch (e) {
    toast('预热失败: ' + e.message, true);
  }
}
window.warmupVoice = warmupVoice;
