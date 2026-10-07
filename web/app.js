'use strict';

const $ = (id) => document.getElementById(id);
const state = {
  products: [], movements: [], loaded: false, view: 'inventory',
  editing: null, editingMetadata: null, adjusting: null, labeling: null,
  stockBusy: false, pendingStock: null, refreshing: false, toastTimer: null,
};
const stockStorageKey = 'windowstock.pendingStock';
const maxStockQuantity = 1000000000;
try {
  const saved = JSON.parse(sessionStorage.getItem(stockStorageKey) || 'null');
  if (saved && ['receive', 'sale', 'adjust'].includes(saved.origin)
    && typeof saved.payload?.barcode === 'string' && typeof saved.payload?.request_id === 'string'
    && ['receipt', 'sale', 'return', 'correction'].includes(saved.payload.kind)) state.pendingStock = saved;
} catch { /* The page still provides retry protection if session storage is unavailable. */ }

function rememberStockRequest(request) {
  try {
    if (request) sessionStorage.setItem(stockStorageKey, JSON.stringify(request));
    else sessionStorage.removeItem(stockStorageKey);
  } catch { /* Keep the current page usable when storage is unavailable. */ }
}

const viewDetails = {
  inventory: ['YOUR STOCK, AT A GLANCE', 'Inventory', 'A clear view of every product and the units on your shelves.'],
  receive: ['FROM DELIVERY TO SHELF', 'Receive stock', 'Add new stock or a returned item using its product barcode.'],
  sale: ['FROM SHELF TO CUSTOMER', 'Record sale', 'Keep your inventory up to date with every sale.'],
  history: ['EVERY MOVEMENT, RECORDED', 'Stock history', 'Follow the receipts, sales, returns, and corrections behind your quantities.'],
};

const icons = {
  edit: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m14 5 5 5M4 20l4-1L20 7l-5-5L3 14z"/></svg>',
  labels: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 8V3h12v5M6 17H3V9h18v8h-3M6 14h12v7H6zm11-3h1"/></svg>',
  copy: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 8h12v13H8zM4 16H2V2h13v2"/></svg>',
};

class ApiError extends Error {
  constructor(message, status = 0, uncertain = false) {
    super(message); this.status = status; this.uncertain = uncertain;
  }
}

async function api(path, options = {}) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 15000);
  let response;
  try {
    response = await fetch(path, {
      ...options, signal: controller.signal,
      headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
      cache: 'no-store',
    });
  } catch (error) {
    throw new ApiError(error.name === 'AbortError'
      ? 'The server took too long to respond. Check that the inventory application is running.'
      : 'Cannot reach the inventory server. Check that the inventory application is running.', 0, true);
  } finally {
    clearTimeout(timeout);
  }
  let result;
  try { result = await response.json(); }
  catch { throw new ApiError('The server returned an unreadable response. Refresh to check the current inventory.', response.status, response.ok || response.status >= 500); }
  if (!response.ok) {
    const detail = result.detail;
    let message = typeof detail === 'string' ? detail : (detail?.message || result.message || 'The change could not be saved.');
    if (Array.isArray(detail)) message = detail.map((item) => {
      const field = (item.loc || []).filter((part) => part !== 'body').join(' ');
      return `${field ? `${field}: ` : ''}${item.msg || 'Invalid value'}`;
    }).join('. ');
    if (response.status === 409 && detail?.current_product) message += ' Refresh the inventory and reopen the form before trying again.';
    throw new ApiError(message, response.status, response.status >= 500);
  }
  return result;
}

function notice(id, message = '') {
  $(id).textContent = message; $(id).hidden = !message;
}

function toast(message) {
  clearTimeout(state.toastTimer); $('toast').textContent = message; $('toast').hidden = false;
  state.toastTimer = setTimeout(() => { $('toast').hidden = true; }, 3500);
}

function setStatus(online) {
  $('server-status').classList.toggle('offline', !online);
  $('status-text').textContent = online ? 'Local server connected' : 'Server unavailable';
}

function element(tag, className = '', text = '') {
  const node = document.createElement(tag); if (className) node.className = className;
  if (text !== '') node.textContent = text; return node;
}

function cell(text = '', className = '') { return element('td', className, text); }
function findProduct(id) { return state.products.find((product) => product.id === id); }
function updateProduct(product) {
  const index = state.products.findIndex((item) => item.id === product.id);
  if (index < 0) state.products.push(product); else state.products[index] = product;
}

