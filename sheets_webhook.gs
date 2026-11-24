// 실험 응답을 구글 시트에 저장하는 Apps Script
//
// 설정 방법
// 1. 새 구글 시트를 만든다 (이 시트에 응답이 쌓임)
// 2. 시트 메뉴: 확장 프로그램 → Apps Script → 이 코드 전체를 붙여넣고 저장
// 3. 아래 SECRET 값을 아무도 못 맞힐 긴 문자열로 바꾼다 (서버의 SHEETS_SECRET 과 같게)
// 4. 배포 → 새 배포 → 유형: 웹 앱
//      다음 사용자로 실행: 나 / 액세스 권한이 있는 사용자: 모든 사용자 → 배포 → 권한 허용
// 5. 나오는 웹 앱 URL(https://script.google.com/macros/s/.../exec)을 서버의 SHEETS_URL 에 넣는다
//
// 시트 탭은 자동으로 생김: responses (참가자×목록), items (영화별 평가), raw (참가자 전체 기록 백업)

const SECRET = 'CHANGE_ME_TO_A_LONG_RANDOM_STRING';

function doPost(e) {
  const lock = LockService.getScriptLock();
  lock.waitLock(30000);
  try {
    const data = JSON.parse(e.postData.contents);
    if (data.secret !== SECRET) return out({ ok: false, error: 'forbidden' });
    const ss = SpreadsheetApp.getActiveSpreadsheet();
    Object.keys(data.sheets).forEach(function (name) {
      appendRows(ss, name, data.sheets[name]);
    });
    return out({ ok: true });
  } catch (err) {
    return out({ ok: false, error: String(err) });
  } finally {
    lock.releaseLock();
  }
}

function appendRows(ss, name, rows) {
  if (!rows || !rows.length) return;
  const sh = ss.getSheetByName(name) || ss.insertSheet(name);
  let header = sh.getLastRow() ? sh.getRange(1, 1, 1, sh.getLastColumn()).getValues()[0] : [];
  const keys = [];
  rows.forEach(function (r) { Object.keys(r).forEach(function (k) { if (keys.indexOf(k) < 0) keys.push(k); }); });
  const extra = keys.filter(function (k) { return header.indexOf(k) < 0; });
  if (extra.length) {                                   // 새 열이 있으면 머리글에 추가
    header = header.concat(extra);
    sh.getRange(1, 1, 1, header.length).setValues([header]);
    sh.setFrozenRows(1);
  }
  const values = rows.map(function (r) {
    return header.map(function (k) { return r[k] === undefined || r[k] === null ? '' : r[k]; });
  });
  sh.getRange(sh.getLastRow() + 1, 1, values.length, header.length).setValues(values);
}

function out(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}
