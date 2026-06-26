const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));
const state = { initialized: false, authenticated: false, listener: null, backends: [], certs: [], sni: [], http: [], versions: [], table: {}, dirty: false };

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

function setFormMessage(form, message = '', bad = false) {
  let box = form.querySelector('[data-form-message]');
  if (!box) {
    box = document.createElement('div');
    box.dataset.formMessage = 'true';
    box.className = 'form-message hidden';
    form.prepend(box);
  }
  box.textContent = message;
  box.classList.toggle('hidden', !message);
  box.classList.toggle('form-message-bad', bad);
  box.classList.toggle('form-message-good', Boolean(message) && !bad);
}

function setSubmitting(form, submitting) {
  const submit = form.querySelector('button[type="submit"]');
  if (!submit) return;
  if (submitting) {
    submit.dataset.label = submit.textContent;
    submit.textContent = '保存中...';
    submit.disabled = true;
  } else {
    submit.textContent = submit.dataset.label || submit.textContent;
    submit.disabled = false;
  }
}

function setDirty(value) {
  state.dirty = Boolean(value);
  const badge = $('#dirtyBadge');
  if (badge) badge.classList.toggle('hidden', !state.dirty);
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
  syncAlpnInput(form);
  const obj = {};
  Array.from(form.elements).forEach((el) => {
    if (!el.name || el.disabled || el.type === 'button' || el.type === 'submit') return;
    if (el.type === 'checkbox') obj[el.name] = el.checked;
    else if (el.type === 'number') obj[el.name] = el.value === '' ? null : Number(el.value);
    else obj[el.name] = el.value === '' ? null : el.value;
  });
  if (obj.extra_options == null) obj.extra_options = '{}';
  if (Object.prototype.hasOwnProperty.call(obj, 'id')) delete obj.id;
  if (Object.prototype.hasOwnProperty.call(obj, 'group_ids')) delete obj.group_ids;
  return obj;
}

function parseListInput(value) {
  return [...new Set(String(value || '').split(/[\s,，;；]+/).map(v => v.trim()).filter(Boolean))];
}

function groupIdsFromForm(form) {
  const raw = form.elements.group_ids ? form.elements.group_ids.value : '';
  return parseListInput(raw);
}

function certNameForDomain(baseName, domain, index, total) {
  if (total <= 1) return baseName;
  const suffix = domain.replace(/[^A-Za-z0-9_.-]/g, '-').replace(/^\*\./, 'wild-');
  return `${baseName}-${index + 1}-${suffix}`.slice(0, 63);
}

function alpnValues(value) {
  return parseListInput(String(value || '').replace(/,/g, ' '));
}

function syncAlpnChips(form) {
  if (!form || form.id !== 'sniForm') return;
  const values = new Set(alpnValues(form.elements.alpn.value));
  form.querySelectorAll('[data-alpn]').forEach(btn => btn.classList.toggle('selected', values.has(btn.dataset.alpn)));
}

function syncAlpnInput(form) {
  if (!form || form.id !== 'sniForm') return;
  const values = Array.from(form.querySelectorAll('[data-alpn].selected')).map(btn => btn.dataset.alpn);
  form.elements.alpn.value = values.join(',');
}

function fillForm(formId, obj) {
  const form = document.getElementById(formId);
  Array.from(form.elements).forEach((el) => {
    if (!el.name || el.type === 'button' || el.type === 'submit') return;
    let value = obj[el.name];
    if (formId === 'listenerForm' && el.name === 'tcp_port' && Array.isArray(obj.tcp_ports)) value = obj.tcp_ports.join(',');
    if (formId === 'listenerForm' && el.name === 'udp_port' && Array.isArray(obj.udp_ports)) value = obj.udp_ports.join(',');
    if (el.type === 'checkbox') el.checked = Boolean(value);
    else if (el.name === 'domain' && Array.isArray(value)) el.value = value.join('\n');
    else if (el.name === 'sni' && Array.isArray(value)) el.value = value.join('\n');
    else el.value = value == null ? '' : value;
  });
  syncAlpnChips(form);
  updateConditionalFields(formId);
  updateFormMode(formId);
  window.scrollTo({ top: form.getBoundingClientRect().top + window.scrollY - 110, behavior: 'smooth' });
}

