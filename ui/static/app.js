const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));
const state = { initialized: false, authenticated: false, listener: null, backends: [], certs: [], sni: [], http: [], versions: [] };

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, ch => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]));
}

function toast(message, bad = false) {
  const box = $('#toast');
  box.textContent = message;
  box.classList.remove('hidden');
  box.classList.toggle('toast-bad', bad);
  box.classList.toggle('toast-good', !bad);
  box.style.background = bad ? '#450a0a' : '#022c22';
  box.style.borderColor = bad ? '#ef4444' : '#14b8a6';
  clearTimeout(window.__toastTimer);
  window.__toastTimer = setTimeout(() => box.classList.add('hidden'), 4200);
}

async function api(path, options = {}) {
  const headers = options.headers || {};
  if (options.body && !(options.body instanceof FormData)) headers['Content-Type'] = 'application/json';
  const res = await fetch(path, { credentials: 'same-origin', ...options, headers });
  const text = await res.text();
  let data = text;
  try { data = text ? JSON.parse(text) : {}; } catch (_) {}
  if (!res.ok) {
    const detail = data && data.detail ? (Array.isArray(data.detail) ? JSON.stringify(data.detail) : data.detail) : text;
    throw new Error(detail || `HTTP ${res.status}`);
  }
  return data;
}

function formToObject(form) {
  updateConditionalFields(form.id);
  const obj = {};
  Array.from(form.elements).forEach((el) => {
    if (!el.name || el.disabled || el.type === 'button' || el.type === 'submit') return;
    if (el.type === 'checkbox') obj[el.name] = el.checked;
    else if (el.type === 'number') obj[el.name] = el.value === '' ? null : Number(el.value);
    else obj[el.name] = el.value === '' ? null : el.value;
  });
  if (obj.extra_options == null) obj.extra_options = '{}';
  if (Object.prototype.hasOwnProperty.call(obj, 'id')) delete obj.id;
  return obj;
}

function parseListInput(value) {
  return String(value || '').split(/[\s,，;；]+/).map(v => v.trim()).filter(Boolean);
}

function fillForm(formId, obj) {
  const form = document.getElementById(formId);
  Array.from(form.elements).forEach((el) => {
    if (!el.name || el.type === 'button' || el.type === 'submit') return;
    let value = obj[el.name];
    if (formId === 'listenerForm' && el.name === 'tcp_port' && Array.isArray(obj.tcp_ports)) value = obj.tcp_ports.join(',');
    if (formId === 'listenerForm' && el.name === 'udp_port' && Array.isArray(obj.udp_ports)) value = obj.udp_ports.join(',');
    if (el.type === 'checkbox') el.checked = Boolean(value);
    else el.value = value == null ? '' : value;
  });
  updateConditionalFields(formId);
  updateFormMode(formId);
  window.scrollTo({ top: form.getBoundingClientRect().top + window.scrollY - 110, behavior: 'smooth' });
}

function resetForm(id) {
  const form = document.getElementById(id);
  form.reset();
  const hidden = form.querySelector('input[name="id"]');
  if (hidden) hidden.value = '';
  const extra = form.querySelector('textarea[name="extra_options"]');
  if (extra) extra.value = '{}';
  if (id === 'backendForm') {
    form.elements.send_proxy_protocol.checked = false;
    form.elements.preserve_host.checked = true;
    form.elements.forward_real_ip.checked = true;
    form.elements.keepalive.value = 32;
    form.elements.connect_timeout.value = 60;
    form.elements.read_timeout.value = 3600;
    form.elements.send_timeout.value = 3600;
  }
  if (id === 'sniForm') {
    form.elements.enabled.checked = true;
    form.elements.priority.value = 100;
    form.elements.listener_id.value = state.listener ? state.listener.id : 1;
  }
  if (id === 'httpForm') {
    form.elements.enabled.checked = true;
    form.elements.priority.value = 100;
    form.elements.path.value = '/';
    form.elements.extra_options.value = '{}';
  }
  updateConditionalFields(id);
  updateFormMode(id);
}

function actionButtons(kind, item) {
  return `<button class="muted" data-edit="${kind}" data-id="${item.id}">编辑</button> <button class="danger" data-delete="${kind}" data-id="${item.id}">删除</button>`;
}