function productDetails(product) {
  const parts = [product.brand, product.model, product.color, product.material].filter(Boolean);
  if (product.width != null || product.height != null) {
    parts.push(`${product.width == null ? '—' : product.width} × ${product.height == null ? '—' : product.height} ${product.dimension_unit}`);
  }
  return parts.join(' · ');
}

function actionButton(label, icon, action) {
  const button = element('button', 'row-action'); button.type = 'button'; button.title = label;
  button.setAttribute('aria-label', label); button.innerHTML = icons[icon];
  button.append(document.createTextNode(label)); button.addEventListener('click', action); return button;
}

function renderInventory() {
  const active = state.products.filter((product) => !product.archived);
  $('metric-products').textContent = active.length.toLocaleString('en-CA');
  $('metric-units').textContent = active.reduce((total, product) => total + product.quantity, 0).toLocaleString('en-CA');
  $('metric-empty').textContent = active.filter((product) => product.quantity === 0).length.toLocaleString('en-CA');
  const shown = state.products.filter((product) => !product.archived || $('show-archived').checked);
  $('inventory-count').textContent = shown.length;
  $('inventory-body').replaceChildren();
  $('inventory-empty').hidden = shown.length > 0 || !state.loaded;
  $('inventory-table-wrap').hidden = shown.length === 0 && state.loaded;
  const emptyTitle = $('inventory-empty').querySelector('h3');
  const emptyText = $('inventory-empty').querySelector('p');
  if (state.products.length > 0) {
    emptyTitle.textContent = 'No active products';
    emptyText.textContent = 'Add a product, or show archived products to restore one.';
  } else {
    emptyTitle.textContent = 'A place for every product';
    emptyText.replaceChildren(document.createTextNode('Add your first blind, curtain, or accessory.'), document.createElement('br'), document.createTextNode('Then receive units using its barcode.'));
  }
  const fragment = document.createDocumentFragment();
  for (const product of shown) {
    const row = element('tr');
    const productCell = cell('', 'product-cell');
    productCell.append(element('span', 'product-name', product.name));
    const details = productDetails(product);
    if (details) productCell.append(element('span', 'product-details', details));
    if (product.category) productCell.append(element('span', 'product-category', product.category));
    row.append(productCell);
    const barcodeCell = cell('', 'barcode-cell'); barcodeCell.append(element('span', 'mono', product.barcode));
    const copy = element('button', 'copy-button'); copy.type = 'button'; copy.innerHTML = icons.copy;
    copy.title = `Copy barcode ${product.barcode}`; copy.setAttribute('aria-label', copy.title);
    copy.addEventListener('click', () => copyBarcode(product.barcode)); barcodeCell.append(copy); row.append(barcodeCell);
    const stockCell = cell();
    const badge = element('span', `stock-badge${product.archived ? ' archived' : product.quantity === 0 ? ' zero' : ''}`);
    badge.append(element('span', 'tiny-dot'), document.createTextNode(product.archived ? 'Archived' : `${product.quantity.toLocaleString('en-CA')} ${product.quantity === 1 ? 'item' : 'items'}`));
    stockCell.append(badge); row.append(stockCell);
    row.append(cell(product.location || '—'));
    row.append(cell(product.price == null ? '—' : new Intl.NumberFormat('en-CA', { style: 'currency', currency: 'CAD' }).format(Number(product.price))));
    const actionsCell = cell(); const actions = element('div', 'table-actions');
    actions.append(actionButton(`Edit ${product.name}`, 'edit', () => openProductDialog(product.id)), actionButton(`Labels for ${product.name}`, 'labels', () => openLabelsDialog(product.id)));
    // The visible button labels stay compact; accessible names include the product.
    actions.children[0].lastChild.textContent = 'Edit'; actions.children[1].lastChild.textContent = 'Labels';
    const menu = element('details', 'action-menu'); const summary = element('summary', '', '⋯');
    summary.setAttribute('aria-label', `More actions for ${product.name}`); menu.append(summary);
    const content = element('div', 'menu-content');
    const adjust = element('button', '', 'Adjust stock'); adjust.type = 'button'; adjust.disabled = product.archived || Boolean(state.pendingStock) || state.stockBusy;
    adjust.addEventListener('click', () => { menu.open = false; openAdjustDialog(product.id); }); content.append(adjust);
    const archive = element('button', '', product.archived ? 'Restore product' : 'Archive product'); archive.type = 'button';
    archive.disabled = !product.archived && product.quantity !== 0;
    if (archive.disabled) archive.title = 'Only products with zero stock can be archived.';
    archive.addEventListener('click', () => { menu.open = false; archiveProduct(product.id, archive); }); content.append(archive);
    menu.addEventListener('toggle', () => {
      if (!menu.open) return;
      const anchor = summary.getBoundingClientRect();
      content.style.position = 'fixed'; content.style.right = 'auto';
      content.style.left = `${Math.max(12, anchor.right - 147)}px`;
      content.style.top = `${Math.min(anchor.bottom + 4, window.innerHeight - content.offsetHeight - 12)}px`;
    });
    menu.append(content); actions.append(menu); actionsCell.append(actions); row.append(actionsCell); fragment.append(row);
  }
  $('inventory-body').append(fragment);
  updateEditStockControls();
}

