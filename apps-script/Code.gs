/** @OnlyCurrentDoc */
/**
 * Moto Repair Log: backend (Google Apps Script + Google Sheet)
 * (@OnlyCurrentDoc limits the script's access to this one spreadsheet.)
 *
 * Setup (about 5 minutes):
 *   1. Create a blank Google Sheet (name it e.g. "Moto Repair Log data").
 *   2. In the sheet: Extensions > Apps Script.
 *   3. Delete everything in Code.gs, paste this whole file, click Save.
 *   4. Pick "setup" in the function dropdown, click Run, approve the permissions.
 *   5. Deploy > New deployment > type "Web app".
 *        Execute as: Me
 *        Who has access: Anyone
 *      Click Deploy and copy the Web app URL (ends in /exec).
 *   6. Paste that URL into API_URL at the top of the script in index.html.
 *
 * After editing this file later: Deploy > Manage deployments > edit (pencil) >
 * Version: New version > Deploy. The URL stays the same.
 *
 * Every entry lands as one row in the "entries" tab. Emails stay in the sheet
 * and are never returned by the API. Riders only ever get back their own
 * entries (by garage code) and per-model totals.
 */

const SHEET_NAME = 'entries';
const HEADERS = [
  'entry_id', 'created_at', 'garage_id', 'source', 'brand', 'model', 'model_key',
  'year', 'country', 'email', 'type', 'date', 'odometer', 'unit', 'category',
  'what_failed', 'parts', 'cost_parts', 'cost_labor', 'currency', 'paid_by',
  'who_fixed', 'notes'
];
const TEXT_COLS = ['entry_id', 'created_at', 'garage_id', 'model', 'model_key', 'date', 'year'];
const PUBLIC_FIELDS = [
  'entry_id', 'created_at', 'brand', 'model', 'year', 'country', 'type', 'date',
  'odometer', 'unit', 'category', 'what_failed', 'parts', 'cost_parts',
  'cost_labor', 'currency', 'paid_by', 'who_fixed', 'notes'
];
const TYPES = ['repair', 'service', 'checkin'];
const CATEGORIES = [
  'Engine', 'Electrical & lights', 'Battery & charging', 'Fuel system', 'Cooling',
  'Clutch & gearbox', 'Final drive', 'Brakes & ABS', 'Suspension & steering',
  'Wheels & bearings', 'Frame & bodywork', 'Electronics & dash', 'Other'
];
const PAID_BY = ['Me', 'Warranty', 'Recall', 'Insurance'];
const WHO_FIXED = ['Myself', 'Dealer', 'Independent shop'];
const UNITS = ['km', 'mi'];
const MAX_PER_HOUR = 60;

/* ---------- setup ---------- */

function setup() {
  const sh = getSheet_();
  Logger.log('Ready. Data goes to the "' + sh.getName() + '" tab.');
}

function getSheet_() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  let sh = ss.getSheetByName(SHEET_NAME);
  if (!sh) sh = ss.insertSheet(SHEET_NAME);
  if (sh.getLastRow() === 0) {
    sh.getRange(1, 1, 1, HEADERS.length).setValues([HEADERS]).setFontWeight('bold');
    sh.setFrozenRows(1);
  }
  return sh;
}

/* ---------- HTTP ---------- */

function doGet(e) {
  const p = (e && e.parameter) || {};
  try {
    if (p.action === 'log') return json_({ ok: true, entries: logFor_(p.garage) });
    if (p.action === 'stats') return json_({ ok: true, stats: statsFor_(p.brand, p.model) });
    if (p.action === 'models') return json_({ ok: true, models: modelsFor_(p.brand) });
    return json_({ ok: true, service: 'moto-repair-log' });
  } catch (err) {
    return json_({ ok: false, error: String(err && err.message || err) });
  }
}

function doPost(e) {
  let body;
  try {
    body = JSON.parse(e.postData.contents);
  } catch (_) {
    return json_({ ok: false, error: 'Bad request' });
  }
  // Honeypot: real people never fill the hidden "website" field.
  if (body.website) return json_({ ok: true });

  const lock = LockService.getScriptLock();
  lock.waitLock(10000);
  try {
    if (body.action === 'add') return json_(add_(body));
    if (body.action === 'delete') return json_(delete_(body));
    return json_({ ok: false, error: 'Unknown action' });
  } catch (err) {
    return json_({ ok: false, error: String(err && err.message || err) });
  } finally {
    lock.releaseLock();
  }
}