function renderTable(target, columns, rows, kind) {
  const html = rows.length ? `<table><thead><tr>${columns.map(c => `<th>${c.label}</th>`).join('')}<th>操作</th></tr></thead><tbody>${rows.map(row => `<tr>${columns.map(c => `<td>${c.render ? c.render(row) : (row[c.key] ?? '')}</td>`).join('')}<td>${actionButtons(kind, row)}</td></tr>`).join('')}</tbody></table>` : '<p class="hint">暂无数据</p>';
  document.getElementById(target).innerHTML = html;
}

function backendById(id) {
  return state.backends.find(b => String(b.id) === String(id));
}

function backendLabel(backend) {
  if (!backend) return '未选择后端';
  const proxy = backend.send_proxy_protocol ? ' · PROXY' : '';
  return `${backend.name} · ${backend.protocol} · ${backend.host}:${backend.port}${proxy}`;
}

function backendSummary(id) {
  if (!id) return '<span class="muted-text">未设置</span>';
  const backend = backendById(id);
  if (!backend) return `<span class="bad">后端 #${escapeHtml(id)} 不存在</span>`;
  return `${escapeHtml(backendLabel(backend))} <span class="muted-text">#${backend.id}</span>`;
}

function routeNameForSni(baseName, sni, index, total) {
  if (total <= 1) return baseName;
  const suffix = sni.replace(/[^A-Za-z0-9_.-]/g, '-');
  return `${baseName}-${index + 1}-${suffix}`.slice(0, 63);
}

function populateBackendSelects() {
  $$('select[data-backend-select]').forEach(select => {
    const current = select.value;
    const placeholder = select.dataset.placeholder || '请选择后端';
    const required = select.hasAttribute('required');
    const options = [`<option value="">${escapeHtml(required ? placeholder : `不使用后端 / ${placeholder}`)}</option>`];
    state.backends.forEach(backend => {
      options.push(`<option value="${backend.id}">${escapeHtml(backendLabel(backend))}</option>`);
    });
    select.innerHTML = options.join('');
    select.value = current;
    if (current && select.value !== current) select.value = '';
  });
}

function setFieldVisible(form, fieldName, visible) {
  const field = form.querySelector(`[data-field="${fieldName}"]`);
  if (!field) return;
  field.classList.toggle('field-hidden', !visible);
  field.querySelectorAll('input, select, textarea').forEach(el => {
    el.disabled = !visible;
    if (!visible) el.required = false;
  });
}

function updateConditionalFields(formId) {
  const form = document.getElementById(formId);
  if (!form) return;
  if (formId === 'listenerForm') {
    const useBackend = form.elements.default_sni_action.value === 'tls_passthrough';
    setFieldVisible(form, 'default_backend_id', useBackend);
    if (form.elements.default_backend_id) form.elements.default_backend_id.required = useBackend;
  }
  if (formId === 'sniForm') {
    const useBackend = form.elements.action.value === 'tls_passthrough';
    setFieldVisible(form, 'backend_id', useBackend);
    if (form.elements.backend_id) form.elements.backend_id.required = useBackend;
  }
  if (formId === 'httpForm') {
    const isGrpc = form.elements.backend_type.value === 'grpc';
    const modeField = form.querySelector('[name="http_mode"]')?.closest('label');
    if (modeField) {
      modeField.classList.toggle('field-hidden', isGrpc);
      form.elements.http_mode.disabled = isGrpc;
      if (isGrpc) form.elements.http_mode.value = '';
      else if (!form.elements.http_mode.value) form.elements.http_mode.value = 'normal';
    }
  }
}

function updateAllConditionalFields() {
  ['listenerForm', 'sniForm', 'httpForm'].forEach(updateConditionalFields);
}

function updateFormMode(formId) {
  const form = document.getElementById(formId);
  const mode = document.getElementById(`${formId.replace('Form', '')}FormMode`);
  if (!form || !mode || !form.elements.id) return;
  const editing = Boolean(form.elements.id.value);
  const names = { backendForm: '后端', certForm: '证书', sniForm: 'SNI 规则', httpForm: 'HTTP 路由' };
  const itemName = form.elements.name && form.elements.name.value ? `：${form.elements.name.value}` : '';
  mode.textContent = editing ? `正在编辑${names[formId]}${itemName}` : `新建${names[formId]}`;
  mode.classList.toggle('editing', editing);
}

