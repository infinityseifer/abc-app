// --- CONFIG ---
const TAB = 'incidents';
const ID_SEPARATOR = ''; // set to '-' if you prefer 'AL-0427'

// If this project is STANDALONE (not bound to the sheet), set SHEET_ID in
// Project Settings → Script properties. If bound, you can leave it empty.
function getSheet() {
  const sp = PropertiesService.getScriptProperties();
  const SHEET_ID = (sp.getProperty('SHEET_ID') || '').trim(); // optional
  const ss = SHEET_ID ? SpreadsheetApp.openById(SHEET_ID) : SpreadsheetApp.getActive();
  if (!ss) throw new Error('No active spreadsheet. Set SHEET_ID in Script properties for standalone projects.');
  const sh = ss.getSheetByName(TAB);
  if (!sh) throw new Error(`Sheet tab "${TAB}" not found`);
  return sh;
}

/** Take first two letters (A-Z) from a name/ID, uppercase, pad with X if short. */
function twoLetterPrefix(str) {
  const letters = (str || '').replace(/[^A-Za-z]/g, '').toUpperCase();
  return (letters.slice(0, 2) || 'XX').padEnd(2, 'X'); // 'A'->'AX', ''->'XX'
}

/** Existing IDs to avoid collisions. */
function getExistingIds(sh) {
  const last = sh.getLastRow();
  if (last < 2) return new Set();
  const ids = sh.getRange(2, 1, last - 1, 1).getValues().flat().filter(String);
  return new Set(ids);
}

/** Next per-prefix sequential suffix (0000–9999), stored in Script properties. */
function nextSequentialSuffix(prefix) {
  const sp = PropertiesService.getScriptProperties();
  const key = 'SEQ_' + prefix; // e.g., SEQ_AL
  let n = parseInt(sp.getProperty(key) || '0', 10);
  n = (n + 1) % 10000;                       // wrap after 9999
  sp.setProperty(key, String(n));
  return Utilities.formatString('%04d', n);
}

/** Generate unique ID using per-prefix sequence; fall back to random if needed. */
function generateIncidentId(prefix, existing) {
  for (let tries = 0; tries < 5; tries++) {
    const id = prefix + ID_SEPARATOR + nextSequentialSuffix(prefix);
    if (!existing.has(id)) return id;
  }
  // rare fallback
  return prefix + ID_SEPARATOR + Utilities.formatString('%04d', Math.floor(Math.random() * 10000));
}

// Create a row with unique incident_id
function addIncident(data) {
  // lock to prevent concurrent sequence collisions
  const lock = LockService.getScriptLock();
  lock.waitLock(5000);
  try {
    const sh = getSheet();
    const sid = (data.student_id || data.student_name || '').trim();
    const prefix = twoLetterPrefix(sid);
    const existing = getExistingIds(sh);
    const incidentId = generateIncidentId(prefix, existing);

    const now = new Date();
    sh.appendRow([
      incidentId,                        // incident_id (e.g., AL0001)
      now.toISOString(),                 // timestamp_utc
      data.date || '',
      data.time || '',
      sid,                                // stored under student_id column
      data.location || '',
      data.antecedent || '',
      data.behavior || '',
      data.consequence || '',
      Number(data.duration_sec || 0),
      Number(data.intensity || 0),
      data.notes || '',
      (data.staff || '').trim()
    ]);
    return { ok: true, incident_id: incidentId };
  } finally {
    lock.releaseLock();
  }
}

// Simple ping for debugging from the form
function ping() { return 'pong'; }

// Web App entry point
function doGet(e) {
  const p = e?.parameter || {};

  // JSON endpoint for Streamlit: /exec?mode=json&token=YOUR_TOKEN
  if (p.mode === 'json') {
    const token = (p.token || '').trim();
    const expected = (PropertiesService.getScriptProperties().getProperty('API_TOKEN') || '').trim();
    if (!expected || token !== expected) {
      return ContentService.createTextOutput(JSON.stringify({ error: 'forbidden' }))
        .setMimeType(ContentService.MimeType.JSON);
    }
    try {
      const sh = getSheet();
      const values = sh.getDataRange().getValues(); // header + rows
      if (!values || values.length < 2) {
        const header = values?.[0] || [];
        return ContentService.createTextOutput(JSON.stringify({ data: [], header }))
          .setMimeType(ContentService.MimeType.JSON);
      }
      const [header, ...rows] = values;
      const data = rows
        .filter(r => r[0]) // require incident_id
        .map(r => Object.fromEntries(header.map((h, i) => [h, r[i]])));
      return ContentService.createTextOutput(JSON.stringify({ data }))
        .setMimeType(ContentService.MimeType.JSON);
    } catch (err) {
      return ContentService.createTextOutput(JSON.stringify({ error: 'server_error', message: String(err) }))
        .setMimeType(ContentService.MimeType.JSON);
    }
  }

  // Default: serve the HTML form
  return HtmlService.createHtmlOutputFromFile('Index')
    .setXFrameOptionsMode(HtmlService.XFrameOptionsMode.ALLOWALL)
    .setTitle('ABC Incident Form');
}


function resetSeq(prefix) { // e.g., resetSeq('AL')
  PropertiesService.getScriptProperties().deleteProperty('SEQ_' + prefix.toUpperCase());
}
function getSeq(prefix) {
  return PropertiesService.getScriptProperties().getProperty('SEQ_' + prefix.toUpperCase());
}