function renderHistory() {
  $('history-count').textContent = state.movements.length;
  $('history-body').replaceChildren();
  $('history-empty').hidden = state.movements.length > 0 || !state.loaded;
  $('history-table-wrap').hidden = state.movements.length === 0 && state.loaded;
  const fragment = document.createDocumentFragment();
  const names = { receipt: 'Received', sale: 'Sale', return: 'Return', correction: 'Correction' };
  for (const movement of state.movements) {
    const row = element('tr'); const date = new Date(movement.created_at);
    const dateCell = cell(date.toLocaleDateString('en-CA', { month: 'short', day: 'numeric', year: 'numeric' }));
    dateCell.append(element('span', 'history-time', date.toLocaleTimeString('en-CA', { hour: 'numeric', minute: '2-digit', second: '2-digit' }))); row.append(dateCell);
    const productCell = cell(); productCell.append(element('span', 'history-product', movement.product_name), element('span', 'mono history-barcode', movement.barcode)); row.append(productCell);
    const typeCell = cell(); typeCell.append(element('span', `movement-badge ${movement.kind}`, names[movement.kind] || movement.kind)); row.append(typeCell);
    row.append(cell(`${movement.delta > 0 ? '+' : ''}${movement.delta}`, movement.delta >= 0 ? 'delta-positive' : 'delta-negative'));
    row.append(cell(String(movement.quantity_after)), cell(movement.reason || '—', 'history-reason')); fragment.append(row);
  }
  $('history-body').append(fragment);
}

async function refresh() {
  if (state.refreshing) return false;
  state.refreshing = true;
  let productsLoaded = false;
  try {
    const results = await Promise.allSettled([api('/api/products?include_archived=true'), api('/api/movements'), api('/api/health')]);
    if (results[0].status === 'fulfilled') {
      if (!Array.isArray(results[0].value)) throw new Error('The inventory server returned an unexpected product list.');
      const changed = !state.loaded || JSON.stringify(state.products) !== JSON.stringify(results[0].value);
      state.products = results[0].value; state.loaded = true; productsLoaded = true;
      if (changed) renderInventory(); notice('global-error');
    } else { notice('global-error', results[0].reason.message); }
    if (results[1].status === 'fulfilled' && Array.isArray(results[1].value)) { state.movements = results[1].value; renderHistory(); }
    else if (state.view === 'history') notice('global-error', results[1].reason?.message || 'Stock history could not be loaded.');
    setStatus(results[2].status === 'fulfilled');
  } catch (error) { notice('global-error', error.message); }
  finally { state.refreshing = false; }
  return productsLoaded;
}

function showView(view) {
  state.view = view;
  const [eyebrow, title, description] = viewDetails[view];
  $('page-eyebrow').textContent = eyebrow; $('page-title').textContent = title; $('page-description').textContent = description;
  $('breadcrumb-view').textContent = title; document.title = `Windowstock · ${title}`;
  for (const name of Object.keys(viewDetails)) $(`${name}-view`).hidden = name !== view;
  for (const button of document.querySelectorAll('.nav-item')) {
    const selected = button.dataset.view === view; button.classList.toggle('active', selected);
    if (selected) button.setAttribute('aria-current', 'page'); else button.removeAttribute('aria-current');
  }
  if (view === 'receive' || view === 'sale') setTimeout(() => $(`${view}-barcode`).focus(), 0);
  refresh();
}