function renderVersions() {
  const rows = state.versions || [];
  const html = rows.length ? `<table><thead><tr><th>ID</th><th>版本</th><th>状态</th><th>生成时间</th><th>结果</th><th>操作</th></tr></thead><tbody>${rows.map(v => `<tr><td>${v.id}</td><td>${v.version}</td><td>${v.status}</td><td>${v.generated_at}</td><td>${(v.test_result || v.error_log || '').slice(0, 120)}</td><td><button class="muted" data-rollback="${v.id}">回滚</button></td></tr>`).join('')}</tbody></table>` : '<p class="hint">暂无配置版本</p>';
  $('#versionsTable').innerHTML = html;
}

function renderSniTable() {
  const groups = new Map();
  state.sni.forEach(row => {
    const key = [row.enabled, row.priority, row.alpn || '', row.action, row.backend_id || ''].join('|');
    if (!groups.has(key)) groups.set(key, { ...row, ids: [], sni_values: [] });
    const group = groups.get(key);
    group.ids.push(row.id);
    group.sni_values.push(row.sni);
  });
  const rows = Array.from(groups.values());
  const html = rows.length ? `<table><thead><tr><th>ID</th><th>启用</th><th>优先级</th><th>SNI</th><th>ALPN</th><th>动作</th><th>目标后端</th><th>操作</th></tr></thead><tbody>${rows.map(row => `<tr><td>${row.ids.map(escapeHtml).join(', ')}</td><td>${row.enabled ? '是' : '否'}</td><td>${row.priority}</td><td>${row.sni_values.map(escapeHtml).join('<br>')}</td><td>${escapeHtml(row.alpn || '')}</td><td>${escapeHtml(row.action)}</td><td>${backendSummary(row.backend_id)}</td><td><button class="muted" data-edit="sni" data-id="${row.ids[0]}">编辑首条</button> <button class="danger" data-delete-sni-group="${row.ids.join(',')}">删除本组</button></td></tr>`).join('')}</tbody></table>` : '<p class="hint">暂无数据</p>';
  $('#sniTable').innerHTML = html;
}

function renderAllTables() {
  populateBackendSelects();
  updateAllConditionalFields();
  renderTable('backendsTable', [
    { key: 'id', label: 'ID' }, { key: 'name', label: '名称' }, { key: 'host', label: '地址' }, { key: 'port', label: '端口' }, { key: 'protocol', label: '协议' },
    { key: 'tls_to_backend', label: 'TLS', render: r => r.tls_to_backend ? '是' : '否' }, { key: 'send_proxy_protocol', label: 'PROXY', render: r => r.send_proxy_protocol ? '是' : '否' }, { key: 'read_timeout', label: '读超时' }
  ], state.backends, 'backend');
  renderTable('certsTable', [
    { key: 'id', label: 'ID' }, { key: 'name', label: '名称' }, { key: 'domain', label: '域名' }, { key: 'cert_path', label: '证书' }, { key: 'key_path', label: '私钥' }
  ], state.certs, 'cert');
  renderSniTable();
  renderTable('httpTable', [
    { key: 'id', label: 'ID' }, { key: 'enabled', label: '启用', render: r => r.enabled ? '是' : '否' }, { key: 'priority', label: '优先级' }, { key: 'host', label: 'Host' },
    { key: 'path', label: 'Path' }, { key: 'match_type', label: '匹配' }, { key: 'backend_type', label: '后端类型' }, { key: 'http_mode', label: 'HTTP 模式' }, { key: 'backend_id', label: '目标后端', render: r => backendSummary(r.backend_id) }
  ], state.http, 'http');
  renderVersions();
}

async function loadAuthState() {
  const auth = await api('/api/auth/state');
  Object.assign(state, auth);
  $('#authStatus').textContent = auth.authenticated ? `已登录：${auth.username}` : (auth.initialized ? '未登录' : '未初始化');
  $('#authPanel').classList.toggle('hidden', auth.authenticated);
  $('#appPanel').classList.toggle('hidden', !auth.authenticated);
  $('#authTitle').textContent = auth.initialized ? '登录' : '初始化管理员';
  const password = $('#authForm input[name="password"]');
  password.minLength = auth.initialized ? 1 : 12;
  password.autocomplete = auth.initialized ? 'current-password' : 'new-password';
  if (auth.authenticated) await refreshAll();
}

async function refreshAll() {
  state.listener = await api('/api/listener');
  if ($('#sniForm').elements.listener_id) $('#sniForm').elements.listener_id.value = state.listener.id;
  state.backends = await api('/api/backends');
  state.certs = await api('/api/certificates');
  state.sni = await api('/api/sni-routes');
  state.http = await api('/api/http-routes');
  state.versions = await api('/api/config/versions');
  populateBackendSelects();
  fillForm('listenerForm', state.listener);
  renderAllTables();
  await refreshPreview(false);
}

