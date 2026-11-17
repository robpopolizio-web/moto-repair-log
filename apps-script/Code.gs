/** @OnlyCurrentDoc */
/**
 * Moto Repair Log: backend (Google Apps Script + Google Sheet)
 * (@OnlyCurrentDoc limits the script's access to this one spreadsheet.)
 *
 * Lives in the "Moto Repair Log data" sheet: Extensions > Apps Script.
 * After editing: Deploy > Manage deployments > edit (pencil) >
 * Version: New version > Deploy. The web app URL stays the same.
 *
 * Every entry lands as one row in the "entries" tab. Emails stay in the sheet
 * and are never returned by the API. Riders only ever get back their own
 * entries (by garage code) and per-model totals.
 */

const SHEET_NAME = 'entries';
const HEADERS = [
  'entry_id', 'created_at', 'garage_id', 'source', 'brand', 'model', 'model_key',
  'year', 'country', 'email', 'type', 'date', 'odometer', 'unit', 'category',
  'part_failed', 'notes'
];
const TEXT_COLS = ['entry_id', 'created_at', 'garage_id', 'model', 'model_key', 'date', 'year'];
const PUBLIC_FIELDS = [
  'entry_id', 'created_at', 'brand', 'model', 'year', 'country', 'type', 'date',
  'odometer', 'unit', 'category', 'part_failed', 'notes'
];
const TYPES = ['repair', 'checkin'];
const CATEGORIES = [
  'Engine', 'Electrical & lights', 'Battery & charging', 'Fuel system', 'Cooling',
  'Clutch & gearbox', 'Final drive', 'Brakes & ABS', 'Suspension & steering',
  'Wheels & bearings', 'Frame & bodywork', 'Electronics & dash', 'Other'
];
const UNITS = ['km', 'mi'];
const KM_PER_MI = 1.609344;
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
  const last = sh.getLastRow();
  if (last === 0) {
    writeHeaders_(sh);
  } else if (last === 1) {
    // No data yet: refresh the header row if the columns changed.
    const cur = sh.getRange(1, 1, 1, sh.getLastColumn()).getDisplayValues()[0];
    if (cur.join('|') !== HEADERS.join('|')) {
      sh.getRange(1, 1, 1, sh.getMaxColumns()).clearContent();
      writeHeaders_(sh);
    }
  }
  return sh;
}

function writeHeaders_(sh) {
  sh.getRange(1, 1, 1, HEADERS.length).setValues([HEADERS]).setFontWeight('bold');
  sh.setFrozenRows(1);
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

  const cats = {};
  repairs.forEach(function (r) { cats[r.category] = (cats[r.category] || 0) + 1; });
  const top = Object.keys(cats)
    .map(function (k) { return [k, cats[k]]; })
    .sort(function (a, b) { return b[1] - a[1]; })
    .slice(0, 3);

  // Median mileage at repair, in km.
  const kms = repairs
    .map(function (r) { const o = Number(r.odometer) || 0; return r.unit === 'mi' ? o * KM_PER_MI : o; })
    .filter(function (x) { return x > 0; })
    .sort(function (a, b) { return a - b; });
  let medianKm = null;
  if (kms.length) {
    const mid = Math.floor(kms.length / 2);
    medianKm = Math.round(kms.length % 2 ? kms[mid] : (kms[mid - 1] + kms[mid]) / 2);
  }

  return { owners: owners, repairs: repairs.length, topCategories: top, medianKm: medianKm };
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
  if (odometer === '') return { ok: false, error: 'Mileage is required' };

  const thisYear = new Date().getFullYear();
  const y = parseInt(b.year, 10);
  const year = y >= 1950 && y <= thisYear + 1 ? String(y) : '';
  const date = /^\d{4}-\d{2}$/.test(String(b.date || '')) ? String(b.date) : '';
  const email = String(b.email || '').trim().slice(0, 120);
  const isRepair = type === 'repair';

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
    category: isRepair ? oneOf_(b.category, CATEGORIES, 'Other') : 'No repairs',
    part_failed: isRepair ? clean_(b.part_failed, 300) : '',
    notes: clean_(b.notes, 500)
  };
  if (isRepair && !entry.part_failed) return { ok: false, error: 'Say which part failed' };

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