async function copyBarcode(barcode) {
  try {
    await navigator.clipboard.writeText(barcode); toast(`Copied ${barcode}`);
  } catch {
    const textarea = element('textarea'); textarea.value = barcode;
    textarea.style.position = 'fixed'; textarea.style.opacity = '0'; document.body.append(textarea); textarea.select();
    const copied = document.execCommand('copy'); textarea.remove();
    toast(copied ? `Copied ${barcode}` : `Barcode: ${barcode}`);
  }
}

function openProductDialog(id = null) {
  const product = id == null ? null : findProduct(id);
  state.editing = product ? { ...product } : null;
  const form = $('product-form'); form.reset(); notice('product-error');
  $('product-dialog-title').textContent = product ? 'Edit product' : 'Add a product';
  $('product-save').textContent = product ? 'Save changes' : 'Create product';
  $('product-form-intro').textContent = product ? `Barcode ${product.barcode} stays with this product. Adjust stock below to correct its quantity.` : 'A barcode will be generated when you save. Receive stock separately.';
  if (product) {
    for (const field of form.elements) {
      if (field.name && product[field.name] != null) field.value = product[field.name];
    }
  }
  state.editingMetadata = JSON.stringify(formMetadata(form));
  updateEditStockControls();
  $('product-dialog').showModal();
}

function updateEditStockControls() {
  const existing = state.editing;
  $('product-stock-actions').hidden = !existing;
  if (!existing) return;
  const product = findProduct(existing.id) || existing;
  const dirty = JSON.stringify(formMetadata($('product-form'))) !== state.editingMetadata;
  $('product-stock-count').textContent = `${product.quantity.toLocaleString('en-CA')} ${product.quantity === 1 ? 'item' : 'items'}`;
  $('product-adjust-stock').disabled = product.archived || dirty || $('product-save').disabled || state.stockBusy || Boolean(state.pendingStock);
  $('product-stock-hint').textContent = product.archived ? 'Restore this product before changing its stock.'
    : dirty ? 'Save your product detail changes before adjusting stock.'
      : state.pendingStock || state.stockBusy ? 'Confirm the pending stock change before making another correction.'
        : 'Set the correct stock count, including zero, and record a reason for the correction.';
}

function adjustFromProductDialog() {
  updateEditStockControls();
  if ($('product-adjust-stock').disabled || !state.editing) return;
  const id = state.editing.id;
  $('product-dialog').close();
  openAdjustDialog(id);
}

function formMetadata(form) {
  const data = new FormData(form); const result = {};
  for (const name of ['name', 'category', 'brand', 'model', 'color', 'material', 'description', 'location']) result[name] = String(data.get(name) || '').trim();
  for (const name of ['width', 'height']) result[name] = data.get(name) === '' ? null : Number(data.get(name));
  result.dimension_unit = data.get('dimension_unit');
  result.price = data.get('price') === '' ? null : Number(data.get('price')).toFixed(2);
  return result;
}

async function saveProduct(event) {
  event.preventDefault(); const button = $('product-save'); if (button.disabled) return;
  notice('product-error'); const metadata = formMetadata(event.currentTarget);
  if (!metadata.name) { notice('product-error', 'Enter a product name.'); return; }
  button.disabled = true; button.textContent = 'Saving…';
  updateEditStockControls();
  const existing = state.editing;
  try {
    const product = await api(existing ? `/api/products/${existing.id}` : '/api/products', {
      method: existing ? 'PATCH' : 'POST', body: JSON.stringify(existing ? { revision: existing.revision, ...metadata } : metadata),
    });
    updateProduct(product); renderInventory(); $('product-dialog').close();
    toast(existing ? 'Product details updated.' : `Product created. Barcode: ${product.barcode}`);
    refresh();
  } catch (error) {
    notice('product-error', error.message + (error.uncertain ? ' The change may have been saved. Close this form and check the inventory before submitting again.' : ''));
    if (error.status === 409) refresh();
  } finally { button.disabled = false; button.textContent = existing ? 'Save changes' : 'Create product'; updateEditStockControls(); }
}