function resetForm(id) {
  const form = document.getElementById(id);
  form.reset();
  const hidden = form.querySelector('input[name="id"]');
  if (hidden) hidden.value = '';
  const groupIds = form.querySelector('input[name="group_ids"]');
  if (groupIds) groupIds.value = '';
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
    form.elements.alpn.value = '';
    syncAlpnChips(form);
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

function cellText(column, row) {
  if (column.text) return column.text(row);
  const raw = row[column.key];
  return Array.isArray(raw) ? raw.join(' ') : String(raw ?? '');
}

function tableState(target) {
  if (!state.table[target]) state.table[target] = { q: '', sort: '', dir: 'asc' };
  return state.table[target];
}

function prepareRows(target, columns, rows) {
  const ts = tableState(target);
  let filtered = rows;
  const q = ts.q.trim().toLowerCase();
  if (q) filtered = rows.filter(row => columns.some(c => cellText(c, row).toLowerCase().includes(q)));
  if (ts.sort) {
    const col = columns.find(c => c.key === ts.sort || c.sortKey === ts.sort);
    if (col) {
      const key = col.sortKey || col.key;
      filtered = [...filtered].sort((a, b) => {
        const av = col.sortValue ? col.sortValue(a) : (a[key] ?? '');
        const bv = col.sortValue ? col.sortValue(b) : (b[key] ?? '');
        const cmp = String(av).localeCompare(String(bv), undefined, { numeric: true, sensitivity: 'base' });
        return ts.dir === 'desc' ? -cmp : cmp;
      });
    }
  }
  return filtered;
}

function renderTableControls(target, columns, rows) {
  const ts = tableState(target);
  const sortable = columns.filter(c => c.sortable !== false);
  return `<div class="table-tools" data-table-tools="${target}">
    <label class="table-search">搜索 <input data-table-search="${target}" value="${escapeHtml(ts.q)}" placeholder="按名称、域名、后端、路径过滤" /></label>
    <label class="table-sort">排序 <select data-table-sort="${target}"><option value="">默认</option>${sortable.map(c => `<option value="${escapeHtml(c.sortKey || c.key)}" ${ts.sort === (c.sortKey || c.key) ? 'selected' : ''}>${escapeHtml(c.label)}</option>`).join('')}</select></label>
    <button type="button" class="muted compact" data-table-dir="${target}">${ts.dir === 'desc' ? '降序' : '升序'}</button>
    <span class="table-count">${prepareRows(target, columns, rows).length} / ${rows.length}</span>
  </div>`;
}

function renderTable(target, columns, rows, kind) {
  const displayRows = prepareRows(target, columns, rows);
  const body = displayRows.length ? `<table><thead><tr>${columns.map(c => `<th>${c.label}</th>`).join('')}<th>操作</th></tr></thead><tbody>${displayRows.map(row => `<tr>${columns.map(c => `<td>${c.render ? c.render(row) : escapeHtml(row[c.key] ?? '')}</td>`).join('')}<td>${actionButtons(kind, row)}</td></tr>`).join('')}</tbody></table>` : '<p class="hint">暂无匹配数据</p>';
  document.getElementById(target).innerHTML = renderTableControls(target, columns, rows) + body;
}

function renderTableByTarget(target) {
  if (target === 'backendsTable') {
    renderTable('backendsTable', [
      { key: 'id', label: 'ID' }, { key: 'name', label: '名称' }, { key: 'host', label: '地址' }, { key: 'port', label: '端口' }, { key: 'protocol', label: '协议' },
      { key: 'tls_to_backend', label: 'TLS', render: r => r.tls_to_backend ? '是' : '否' }, { key: 'send_proxy_protocol', label: 'PROXY', render: r => r.send_proxy_protocol ? '是' : '否' }, { key: 'read_timeout', label: '读超时' }
    ], state.backends, 'backend');
  } else if (target === 'certsTable') {
    renderCertTable();
  } else if (target === 'sniTable') {
    renderSniTable();
  } else if (target === 'httpTable') {
    renderTable('httpTable', [
      { key: 'id', label: 'ID' }, { key: 'enabled', label: '启用', render: r => r.enabled ? '是' : '否' }, { key: 'priority', label: '优先级' }, { key: 'host', label: 'Host' },
      { key: 'path', label: 'Path' }, { key: 'match_type', label: '匹配' }, { key: 'backend_type', label: '后端类型' }, { key: 'http_mode', label: 'HTTP 模式' }, { key: 'backend_id', label: '目标后端', render: r => backendSummary(r.backend_id) }
    ], state.http, 'http');
  }
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

function groupCerts() {
  const groups = new Map();
  state.certs.forEach(row => {
    const key = [row.cert_path, row.key_path, row.managed_by_system].join('|');
    if (!groups.has(key)) groups.set(key, { ...row, ids: [], domains: [], names: [] });
    const group = groups.get(key);
    group.ids.push(row.id);
    group.domains.push(row.domain);
    group.names.push(row.name);
  });
  return Array.from(groups.values());
}

function renderCertTable() {
  const rows = groupCerts();
  const columns = [
    { key: 'ids', label: 'ID', render: r => r.ids.map(escapeHtml).join(', '), text: r => r.ids.join(' ') },
    { key: 'names', label: '名称', render: r => r.names.map(escapeHtml).join('<br>'), text: r => r.names.join(' ') },
    { key: 'domains', label: '域名', render: r => `<div class="chip-list">${r.domains.map(v => `<span class="mini-chip">${escapeHtml(v)}</span>`).join('')}</div>`, text: r => r.domains.join(' ') },
    { key: 'cert_path', label: '证书' },
    { key: 'key_path', label: '私钥' },
  ];
  const displayRows = prepareRows('certsTable', columns, rows);
  const body = displayRows.length ? `<table><thead><tr>${columns.map(c => `<th>${c.label}</th>`).join('')}<th>操作</th></tr></thead><tbody>${displayRows.map(row => `<tr>${columns.map(c => `<td>${c.render ? c.render(row) : escapeHtml(row[c.key] ?? '')}</td>`).join('')}<td><button class="muted" data-edit-cert-group="${row.ids.join(',')}">编辑本组</button> <button class="danger" data-delete-cert-group="${row.ids.join(',')}">删除本组</button></td></tr>`).join('')}</tbody></table>` : '<p class="hint">暂无匹配数据</p>';
  $('#certsTable').innerHTML = renderTableControls('certsTable', columns, rows) + body;
}

function groupSniRoutes() {
  const groups = new Map();
  state.sni.forEach(row => {
    const key = [row.enabled, row.priority, row.alpn || '', row.action, row.backend_id || ''].join('|');
    if (!groups.has(key)) groups.set(key, { ...row, ids: [], names: [], sni_values: [] });
    const group = groups.get(key);
    group.ids.push(row.id);
    group.names.push(row.name);
    group.sni_values.push(row.sni);
  });
  return Array.from(groups.values());
}

function renderSniTable() {
  const rows = groupSniRoutes();
  const columns = [
    { key: 'ids', label: 'ID', render: r => r.ids.map(escapeHtml).join(', '), text: r => r.ids.join(' ') },
    { key: 'enabled', label: '启用', render: r => r.enabled ? '是' : '否' },
    { key: 'priority', label: '优先级' },
    { key: 'sni_values', label: 'SNI', render: r => `<div class="chip-list">${r.sni_values.map(v => `<span class="mini-chip">${escapeHtml(v)}</span>`).join('')}</div>`, text: r => r.sni_values.join(' ') },
    { key: 'alpn', label: 'ALPN', render: r => r.alpn ? `<div class="chip-list">${alpnValues(r.alpn).map(v => `<span class="mini-chip accent">${escapeHtml(v)}</span>`).join('')}</div>` : '<span class="muted-text">不限</span>' },
    { key: 'action', label: '动作' },
    { key: 'backend_id', label: '目标后端', render: r => backendSummary(r.backend_id), text: r => backendLabel(backendById(r.backend_id)) },
  ];
  const displayRows = prepareRows('sniTable', columns, rows);
  const body = displayRows.length ? `<table><thead><tr>${columns.map(c => `<th>${c.label}</th>`).join('')}<th>操作</th></tr></thead><tbody>${displayRows.map(row => `<tr>${columns.map(c => `<td>${c.render ? c.render(row) : escapeHtml(row[c.key] ?? '')}</td>`).join('')}<td><button class="muted" data-edit-sni-group="${row.ids.join(',')}">编辑本组</button> <button class="danger" data-delete-sni-group="${row.ids.join(',')}">删除本组</button></td></tr>`).join('')}</tbody></table>` : '<p class="hint">暂无匹配数据</p>';
  $('#sniTable').innerHTML = renderTableControls('sniTable', columns, rows) + body;
}

function renderAllTables() {
  populateBackendSelects();
  updateAllConditionalFields();
  ['backendsTable', 'certsTable', 'sniTable', 'httpTable'].forEach(renderTableByTarget);
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
  const form = ev.currentTarget;
  setFormMessage(form);
  setSubmitting(form, true);
  try {
    await api('/api/listener', { method: 'PUT', body: JSON.stringify(formToObject(form)) });
    await refreshAll();
    setDirty(true);
    setFormMessage(form, '入口设置已保存，预览 / 应用页会显示待应用。');
    toast('入口设置已保存');
  } catch (err) {
    setFormMessage(form, err.message, true);
    toast(err.message, true);
  } finally {
    setSubmitting(form, false);
  }
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
  setFormMessage(form);
  setSubmitting(form, true);
  try {
    const entry = endpointByForm(form.id);
    if (!entry) return;
    const [kind, cfg] = entry;
    const id = form.elements.id ? form.elements.id.value : '';
    const groupIds = groupIdsFromForm(form);
    const payload = formToObject(form);
    if (kind === 'sni') {
      const sniValues = parseListInput(payload.sni);
      if (!sniValues.length) throw new Error('至少需要一个 SNI 域名');
      const idsToReplace = groupIds.length ? groupIds : (id ? [id] : []);
      for (const oldId of idsToReplace) await api(`${cfg.base}/${oldId}`, { method: 'DELETE' });
      for (let i = 0; i < sniValues.length; i += 1) {
        const sni = sniValues[i];
        await api(cfg.base, { method: 'POST', body: JSON.stringify({ ...payload, name: routeNameForSni(payload.name, sni, i, sniValues.length), sni }) });
      }
    } else if (kind === 'cert') {
      const domains = parseListInput(payload.domain);
      if (!domains.length) throw new Error('至少需要一个证书域名');
      const idsToReplace = groupIds.length ? groupIds : (id ? [id] : []);
      const certificates = domains.map((domain, i) => ({ ...payload, name: certNameForDomain(payload.name, domain, i, domains.length), domain }));
      await api(`${cfg.base}/bulk-replace`, { method: 'POST', body: JSON.stringify({ replace_ids: idsToReplace.map(Number), certificates }) });
    } else {
      await api(id ? `${cfg.base}/${id}` : cfg.base, { method: id ? 'PUT' : 'POST', body: JSON.stringify(payload) });
    }
    resetForm(form.id);
    await refreshAll();
    setDirty(true);
    setFormMessage(form, kind === 'sni' ? 'SNI 规则已保存，预览 / 应用页会显示待应用。' : kind === 'cert' ? '证书已保存，预览 / 应用页会显示待应用。' : '已保存，预览 / 应用页会显示待应用。');
    toast(kind === 'sni' ? 'SNI 规则已保存' : kind === 'cert' ? '证书已保存' : `${kind} 已保存`);
  } catch (err) {
    setFormMessage(form, err.message, true);
    toast(err.message, true);
  } finally {
    setSubmitting(form, false);
  }
}

async function deleteItem(kind, id) {
  const cfg = endpoints[kind];
  if (!cfg) return;
  if (!confirm(`确认删除 ${kind} #${id}？`)) return;
  try {
    await api(`${cfg.base}/${id}`, { method: 'DELETE' });
    await refreshAll();
    setDirty(true);
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
    setDirty(true);
    toast('SNI 规则组已删除');
  } catch (err) { toast(err.message, true); }
}

async function deleteCertGroup(ids) {
  const idList = ids.split(',').map(v => v.trim()).filter(Boolean);
  if (!idList.length) return;
  if (!confirm(`确认删除本组 ${idList.length} 条证书域名？`)) return;
  try {
    for (const id of idList) await api(`/api/certificates/${id}`, { method: 'DELETE' });
    await refreshAll();
    setDirty(true);
    toast('证书组已删除');
  } catch (err) { toast(err.message, true); }
}

function editSniGroup(ids) {
  const idList = ids.split(',').map(v => v.trim()).filter(Boolean);
  const items = state.sni.filter(x => idList.includes(String(x.id)));
  if (!items.length) return;
  const first = items[0];
  fillForm('sniForm', { ...first, id: first.id, group_ids: idList.join(','), name: first.names ? first.names[0] : first.name.replace(/-\d+-.*$/, ''), sni: items.map(x => x.sni), alpn: first.alpn || '' });
}

function editCertGroup(ids) {
  const idList = ids.split(',').map(v => v.trim()).filter(Boolean);
  const items = state.certs.filter(x => idList.includes(String(x.id)));
  if (!items.length) return;
  const first = items[0];
  fillForm('certForm', { ...first, id: first.id, group_ids: idList.join(','), name: first.names ? first.names[0] : first.name.replace(/-\d+-.*$/, ''), domain: items.map(x => x.domain) });
}

function refreshTableControl(target, restoreFocus = false) {
  const active = restoreFocus ? document.activeElement : null;
  const selectionStart = active && typeof active.selectionStart === 'number' ? active.selectionStart : null;
  renderTableByTarget(target);
  if (restoreFocus) {
    const next = document.querySelector(`[data-table-search="${target}"]`);
    if (next) {
      next.focus();
      if (selectionStart != null) next.setSelectionRange(selectionStart, selectionStart);
    }
  }
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
    if (result.ok) setDirty(false);
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
    if (result.ok) setDirty(false);
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
    setDirty(true);
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
    $$('.tabs button[data-tab]').forEach(b => b.setAttribute('aria-selected', 'false'));
    $$('.tab').forEach(t => t.classList.remove('active'));
    btn.classList.add('active');
    btn.setAttribute('aria-selected', 'true');
    $(`#tab-${btn.dataset.tab}`).classList.add('active');
  }));
  document.body.addEventListener('click', (ev) => {
    const edit = ev.target.closest('[data-edit]');
    const del = ev.target.closest('[data-delete]');
    const delSniGroup = ev.target.closest('[data-delete-sni-group]');
    const delCertGroup = ev.target.closest('[data-delete-cert-group]');
    const editSniGroupBtn = ev.target.closest('[data-edit-sni-group]');
    const editCertGroupBtn = ev.target.closest('[data-edit-cert-group]');
    const sortDir = ev.target.closest('[data-table-dir]');
    const rb = ev.target.closest('[data-rollback]');
    if (edit) editItem(edit.dataset.edit, edit.dataset.id);
    if (del) deleteItem(del.dataset.delete, del.dataset.id);
    if (delSniGroup) deleteSniGroup(delSniGroup.dataset.deleteSniGroup);
    if (delCertGroup) deleteCertGroup(delCertGroup.dataset.deleteCertGroup);
    if (editSniGroupBtn) editSniGroup(editSniGroupBtn.dataset.editSniGroup);
    if (editCertGroupBtn) editCertGroup(editCertGroupBtn.dataset.editCertGroup);
    if (sortDir) { const target = sortDir.dataset.tableDir; const ts = tableState(target); ts.dir = ts.dir === 'desc' ? 'asc' : 'desc'; refreshTableControl(target); }
    if (rb) rollback(rb.dataset.rollback);
  });
  document.body.addEventListener('input', (ev) => {
    const search = ev.target.closest('[data-table-search]');
    if (search) { tableState(search.dataset.tableSearch).q = search.value; refreshTableControl(search.dataset.tableSearch, true); }
  });
  document.body.addEventListener('change', (ev) => {
    const sort = ev.target.closest('[data-table-sort]');
    if (sort) { tableState(sort.dataset.tableSort).sort = sort.value; refreshTableControl(sort.dataset.tableSort); }
  });
  document.body.addEventListener('click', (ev) => {
    const chip = ev.target.closest('[data-alpn]');
    if (chip) { chip.classList.toggle('selected'); syncAlpnInput(document.getElementById('sniForm')); }
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
  window.addEventListener('error', ev => toast(ev.message || '前端脚本错误', true));
  window.addEventListener('unhandledrejection', ev => toast(ev.reason?.message || String(ev.reason || '前端异步错误'), true));
  initEvents();
  try { await loadAuthState(); } catch (err) { toast(err.message, true); }
});