function json_(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}

/* ---------- reads ---------- */

function readRows_() {
  const sh = getSheet_();
  const n = sh.getLastRow();
  if (n < 2) return [];
  const vals = sh.getRange(2, 1, n - 1, HEADERS.length).getDisplayValues();
  return vals.map(function (r) {
    const o = {};
    HEADERS.forEach(function (h, i) { o[h] = r[i]; });
    return o;
  });
}

function public_(row) {
  const o = {};
  PUBLIC_FIELDS.forEach(function (f) { o[f] = row[f]; });
  return o;
}

function logFor_(garage) {
  if (!validGarage_(garage)) throw new Error('Bad garage code');
  return readRows_().filter(function (r) { return r.garage_id === garage; }).map(public_);
}

function statsFor_(brand, model) {
  const bk = key_(brand), mk = key_(model);
  if (!bk || !mk) throw new Error('Brand and model required');
  const rows = readRows_().filter(function (r) { return key_(r.brand) === bk && r.model_key === mk; });
  return computeStats_(rows);
}

function computeStats_(rows) {
  const owners = new Set(rows.map(function (r) { return r.garage_id; })).size;
  const repairs = rows.filter(function (r) { return r.type === 'repair'; });
  const services = rows.filter(function (r) { return r.type === 'service'; }).length;

  const cats = {};
  repairs.forEach(function (r) { cats[r.category] = (cats[r.category] || 0) + 1; });
  const top = Object.keys(cats)
    .map(function (k) { return [k, cats[k]]; })
    .sort(function (a, b) { return b[1] - a[1]; })
    .slice(0, 3);

  // Typical owner-paid repair cost, in whichever currency has the most entries.
  const byCur = {};
  repairs.forEach(function (r) {
    if (r.paid_by !== 'Me' || !r.currency) return;
    const t = (Number(r.cost_parts) || 0) + (Number(r.cost_labor) || 0);
    if (t <= 0) return;
    (byCur[r.currency] = byCur[r.currency] || []).push(t);
  });
  let typical = null;
  Object.keys(byCur).forEach(function (c) {
    const a = byCur[c];
    if (typical && a.length <= typical.n) return;
    a.sort(function (x, y) { return x - y; });
    const mid = Math.floor(a.length / 2);
    const median = a.length % 2 ? a[mid] : (a[mid - 1] + a[mid]) / 2;
    typical = { currency: c, median: Math.round(median), n: a.length };
  });

  return { owners: owners, repairs: repairs.length, services: services, topCategories: top, typicalCost: typical };
}

function modelsFor_(brand) {
  const bk = key_(brand);
  if (!bk) return [];
  const counts = {}, spellings = {};
  readRows_().forEach(function (r) {
    if (key_(r.brand) !== bk) return;
    const mk = r.model_key;
    counts[mk] = (counts[mk] || 0) + 1;
    spellings[mk] = spellings[mk] || {};
    spellings[mk][r.model] = (spellings[mk][r.model] || 0) + 1;
  });
  return Object.keys(counts)
    .sort(function (a, b) { return counts[b] - counts[a]; })
    .slice(0, 50)
    .map(function (mk) {
      const s = spellings[mk];
      return Object.keys(s).sort(function (a, b) { return s[b] - s[a]; })[0];
    });
}

/* ---------- writes ---------- */