async function archiveProduct(id, button) {
  const product = findProduct(id); button.disabled = true;
  try {
    const updated = await api(`/api/products/${id}/archive`, { method: 'POST', body: JSON.stringify({ revision: product.revision, archived: !product.archived }) });
    updateProduct(updated); renderInventory(); toast(updated.archived ? 'Product archived.' : 'Product restored.');
  } catch (error) { notice('global-error', error.message); refresh(); }
  finally { button.disabled = false; }
}

function setStockAvailability() {
  const blocked = state.stockBusy || Boolean(state.pendingStock);
  for (const view of ['receive', 'sale']) {
    $(`${view}-submit`).disabled = blocked; $(`${view}-barcode`).disabled = blocked;
    $(`${view}-quantity`).disabled = blocked;
    updateQuantityControls(view);
  }
  $('receive-kind').disabled = blocked; $('adjust-save').disabled = blocked;
  $('retry-scan').disabled = state.stockBusy; $('dismiss-scan').disabled = state.stockBusy;
  $('pending-notice').hidden = !state.pendingStock;
  updateEditStockControls();
}

function validStockQuantity(value) {
  return /^[0-9]+$/.test(value) && Number.isSafeInteger(Number(value)) && Number(value) >= 1 && Number(value) <= maxStockQuantity;
}

function updateQuantityControls(origin) {
  const input = $(`${origin}-quantity`);
  const quantity = validStockQuantity(input.value) ? Number(input.value) : 1;
  const blocked = state.stockBusy || Boolean(state.pendingStock);
  $(`${origin}-decrease`).disabled = blocked || quantity <= 1;
  $(`${origin}-increase`).disabled = blocked || quantity >= maxStockQuantity;
  const noun = quantity === 1 ? 'item' : 'items';
  $(`${origin}-submit`).textContent = origin === 'sale' ? `Record sale of ${quantity} ${noun}` : `Receive ${quantity} ${noun}`;
}

function quantityWarning(origin) {
  notice(`${origin}-error`, 'Enter a positive whole-number quantity from 1 to 1,000,000,000.');
}

function setupQuantityControl(origin) {
  const input = $(`${origin}-quantity`);
  let accepted = input.value;
  input.addEventListener('beforeinput', (event) => {
    if (!event.inputType.startsWith('insert') || event.data == null) return;
    const candidate = input.value.slice(0, input.selectionStart) + event.data + input.value.slice(input.selectionEnd);
    if (candidate !== '' && !validStockQuantity(candidate)) { event.preventDefault(); quantityWarning(origin); }
  });
  input.addEventListener('input', () => {
    // Paste and autofill may bypass beforeinput. Never turn an invalid value into a different valid quantity.
    if (input.value !== '' && !validStockQuantity(input.value)) {
      input.value = accepted; quantityWarning(origin);
    } else { accepted = input.value; notice(`${origin}-error`); }
    updateQuantityControls(origin);
  });
  for (const [direction, amount] of [['decrease', -1], ['increase', 1]]) {
    $(`${origin}-${direction}`).addEventListener('click', () => {
      if (state.stockBusy || state.pendingStock) return;
      const current = validStockQuantity(input.value) ? Number(input.value) : 1;
      input.value = String(Math.min(maxStockQuantity, Math.max(1, current + amount)));
      accepted = input.value; notice(`${origin}-error`); updateQuantityControls(origin);
    });
  }
  input.addEventListener('change', () => { accepted = input.value; });
  updateQuantityControls(origin);
}

function showStockResult(origin, response) {
  const { product, movement, replayed } = response;
  updateProduct(product); renderInventory();
  if (origin === 'adjust') {
    $('adjust-dialog').close(); toast(`Stock corrected to ${product.quantity} ${product.quantity === 1 ? 'item' : 'items'}.`);
  } else {
    const result = $(`${origin}-success`); result.replaceChildren();
    const count = Math.abs(movement.delta); const noun = count === 1 ? 'item' : 'items';
    const text = movement.kind === 'sale' ? 'Sale recorded' : movement.kind === 'return' ? 'Return received' : count === 1 ? 'Item received' : 'Items received';
    result.append(element('strong', '', `${text} · ${product.name}`), element('p', '', `${product.barcode} · ${movement.delta > 0 ? '+' : ''}${movement.delta} ${noun} · ${movement.quantity_after} in stock`));
    result.append(element('small', '', replayed ? 'The previous scan was confirmed safely. It was only counted once.' : `Recorded at ${new Date(movement.created_at).toLocaleTimeString('en-CA', { hour: 'numeric', minute: '2-digit', second: '2-digit' })}`));
    result.hidden = false; $(`${origin}-barcode`).value = '';
    $(`${origin}-quantity`).value = '1';
    $(`${origin}-quantity`).dispatchEvent(new Event('change'));
    updateQuantityControls(origin);
  }
}