async function refreshPreview(showToast = true) {
  const preview = await api('/api/config/preview');
  $('#httpPreview').textContent = preview.http;
  $('#streamPreview').textContent = preview.stream;
  if (showToast) toast('配置预览已刷新');
}

async function submitAuth(ev) {
  ev.preventDefault();
  const form = ev.currentTarget;
  const body = formToObject(form);
  try {
    await api(state.initialized ? '/api/auth/login' : '/api/auth/init', { method: 'POST', body: JSON.stringify(body) });
    form.reset();
    await loadAuthState();
    toast('认证成功');
  } catch (err) { toast(err.message, true); }
}

async function submitListener(ev) {
  ev.preventDefault();
  try {
    await api('/api/listener', { method: 'PUT', body: JSON.stringify(formToObject(ev.currentTarget)) });
    await refreshAll();
    toast('入口设置已保存');
  } catch (err) { toast(err.message, true); }
}

const endpoints = {
  backend: { base: '/api/backends', form: 'backendForm', data: () => state.backends },
  cert: { base: '/api/certificates', form: 'certForm', data: () => state.certs },
  sni: { base: '/api/sni-routes', form: 'sniForm', data: () => state.sni },
  http: { base: '/api/http-routes', form: 'httpForm', data: () => state.http },
};

function endpointByForm(formId) {
  return Object.entries(endpoints).find(([, cfg]) => cfg.form === formId);
}

async function submitCrud(ev) {
  ev.preventDefault();
  const form = ev.currentTarget;
  const entry = endpointByForm(form.id);
  if (!entry) return;
  const [kind, cfg] = entry;
  const id = form.elements.id ? form.elements.id.value : '';
  const payload = formToObject(form);
  try {
    if (kind === 'sni') {
      const sniValues = parseListInput(payload.sni);
      if (!sniValues.length) throw new Error('至少需要一个 SNI 域名');
    if (id) {
      await api(`${cfg.base}/${id}`, { method: 'PUT', body: JSON.stringify({ ...payload, sni: sniValues[0] }) });
      for (const sni of sniValues.slice(1)) {
          await api(cfg.base, { method: 'POST', body: JSON.stringify({ ...payload, name: routeNameForSni(payload.name, sni, sniValues.indexOf(sni), sniValues.length), sni }) });
      }
    } else {
        for (let i = 0; i < sniValues.length; i += 1) {
          const sni = sniValues[i];
          await api(cfg.base, { method: 'POST', body: JSON.stringify({ ...payload, name: routeNameForSni(payload.name, sni, i, sniValues.length), sni }) });
        }
      }
    } else {
      await api(id ? `${cfg.base}/${id}` : cfg.base, { method: id ? 'PUT' : 'POST', body: JSON.stringify(payload) });
    }
    resetForm(form.id);
    await refreshAll();
    toast(kind === 'sni' ? 'SNI 规则已保存' : `${kind} 已保存`);
  } catch (err) { toast(err.message, true); }
}

async function deleteItem(kind, id) {
  const cfg = endpoints[kind];
  if (!cfg) return;
  if (!confirm(`确认删除 ${kind} #${id}？`)) return;
  try {
    await api(`${cfg.base}/${id}`, { method: 'DELETE' });
    await refreshAll();
    toast('已删除');
  } catch (err) { toast(err.message, true); }
}

async function deleteSniGroup(ids) {
  const idList = ids.split(',').map(v => v.trim()).filter(Boolean);
  if (!idList.length) return;
  if (!confirm(`确认删除本组 ${idList.length} 条 SNI 规则？`)) return;
  try {
    for (const id of idList) await api(`/api/sni-routes/${id}`, { method: 'DELETE' });
    await refreshAll();
    toast('SNI 规则组已删除');
  } catch (err) { toast(err.message, true); }
}

function editItem(kind, id) {
  const cfg = endpoints[kind];
  const item = cfg.data().find(x => String(x.id) === String(id));
  if (!item) return;
  fillForm(cfg.form, item);
}

