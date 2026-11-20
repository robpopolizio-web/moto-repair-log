/**
 * Moto Repair Log: backend (Google Apps Script + Google Sheet)
 *
 * Lives in the "Moto Repair Log data" sheet: Extensions > Apps Script.
 * Permissions are set in appsscript.json: this spreadsheet only, plus Drive
 * files this script creates itself (the photos folder). Nothing else in Drive.
 * After editing: Deploy > Manage deployments > edit (pencil) >
 * Version: New version > Deploy. The web app URL stays the same.
 *
 * Every entry lands as one row in the "entries" tab. Photos go to the
 * "Moto Repair Log photos" folder in Drive, private to the owner, with links
 * in the "photos" column. Emails and photo links are never returned by the
 * API. Riders only ever get back their own entries (by garage code) and
 * per-model totals.
 */

const SHEET_NAME = 'entries';
const HEADERS = [
  'entry_id', 'created_at', 'garage_id', 'source', 'brand', 'model', 'model_key',
  'year', 'country', 'email', 'type', 'date', 'odometer', 'unit', 'category',
  'part_failed', 'notes', 'photos'
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
const MAX_PHOTOS = 3;
const MAX_PHOTO_BYTES = 3 * 1024 * 1024;
const PHOTO_FOLDER_NAME = 'Moto Repair Log photos';

/* ---------- setup ---------- */

function setup() {
  const sh = getSheet_();
  const folderId = photoFolderId_();
  Logger.log('Ready. Data goes to the "' + sh.getName() + '" tab. Photos folder id: ' + folderId);
}

function getSheet_() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  let sh = ss.getSheetByName(SHEET_NAME);
  if (!sh) sh = ss.insertSheet(SHEET_NAME);
  if (sh.getLastRow() === 0) {
    writeHeaders_(sh);
  } else {
    // Refresh the header row when columns were added at the end or (with no data yet) changed.
    const cur = sh.getRange(1, 1, 1, Math.max(sh.getLastColumn(), 1)).getDisplayValues()[0]
      .filter(function (h) { return h !== ''; });
    const isPrefix = cur.every(function (h, i) { return HEADERS[i] === h; });
    if (cur.join('|') !== HEADERS.join('|') && (isPrefix || sh.getLastRow() === 1)) {
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

function photoFolderId_() {
  const props = PropertiesService.getScriptProperties();
  const id = props.getProperty('PHOTO_FOLDER_ID');
  if (id) return id;
  const folder = Drive.Files.create({ name: PHOTO_FOLDER_NAME, mimeType: 'application/vnd.google-apps.folder' });
  props.setProperty('PHOTO_FOLDER_ID', folder.id);
  return folder.id;
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

  try {
    if (body.action === 'add') return json_(add_(body));
    if (body.action === 'delete') return json_(delete_(body));
    return json_({ ok: false, error: 'Unknown action' });
  } catch (err) {
    return json_({ ok: false, error: String(err && err.message || err) });
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
  o.photo_count = row.photos ? String(row.photos).split(/\s+/).filter(String).length : 0;
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

  // Most common failed parts, grouped loosely by their text.
  const counts = {}, names = {};
  repairs.forEach(function (r) {
    const k = key_(r.part_failed);
    if (!k) return;
    counts[k] = (counts[k] || 0) + 1;
    names[k] = names[k] || r.part_failed;
  });
  const top = Object.keys(counts)
    .map(function (k) { return [names[k], counts[k]]; })
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
    category: isRepair ? oneOf_(b.category, CATEGORIES, '') : 'No repairs',
    part_failed: isRepair ? clean_(b.part_failed, 300) : '',
    notes: clean_(b.notes, 500),
    photos: ''
  };
  if (isRepair && !entry.part_failed) return { ok: false, error: 'Say which part failed' };

  // Photos first (the slow part), outside the sheet lock.
  if (isRepair && Array.isArray(b.photos) && b.photos.length) {
    const blobs = [];
    b.photos.slice(0, MAX_PHOTOS).forEach(function (data, i) {
      let bytes;
      try { bytes = Utilities.base64Decode(String(data || '')); } catch (_) { return; }
      if (!bytes.length || bytes.length > MAX_PHOTO_BYTES) return;
      if ((bytes[0] & 0xff) !== 0xff || (bytes[1] & 0xff) !== 0xd8) return; // JPEG only
      blobs.push(Utilities.newBlob(bytes, 'image/jpeg', entry.entry_id + '-' + (i + 1) + '.jpg'));
    });
    if (blobs.length) {
      const folderId = photoFolderId_();
      entry.photos = blobs.map(function (blob) {
        const f = Drive.Files.create({ name: blob.getName(), parents: [folderId] }, blob);
        return 'https://drive.google.com/file/d/' + f.id + '/view';
      }).join(' ');
    }
  }

  const lock = LockService.getScriptLock();
  lock.waitLock(10000);
  try {
    const sh = getSheet_();
    const r = sh.getLastRow() + 1;
    if (r > sh.getMaxRows()) sh.insertRowsAfter(sh.getMaxRows(), 200);
    const range = sh.getRange(r, 1, 1, HEADERS.length);
    range.setNumberFormats([HEADERS.map(function (h) { return TEXT_COLS.indexOf(h) >= 0 ? '@' : 'General'; })]);
    range.setValues([HEADERS.map(function (h) { return safe_(entry[h]); })]);
  } finally {
    lock.releaseLock();
  }

  cache.put(ck, String(count + 1), 3600);
  return { ok: true, entry: public_(entry) };
}

function delete_(b) {
  const garage = String(b.garage || '');
  const id = String(b.entry_id || '');
  if (!validGarage_(garage) || !/^[a-f0-9]{12}$/.test(id)) return { ok: false, error: 'Bad request' };
  let photos = '';
  const lock = LockService.getScriptLock();
  lock.waitLock(10000);
  try {
    const sh = getSheet_();
    const n = sh.getLastRow();
    if (n < 2) return { ok: false, error: 'Entry not found' };
    const idCol = HEADERS.indexOf('entry_id') + 1;
    const gCol = HEADERS.indexOf('garage_id') + 1;
    const pCol = HEADERS.indexOf('photos') + 1;
    const ids = sh.getRange(2, idCol, n - 1, 1).getDisplayValues();
    const gs = sh.getRange(2, gCol, n - 1, 1).getDisplayValues();
    let found = -1;
    for (let i = 0; i < ids.length; i++) {
      if (ids[i][0] === id && gs[i][0] === garage) { found = i + 2; break; }
    }
    if (found < 0) return { ok: false, error: 'Entry not found' };
    photos = sh.getRange(found, pCol).getDisplayValue();
    sh.deleteRow(found);
  } finally {
    lock.releaseLock();
  }
  // Move the entry's photos to the Drive trash.
  String(photos || '').split(/\s+/).forEach(function (url) {
    const m = /\/file\/d\/([^/]+)/.exec(url);
    if (!m) return;
    try { Drive.Files.update({ trashed: true }, m[1]); } catch (_) {}
  });
  return { ok: true };
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