async function submitStock(payload, origin, isRetry = false) {
  if (state.stockBusy || (state.pendingStock && !isRetry)) return;
  state.stockBusy = true; setStockAvailability();
  const errorId = origin === 'adjust' ? 'adjust-error' : `${origin}-error`; notice(errorId);
  if (origin !== 'adjust') $(`${origin}-success`).hidden = true;
  rememberStockRequest({ payload, origin });
  try {
    const response = await api('/api/stock', { method: 'POST', body: JSON.stringify(payload) });
    state.pendingStock = null; rememberStockRequest(null); showStockResult(origin, response); refresh();
  } catch (error) {
    if (error.uncertain) {
      state.pendingStock = { payload, origin }; rememberStockRequest(state.pendingStock);
      $('pending-message').textContent = `${error.message} This scan may already have been recorded. Retry the same scan safely to confirm it, or check the inventory before dismissing it.`;
      if (origin === 'adjust') { $('adjust-dialog').close(); notice('global-error', 'The stock correction needs confirmation. Use the confirmation controls below.'); }
    } else {
      state.pendingStock = null; rememberStockRequest(null);
      notice(origin === 'adjust' && !$('adjust-dialog').open ? 'global-error' : errorId, error.message);
      if (error.status === 409) refresh();
    }
  } finally {
    state.stockBusy = false; setStockAvailability(); renderInventory();
    if (!state.pendingStock && state.view === origin && origin !== 'adjust') $(`${origin}-barcode`).focus();
  }
}

function scanSubmit(event, origin) {
  event.preventDefault(); if (state.stockBusy || state.pendingStock) return;
  const barcode = $(`${origin}-barcode`).value.trim();
  if (!barcode) { notice(`${origin}-error`, 'Enter a barcode first.'); return; }
  const value = $(`${origin}-quantity`).value;
  if (!validStockQuantity(value)) { quantityWarning(origin); $(`${origin}-quantity`).focus(); return; }
  submitStock({ barcode, quantity: Number(value), kind: origin === 'sale' ? 'sale' : $('receive-kind').value, request_id: crypto.randomUUID() }, origin);
}

function openAdjustDialog(id) {
  if (state.stockBusy || state.pendingStock) return;
  const product = findProduct(id); if (!product || product.archived) return;
  state.adjusting = { ...product }; $('adjust-form').reset(); notice('adjust-error');
  $('adjust-product-name').textContent = product.name; $('adjust-product-barcode').textContent = product.barcode;
  $('adjust-current').textContent = product.quantity; $('adjust-form').elements.quantity.value = product.quantity;
  $('adjust-dialog').showModal();
}

function adjustmentSubmit(event) {
  event.preventDefault(); if (state.stockBusy || state.pendingStock) return;
  const product = state.adjusting; const form = event.currentTarget;
  const quantity = Number(form.elements.quantity.value); const reason = form.elements.reason.value.trim();
  if (!Number.isSafeInteger(quantity) || quantity < 0) { notice('adjust-error', 'Enter a whole number of items, zero or more.'); return; }
  if (!reason) { notice('adjust-error', 'Enter a reason for this correction.'); return; }
  if (quantity === product.quantity) { notice('adjust-error', 'The quantity is unchanged. Enter the corrected stock count.'); return; }
  submitStock({ barcode: product.barcode, kind: 'correction', quantity, revision: product.revision, reason, request_id: crypto.randomUUID() }, 'adjust');
}

function openLabelsDialog(id) {
  const product = findProduct(id); state.labeling = { ...product }; notice('labels-error');
  $('label-product-name').textContent = product.name; $('label-barcode-text').textContent = product.barcode;
  $('label-barcode-image').src = `/api/products/${product.id}/barcode.svg`;
  $('label-barcode-image').alt = `Barcode ${product.barcode}`;
  $('labels-dialog').showModal();
}

