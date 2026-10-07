'use strict';

const printButton = document.getElementById('print-button');
const sheet = document.getElementById('label-sheet');
const statusText = document.getElementById('print-status');
const errorBox = document.getElementById('print-error');

function printError(message) {
  errorBox.textContent = message; errorBox.hidden = false;
  statusText.hidden = true; printButton.disabled = true;
}

function integerParam(params, name, min, max) {
  const raw = params.get(name);
  if (!raw || !/^\d+$/.test(raw)) throw new Error(`The ${name.replace('_', ' ')} value must be a whole number.`);
  const value = Number(raw);
  if (!Number.isSafeInteger(value) || value < min || value > max) throw new Error(`The ${name.replace('_', ' ')} value must be between ${min} and ${max}.`);
  return value;
}

async function prepareLabels() {
  errorBox.hidden = true; errorBox.textContent = ''; statusText.hidden = false;
  try {
    const params = new URLSearchParams(window.location.search);
    const productId = integerParam(params, 'product_id', 1, Number.MAX_SAFE_INTEGER);
    const copies = integerParam(params, 'copies', 1, 100);
    const width = integerParam(params, 'width', 40, 200);
    const height = integerParam(params, 'height', 25, 150);
    const controller = new AbortController(); const timeout = setTimeout(() => controller.abort(), 15000);
    let response;
    try { response = await fetch(`/api/products/${productId}`, { cache: 'no-store', signal: controller.signal }); }
    catch { throw new Error('Cannot reach the inventory server. Check that the application is running, then reload this sheet.'); }
    finally { clearTimeout(timeout); }
    if (!response.ok) {
      let detail;
      try { detail = (await response.json()).detail; } catch { /* Use a helpful fallback. */ }
      throw new Error(typeof detail === 'string' ? detail : (detail?.message || 'This product could not be loaded. Return to inventory and open its labels again.'));
    }
    const product = await response.json();
    if (!product.name || !product.barcode || product.id !== productId) throw new Error('The server returned unexpected product details. Return to inventory and try again.');
    document.title = `Barcode labels · ${product.name}`;
    document.getElementById('print-title').textContent = product.name;
    document.getElementById('print-summary').textContent = `${copies} ${copies === 1 ? 'label' : 'labels'} · ${width} × ${height} mm · ${product.barcode}`;
    document.documentElement.style.setProperty('--label-width', `${width}mm`);
    document.documentElement.style.setProperty('--label-height', `${height}mm`);
    document.documentElement.style.setProperty('--barcode-height', `${Math.max(9, height - 20)}mm`);
    statusText.textContent = 'Loading barcode images…';
    let remaining = copies, failed = false;
    const imageReady = (success) => {
      if (!success) failed = true;
      remaining -= 1;
      if (remaining === 0) {
        if (failed) printError('A barcode image could not be loaded. Check the local server connection and reload this sheet before printing.');
        else { printButton.disabled = false; statusText.textContent = 'Ready to print. Use the button above to print or save this sheet as PDF.'; }
      }
    };
    for (let index = 0; index < copies; index += 1) {
      const label = document.createElement('div'); label.className = 'barcode-label';
      const name = document.createElement('strong'); name.textContent = product.name;
      const image = document.createElement('img'); image.alt = `Barcode ${product.barcode}`;
      image.addEventListener('load', () => imageReady(true), { once: true });
      image.addEventListener('error', () => imageReady(false), { once: true });
      image.src = `/api/products/${product.id}/barcode.svg`;
      const barcode = document.createElement('span'); barcode.textContent = product.barcode;
      label.append(name, image, barcode); sheet.append(label);
    }
    sheet.hidden = false;
  } catch (error) { printError(error.message || 'The printable sheet could not be prepared. Return to inventory and try again.'); }
}

printButton.addEventListener('click', () => { if (!printButton.disabled) window.print(); });
prepareLabels();
