// =====================================================================
// 영화 추천 실험 — 구글 Apps Script 서버 (응답 시트에 붙어 있는 스크립트)
//
// 하는 일
//   start     : 참가자 목록 순서 배정 (A: Gemini 먼저 / B: 감정 먼저, 인원 균형) + sessions 시트에 기록
//   recommend : Gemini 추천(선호작 5편 + 요청) → TMDB로 실존 확인·포스터
//               + 브라우저가 계산한 감정 목록(IMDb ID)의 TMDB 정보
//   save      : 응답을 시트에 추가 (responses / items / raw)
//
// 설정
//   1. 응답 시트 → 확장 프로그램 → Apps Script → 이 코드 전체로 바꾸고 저장
//   2. 왼쪽 톱니바퀴(프로젝트 설정) → 스크립트 속성 → 아래 두 개 추가
//        GEMINI_API_KEY  = 제미나이 키
//        TMDB_API_KEY    = TMDB 키 (API 키 또는 읽기 토큰)
//      (선택) GEN_MODEL = gemini-3-flash-preview, THINKING_LEVEL = low
//   3. 배포 → 새 배포 → 웹 앱 / 실행: 나 / 액세스: 모든 사용자 → 배포
//      (이미 배포했다면: 배포 관리 → 수정 → 버전: 새 버전 → 배포. 주소는 그대로)
//   4. 웹 앱 URL(…/exec)을 docs/config.js 의 SCRIPT_URL 에 넣기
// =====================================================================

const MIN_YEAR = 2000;
const N_SHOW = 10;
const N_REQUEST = 12;            // TMDB에서 못 찾는 영화 대비 여유 2편
const MAX_RECOMMEND_PER_MIN = 30; // 남용 방지

function doPost(e) {
  try {
    const req = JSON.parse(e.postData.contents);
    const fn = { start: start_, recommend: recommend_, save: save_ }[req.action];
    if (!fn) return out_({ ok: false, error: 'unknown action' });
    return out_(Object.assign({ ok: true }, fn(req)));
  } catch (err) {
    console.error(err && err.stack || err);
    return out_({ ok: false, error: String(err && err.message || err) });
  }
}

function doGet() {
  return out_({ ok: true, msg: 'movie study server is running' });
}

function out_(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}

function prop_(k, d) {
  return PropertiesService.getScriptProperties().getProperty(k) || d;
}

// ───────── start: 순서 배정 ─────────
function start_(req) {
  if (!/^[0-9a-f]{16}$/.test(req.pid || '')) throw new Error('bad pid');
  const lock = LockService.getScriptLock();
  lock.waitLock(20000);
  try {
    const props = PropertiesService.getScriptProperties();
    const nA = Number(props.getProperty('COUNT_A') || 0), nB = Number(props.getProperty('COUNT_B') || 0);
    const code = nA < nB ? 'A' : nB < nA ? 'B' : (Math.random() < 0.5 ? 'A' : 'B');
    props.setProperty('COUNT_' + code, String((code === 'A' ? nA : nB) + 1));
    appendRows_('sessions', [{ pid: req.pid, order_code: code, ext_id: req.ext_id || '',
                               started: new Date() }]);
    return { order_code: code };
  } finally {
    lock.releaseLock();
  }
}

// ───────── save: 시트에 행 추가 ─────────
function save_(req) {
  const lock = LockService.getScriptLock();
  lock.waitLock(30000);
  try {
    Object.keys(req.sheets || {}).forEach(function (name) {
      if (['responses', 'items', 'raw'].indexOf(name) < 0) throw new Error('bad sheet ' + name);
      appendRows_(name, req.sheets[name]);
    });
    return {};
  } finally {
    lock.releaseLock();
  }
}

function appendRows_(name, rows) {
  if (!rows || !rows.length) return;
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sh = ss.getSheetByName(name) || ss.insertSheet(name);
  let header = sh.getLastRow() ? sh.getRange(1, 1, 1, sh.getLastColumn()).getValues()[0] : [];
  const keys = [];
  rows.forEach(function (r) { Object.keys(r).forEach(function (k) { if (keys.indexOf(k) < 0) keys.push(k); }); });
  const extra = keys.filter(function (k) { return header.indexOf(k) < 0; });
  if (extra.length) {
    header = header.concat(extra);
    sh.getRange(1, 1, 1, header.length).setValues([header]);
    sh.setFrozenRows(1);
  }
  const values = rows.map(function (r) {
    return header.map(function (k) {
      const v = r[k];
      if (v === undefined || v === null) return '';
      if (typeof v === 'object' && !(v instanceof Date)) return JSON.stringify(v).slice(0, 49000);
      return typeof v === 'string' ? v.slice(0, 49000) : v;
    });
  });
  sh.getRange(sh.getLastRow() + 1, 1, values.length, header.length).setValues(values);
}