function printLabels() {
  notice('labels-error');
  for (const id of ['label-copies', 'label-width', 'label-height']) {
    if (!$(id).reportValidity()) return;
  }
  const params = new URLSearchParams({
    product_id: String(state.labeling.id),
    copies: $('label-copies').value,
    width: $('label-width').value,
    height: $('label-height').value,
  });
  window.location.assign(`/print?${params}`);
}

for (const button of document.querySelectorAll('.nav-item')) {
  button.setAttribute('aria-label', viewDetails[button.dataset.view][1]); button.addEventListener('click', () => showView(button.dataset.view));
}
for (const button of document.querySelectorAll('.close-dialog')) button.addEventListener('click', () => button.closest('dialog').close());
$('add-product-button').addEventListener('click', () => openProductDialog());
$('empty-add-button').addEventListener('click', () => openProductDialog());
$('history-receive-button').addEventListener('click', () => showView('receive'));
$('show-archived').addEventListener('change', renderInventory);
$('product-form').addEventListener('submit', saveProduct);
$('product-form').addEventListener('input', updateEditStockControls);
$('product-form').addEventListener('change', updateEditStockControls);
$('product-adjust-stock').addEventListener('click', adjustFromProductDialog);
$('receive-form').addEventListener('submit', (event) => scanSubmit(event, 'receive'));
$('sale-form').addEventListener('submit', (event) => scanSubmit(event, 'sale'));
$('adjust-form').addEventListener('submit', adjustmentSubmit);
$('print-labels').addEventListener('click', printLabels);
$('retry-scan').addEventListener('click', () => {
  if (state.pendingStock) submitStock(state.pendingStock.payload, state.pendingStock.origin, true);
});
$('dismiss-scan').addEventListener('click', async () => {
  if (state.stockBusy) return;
  state.stockBusy = true; setStockAvailability();
  try {
    const refreshed = await refresh();
    if (!refreshed) { toast('Unable to check current inventory. Keep this scan pending until the server reconnects.'); return; }
    state.pendingStock = null; rememberStockRequest(null);
    toast('Check current quantities and history before submitting that item again.'); showView('inventory');
  } finally {
    state.stockBusy = false; setStockAvailability(); renderInventory();
  }
});
async function downloadBackup() {
  const button = $('backup-button'); if (button.disabled) return;
  button.disabled = true; $('compact-backup-button').disabled = true;
  try {
    const response = await fetch('/api/backup', { cache: 'no-store' });
    if (!response.ok) throw new Error('The database backup could not be downloaded. Try again when the server is connected.');
    const blob = await response.blob(); const url = URL.createObjectURL(blob);
    const link = element('a'); link.href = url;
    const date = new Date().toLocaleDateString('en-CA'); link.download = `windowstock-backup-${date}.sqlite3`;
    document.body.append(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url), 10000);
    toast('Database backup downloaded. Keep a copy somewhere safe.');
  } catch (error) { notice('global-error', error.message); }
  finally { button.disabled = false; $('compact-backup-button').disabled = false; }
}
$('backup-button').addEventListener('click', downloadBackup);
$('compact-backup-button').addEventListener('click', downloadBackup);
document.addEventListener('click', (event) => {
  for (const menu of document.querySelectorAll('.action-menu[open]')) if (!menu.contains(event.target)) menu.open = false;
});
document.addEventListener('scroll', () => {
  for (const menu of document.querySelectorAll('.action-menu[open]')) menu.open = false;
}, true);
$('label-barcode-image').addEventListener('error', () => notice('labels-error', 'The barcode preview could not be loaded. Check the local server connection.'));
for (const origin of ['receive', 'sale']) setupQuantityControl(origin);
if (state.pendingStock && ['receive', 'sale'].includes(state.pendingStock.origin)) {
  const quantity = state.pendingStock.payload.quantity ?? 1;
  if (validStockQuantity(String(quantity))) {
    $(`${state.pendingStock.origin}-quantity`).value = String(quantity);
    $(`${state.pendingStock.origin}-quantity`).dispatchEvent(new Event('change'));
  }
}
setStockAvailability();
refresh();
setInterval(() => { if (!document.hidden) refresh(); }, 3000);
document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh(); });