async function applyConfig() {
  if (!confirm('将写入生成目录、执行 nginx -t 并 reload。确认应用？')) return;
  $('#applyResult').textContent = '正在应用...';
  try {
    const result = await api('/api/config/apply', { method: 'POST', body: '{}' });
    $('#applyResult').textContent = `ok=${result.ok}\nversion=${result.version || ''}\n${result.test_result || ''}\n${result.error_log || ''}`;
    state.versions = await api('/api/config/versions');
    renderVersions();
    toast(result.ok ? '配置已应用' : '配置测试或 reload 失败', !result.ok);
  } catch (err) {
    $('#applyResult').textContent = err.message;
    toast(err.message, true);
  }
}

async function rollback(id) {
  if (!confirm(`确认回滚到版本 ID ${id}？`)) return;
  try {
    const result = await api(`/api/config/rollback/${id}`, { method: 'POST', body: '{}' });
    $('#applyResult').textContent = `rollback ok=${result.ok}\nversion=${result.version || ''}\n${result.test_result || ''}\n${result.error_log || ''}`;
    state.versions = await api('/api/config/versions');
    renderVersions();
    toast(result.ok ? '回滚完成' : '回滚失败', !result.ok);
  } catch (err) { toast(err.message, true); }
}

async function loadLogs() {
  try {
    const text = await api('/api/logs/error.log?lines=300');
    $('#logOutput').textContent = text || '(无日志或日志文件不存在)';
  } catch (err) { toast(err.message, true); }
}

async function exportConfig() {
  try {
    const bundle = await api('/api/config/export');
    const blob = new Blob([JSON.stringify(bundle, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `omni-proxygate-config-${new Date().toISOString().replace(/[:.]/g, '-')}.json`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    toast('配置已导出');
  } catch (err) { toast(err.message, true); }
}

async function importConfig(file) {
  if (!file) return;
  if (!confirm('导入会替换当前所有入口、后端、证书、SNI 和 HTTP 路由配置。确认继续？')) return;
  try {
    const bundle = JSON.parse(await file.text());
    const result = await api('/api/config/import', { method: 'POST', body: JSON.stringify(bundle) });
    await refreshAll();
    toast(`导入完成：后端 ${result.backends}，SNI ${result.sni_routes}，HTTP ${result.http_routes}`);
  } catch (err) { toast(`导入失败：${err.message}`, true); }
}

function initEvents() {
  $('#authForm').addEventListener('submit', submitAuth);
  $('#listenerForm').addEventListener('submit', submitListener);
  ['backendForm', 'certForm', 'sniForm', 'httpForm'].forEach(id => document.getElementById(id).addEventListener('submit', submitCrud));
  ['listenerForm', 'sniForm', 'httpForm'].forEach(id => {
    const form = document.getElementById(id);
    form.addEventListener('change', () => updateConditionalFields(id));
  });
  $$('[data-reset]').forEach(btn => btn.addEventListener('click', () => resetForm(btn.dataset.reset)));
  $$('.tabs button[data-tab]').forEach(btn => btn.addEventListener('click', () => {
    $$('.tabs button[data-tab]').forEach(b => b.classList.remove('active'));
    $$('.tab').forEach(t => t.classList.remove('active'));
    btn.classList.add('active');
    $(`#tab-${btn.dataset.tab}`).classList.add('active');
  }));
  document.body.addEventListener('click', (ev) => {
    const edit = ev.target.closest('[data-edit]');
    const del = ev.target.closest('[data-delete]');
    const delSniGroup = ev.target.closest('[data-delete-sni-group]');
    const rb = ev.target.closest('[data-rollback]');
    if (edit) editItem(edit.dataset.edit, edit.dataset.id);
    if (del) deleteItem(del.dataset.delete, del.dataset.id);
    if (delSniGroup) deleteSniGroup(delSniGroup.dataset.deleteSniGroup);
    if (rb) rollback(rb.dataset.rollback);
  });
  $('#previewBtn').addEventListener('click', () => refreshPreview(true));
  $('#applyBtn').addEventListener('click', applyConfig);
  $('#logsBtn').addEventListener('click', loadLogs);
  $('#exportBtn').addEventListener('click', exportConfig);
  $('#importBtn').addEventListener('click', () => $('#importFile').click());
  $('#importFile').addEventListener('change', ev => {
    importConfig(ev.currentTarget.files[0]);
    ev.currentTarget.value = '';
  });
  $('#logoutBtn').addEventListener('click', async () => {
    await api('/api/auth/logout', { method: 'POST', body: '{}' });
    await loadAuthState();
  });
}

document.addEventListener('DOMContentLoaded', async () => {
  initEvents();
  try { await loadAuthState(); } catch (err) { toast(err.message, true); }
});