// ───────── recommend ─────────
function recommend_(req) {
  rateLimit_();
  const liked = req.liked || [];
  if (liked.length !== 5 || !req.query || String(req.query).trim().length < 5) throw new Error('bad input');
  const log = {};
  const gemini = geminiList_(String(req.query).trim().slice(0, 1000), liked, log);
  const emotionCards = findImdb_((req.als_ids || []).slice(0, N_SHOW));
  return { gemini: gemini, gemini_log: log, emotion_cards: emotionCards };
}

function rateLimit_() {
  const cache = CacheService.getScriptCache();
  const key = 'rec_' + Math.floor(Date.now() / 60000);
  const n = Number(cache.get(key) || 0) + 1;
  cache.put(key, String(n), 120);
  if (n > MAX_RECOMMEND_PER_MIN) throw new Error('지금 참여자가 많아요. 1분 뒤 다시 시도해 주세요');
}

// ───────── Gemini ─────────
function buildPrompt_(query, liked) {
  const lines = liked.map(function (m) {
    return '- ' + m.title + ' (' + m.year + ') | Genres: ' + m.genres + ' | Plot: ' + m.plot;
  }).join('\n');
  return 'You are a movie recommendation assistant.\n\n' +
    'The user likes these movies:\n' + lines + '\n\n' +
    "The user's request:\n\"" + query + '"\n\n' +
    'Recommend ' + N_REQUEST + ' real movies released in ' + MIN_YEAR + ' or later that best satisfy the user\'s request ' +
    'and match their taste, ranked from most to least recommended. ' +
    'Do not include the movies the user already listed.\n' +
    'For each movie give the exact English title and the release year.';
}

function callGemini_(prompt) {
  const key = prop_('GEMINI_API_KEY');
  if (!key) throw new Error('GEMINI_API_KEY 스크립트 속성이 없어요');
  const model = prop_('GEN_MODEL', 'gemini-3-flash-preview');
  const url = 'https://generativelanguage.googleapis.com/v1beta/models/' + model + ':generateContent';
  const body = {
    contents: [{ role: 'user', parts: [{ text: prompt }] }],
    generationConfig: {
      responseMimeType: 'application/json',
      responseSchema: {
        type: 'ARRAY',
        items: { type: 'OBJECT', properties: { title: { type: 'STRING' }, year: { type: 'INTEGER' } },
                 required: ['title', 'year'] },
      },
      thinkingConfig: { thinkingLevel: prop_('THINKING_LEVEL', 'low') },
    },
  };
  const res = UrlFetchApp.fetch(url, {
    method: 'post', contentType: 'application/json', payload: JSON.stringify(body),
    headers: { 'x-goog-api-key': key }, muteHttpExceptions: true,
  });
  if (res.getResponseCode() !== 200) {
    throw new Error('Gemini ' + res.getResponseCode() + ': ' + res.getContentText().slice(0, 300));
  }
  const parts = ((JSON.parse(res.getContentText()).candidates || [])[0] || {}).content;
  const text = ((parts && parts.parts) || []).filter(function (p) { return p.text && !p.thought; })
    .map(function (p) { return p.text; }).join('');
  try {
    return JSON.parse(text);
  } catch (err) {
    const m = text.match(/\[[\s\S]*\]/);
    return m ? JSON.parse(m[0]) : [];
  }
}

function normTitle_(t) {
  return String(t || '').normalize('NFKD').replace(/[̀-ͯ]/g, '').toLowerCase()
    .replace(/^(the|a|an) /, '').replace(/[^a-z0-9]/g, '');
}

function cleanCandidates_(raw, liked) {
  const likedKeys = liked.map(function (m) { return normTitle_(m.title); });
  const seen = {}, out = [];
  (Array.isArray(raw) ? raw : []).forEach(function (c) {
    const year = parseInt(c && c.year, 10), key = normTitle_(c && c.title);
    if (!key || !(year >= MIN_YEAR) || likedKeys.indexOf(key) >= 0 || seen[key]) return;
    seen[key] = true;
    out.push({ title: String(c.title).trim(), year: year });
  });
  return out;
}

