// --- CONFIG ---
const TAB = 'incidents';

// GET /exec?token=YOUR_TOKEN  → returns { data: [...] } for Streamlit
function doGet(e) {
  const token = (e.parameter.token || '').trim();
  const expected = PropertiesService.getScriptProperties().getProperty('API_TOKEN');
  if (!expected || token !== expected) {
    return ContentService.createTextOutput('Forbidden').setMimeType(ContentService.MimeType.TEXT);
  }
  const sh = SpreadsheetApp.getActive().getSheetByName(TAB);
  const values = sh.getDataRange().getValues();
  const [header, ...rows] = values;
  const data = rows
    .filter(r => r[0]) // keep rows with an incident_id
    .map(r => Object.fromEntries(header.map((h, i) => [h, r[i]])));
  return ContentService
    .createTextOutput(JSON.stringify({ data }))
    .setMimeType(ContentService.MimeType.JSON);
}

// Client calls this to append a row
function addIncident(data) {
  const sh = SpreadsheetApp.getActive().getSheetByName(TAB);
  if (!sh) throw new Error('Sheet tab "incidents" not found');
  const now = new Date();
  const row = [
    Utilities.getUuid(),                               // incident_id
    now.toISOString(),                                 // timestamp_utc
    data.date || '',
    data.time || '',
    (data.student_id || '').trim(),
    data.location || '',
    data.antecedent || '',
    data.behavior || '',
    data.consequence || '',
    Number(data.duration_sec || 0),
    Number(data.intensity || 0),
    data.notes || '',
    (data.staff || '').trim()
  ];
  sh.appendRow(row);
  return { ok: true };
}

function doGetForm() {
  return HtmlService.createHtmlOutputFromFile('Index')
    .setXFrameOptionsMode(HtmlService.XFrameOptionsMode.ALLOWALL)
    .setTitle('ABC Incident Form');
}