function add_(b) {
  const garage = String(b.garage || '');
  if (!validGarage_(garage)) return { ok: false, error: 'Bad garage code' };

  const cache = CacheService.getScriptCache();
  const ck = 'rl_' + garage;
  const count = Number(cache.get(ck) || 0);
  if (count >= MAX_PER_HOUR) return { ok: false, error: 'Too many entries this hour. Try again later.' };

  const type = TYPES.indexOf(b.type) >= 0 ? b.type : '';
  if (!type) return { ok: false, error: 'Unknown entry type' };

  const brand = clean_(b.brand, 40);
  const model = clean_(b.model, 60);
  if (!brand || !model) return { ok: false, error: 'Brand and model are required' };

  const odometer = num_(b.odometer);
  if (odometer === '') return { ok: false, error: 'Odometer reading is required' };

  const thisYear = new Date().getFullYear();
  const y = parseInt(b.year, 10);
  const year = y >= 1950 && y <= thisYear + 1 ? String(y) : '';
  const date = /^\d{4}-\d{2}$/.test(String(b.date || '')) ? String(b.date) : '';
  const email = String(b.email || '').trim().slice(0, 120);
  const isCheckin = type === 'checkin';

  const entry = {
    entry_id: Utilities.getUuid().replace(/-/g, '').slice(0, 12),
    created_at: new Date().toISOString(),
    garage_id: garage,
    source: clean_(b.source, 60),
    brand: brand,
    model: model,
    model_key: key_(model),
    year: year,
    country: clean_(b.country, 40),
    email: /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email) ? email : '',
    type: type,
    date: date,
    odometer: odometer,
    unit: UNITS.indexOf(b.unit) >= 0 ? b.unit : 'km',
    category: type === 'repair' ? oneOf_(b.category, CATEGORIES, 'Other') : (type === 'service' ? 'Service' : 'No repairs'),
    what_failed: isCheckin ? '' : clean_(b.what_failed, 300),
    parts: isCheckin ? '' : clean_(b.parts, 300),
    cost_parts: isCheckin ? '' : num_(b.cost_parts),
    cost_labor: isCheckin ? '' : num_(b.cost_labor),
    currency: isCheckin ? '' : clean_(b.currency, 8).toUpperCase(),
    paid_by: type === 'repair' ? oneOf_(b.paid_by, PAID_BY, 'Me') : (type === 'service' ? 'Me' : ''),
    who_fixed: isCheckin ? '' : oneOf_(b.who_fixed, WHO_FIXED, ''),
    notes: clean_(b.notes, 500)
  };
  if (!isCheckin && !entry.what_failed) return { ok: false, error: 'Describe what failed or what was done' };

  const sh = getSheet_();
  const r = sh.getLastRow() + 1;
  if (r > sh.getMaxRows()) sh.insertRowsAfter(sh.getMaxRows(), 200);
  const range = sh.getRange(r, 1, 1, HEADERS.length);
  range.setNumberFormats([HEADERS.map(function (h) { return TEXT_COLS.indexOf(h) >= 0 ? '@' : 'General'; })]);
  range.setValues([HEADERS.map(function (h) { return safe_(entry[h]); })]);

  cache.put(ck, String(count + 1), 3600);
  return { ok: true, entry: public_(entry) };
}

function delete_(b) {
  const garage = String(b.garage || '');
  const id = String(b.entry_id || '');
  if (!validGarage_(garage) || !/^[a-f0-9]{12}$/.test(id)) return { ok: false, error: 'Bad request' };
  const sh = getSheet_();
  const n = sh.getLastRow();
  if (n < 2) return { ok: false, error: 'Entry not found' };
  const idCol = HEADERS.indexOf('entry_id') + 1;
  const gCol = HEADERS.indexOf('garage_id') + 1;
  const ids = sh.getRange(2, idCol, n - 1, 1).getDisplayValues();
  const gs = sh.getRange(2, gCol, n - 1, 1).getDisplayValues();
  for (let i = 0; i < ids.length; i++) {
    if (ids[i][0] === id && gs[i][0] === garage) {
      sh.deleteRow(i + 2);
      return { ok: true };
    }
  }
  return { ok: false, error: 'Entry not found' };
}

/* ---------- helpers ---------- */

function validGarage_(g) { return /^[a-z0-9]{12,32}$/.test(String(g || '')); }
function key_(s) { return String(s || '').toLowerCase().replace(/[^a-z0-9]/g, ''); }
function clean_(v, max) {
  return String(v == null ? '' : v).replace(/[\u0000-\u001f\u007f]/g, ' ').trim().slice(0, max || 200);
}
function num_(v) {
  if (v === '' || v == null) return '';
  const n = Number(String(v).replace(/\s/g, '').replace(',', '.'));
  return isFinite(n) && n >= 0 && n < 10000000 ? Math.round(n * 100) / 100 : '';
}
function oneOf_(v, list, fallback) { return list.indexOf(v) >= 0 ? v : fallback; }
// Stop text from being read as a spreadsheet formula.
function safe_(v) {
  if (typeof v !== 'string') return v;
  return /^[=+\-@]/.test(v) ? "'" + v : v;
}