function geminiList_(query, liked, log) {
  const prompt = buildPrompt_(query, liked);
  log.prompt = prompt;
  log.model = prop_('GEN_MODEL', 'gemini-3-flash-preview');
  log.raw = [];
  log.not_found = [];
  const likedImdb = liked.map(function (m) { return m.imdb_id; });
  const pool = [];
  for (let attempt = 0; attempt < 2 && pool.length < N_SHOW; attempt++) {
    const raw = callGemini_(prompt);
    log.raw.push(raw);
    const cands = cleanCandidates_(raw, liked);
    const found = tmdbSearch_(cands);
    cands.forEach(function (c, i) {
      const f = found[i];
      const dup = f && pool.some(function (p) { return p.tmdb_id === f.tmdb_id; });
      if (!f || !(f.year >= MIN_YEAR) || dup || likedImdb.indexOf(f.imdb_id) >= 0) {
        log.not_found.push(c.title + ' (' + c.year + ')');
        return;
      }
      f.llm_title = c.title;
      f.llm_year = c.year;
      pool.push(f);
    });
  }
  if (pool.length < N_SHOW) throw new Error('추천 영화가 ' + pool.length + '편밖에 확인되지 않았어요. 다시 시도해 주세요');
  return pool.slice(0, N_SHOW).map(function (c, i) {
    c.key = 'tmdb:' + c.tmdb_id;
    c.rank = i + 1;
    return c;
  });
}

// ───────── TMDB ─────────
const TMDB = 'https://api.themoviedb.org/3';
const IMG = 'https://image.tmdb.org/t/p/w342';

function tmdbAll_(reqs) {      // reqs: [{path, params}] → [json|null]
  const key = prop_('TMDB_API_KEY');
  if (!key) throw new Error('TMDB_API_KEY 스크립트 속성이 없어요');
  const bearer = key.length > 40;
  const fetches = reqs.map(function (r) {
    const p = Object.assign({ language: 'en-US' }, r.params || {});
    if (!bearer) p.api_key = key;
    const qs = Object.keys(p).map(function (k) { return k + '=' + encodeURIComponent(p[k]); }).join('&');
    return { url: TMDB + r.path + '?' + qs, muteHttpExceptions: true,
             headers: bearer ? { Authorization: 'Bearer ' + key } : {} };
  });
  if (!fetches.length) return [];
  return UrlFetchApp.fetchAll(fetches).map(function (res) {
    return res.getResponseCode() === 200 ? JSON.parse(res.getContentText()) : null;
  });
}

function genres_() {
  const cache = CacheService.getScriptCache();
  const hit = cache.get('genres');
  if (hit) return JSON.parse(hit);
  const g = {};
  ((tmdbAll_([{ path: '/genre/movie/list' }])[0] || {}).genres || []).forEach(function (x) { g[x.id] = x.name; });
  cache.put('genres', JSON.stringify(g), 21600);
  return g;
}

function card_(m, G) {
  const y = (m.release_date || '').slice(0, 4);
  return {
    tmdb_id: m.id, title: m.title, year: /^\d{4}$/.test(y) ? Number(y) : null,
    poster: m.poster_path ? IMG + m.poster_path : null, plot: m.overview || '',
    genres: (m.genre_ids || []).map(function (id) { return G[id]; }).filter(Boolean).join(', '),
  };
}

function tmdbSearch_(cands) {   // Gemini 추천 → 카드 (+ IMDb ID), 못 찾으면 null
  const G = genres_();
  const first = tmdbAll_(cands.map(function (c) {
    return { path: '/search/movie', params: { query: c.title, primary_release_year: c.year, include_adult: 'false' } };
  }));
  const missing = [];
  cands.forEach(function (c, i) { if (!first[i] || !first[i].results.length) missing.push(i); });
  const second = tmdbAll_(missing.map(function (i) {
    return { path: '/search/movie', params: { query: cands[i].title, include_adult: 'false' } };
  }));
  const cards = cands.map(function (c, i) {
    let res = first[i] && first[i].results.length ? first[i].results : [];
    const j = missing.indexOf(i);
    if (j >= 0 && second[j]) {           // 연도가 1년 어긋난 경우 허용
      res = second[j].results.filter(function (m) {
        const y = Number((m.release_date || '').slice(0, 4));
        return y && Math.abs(y - c.year) <= 1;
      });
    }
    return res.length ? card_(res[0], G) : null;
  });
  const ext = tmdbAll_(cards.filter(Boolean).map(function (c) { return { path: '/movie/' + c.tmdb_id + '/external_ids' }; }));
  let k = 0;
  cards.forEach(function (c) { if (c) { c.imdb_id = (ext[k++] || {}).imdb_id || null; } });
  return cards;
}

function findImdb_(ids) {      // 감정 목록(IMDb ID) → {imdb: 카드|null}
  const G = genres_();
  const res = tmdbAll_(ids.map(function (id) { return { path: '/find/' + id, params: { external_source: 'imdb_id' } }; }));
  const out = {};
  ids.forEach(function (id, i) {
    const m = res[i] && res[i].movie_results && res[i].movie_results[0];
    out[id] = m ? Object.assign(card_(m, G), { imdb_id: id }) : null;
  });
  return out;
}
