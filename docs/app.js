// 흐름: 동의 → 선호작 5편 → 질의 → [목록 1 선택 → 평가 → 설문] → 안내 → [목록 2 선택 → 평가 → 설문 + 자유 의견] → 완료
// 계산(ALS·감정 다양화)은 브라우저에서, Gemini·TMDB·저장은 Apps Script(CONFIG.SCRIPT_URL)에서
const $ = (s) => document.querySelector(s);
const STEPS = ["consent", "liked", "query", "loading", "recs", "ratings", "survey", "next", "done"];
const LIST_NAME = ["첫 번째 추천 목록", "두 번째 추천 목록"];
const ORDER = { A: ["gemini", "emotion"], B: ["emotion", "gemini"] };

const S = JSON.parse(sessionStorage.getItem("state") || "null") || {
  step: "consent", pid: null, ext_id: null, order_code: null, liked: [], query: "",
  lists: {}, li: 0, choices: {}, ratings: {}, surveys: {}, survey_orders: {}, comment: "", gemini_log: null,
  started: null, sel: [null, null],
};
const save = () => sessionStorage.setItem("state", JSON.stringify(S));
const method = (i = S.li) => ORDER[S.order_code][i];

// ───────── 데이터 불러오기 ─────────
const DATA = { movies: null, byId: null, als: null, survey: null };
const dataReady = (async () => {
  const [mv, meta, qbuf, survey] = await Promise.all([
    fetch("data/movies.json").then((r) => r.json()),
    fetch("data/als.json").then((r) => r.json()),
    fetch("data/als_q.bin").then((r) => r.arrayBuffer()),
    fetch("data/survey.json").then((r) => r.json()),
  ]);
  const ci = Object.fromEntries(mv.cols.map((c, i) => [c, i]));
  DATA.movies = mv.rows.map((r) => ({
    id: r[ci.id], title: r[ci.title], year: r[ci.year], genres: r[ci.genres], plot: r[ci.plot],
    signature: Object.fromEntries(Rec.EMOTIONS.map((e) => [e, r[ci[e]]])), _t: r[ci.title].toLowerCase(),
  }));
  DATA.byId = new Map(DATA.movies.map((m) => [m.id, m]));
  DATA.als = { ...meta, Q: new Float32Array(qbuf), pos: new Map(meta.ids.map((id, i) => [id, i])) };
  DATA.survey = survey;
  const st = $("#data-status");
  if (st) st.hidden = true;
})().catch((e) => { toast("데이터를 불러오지 못했어요. 새로고침해 주세요."); throw e; });

// ───────── Apps Script 호출 ─────────
async function callScript(action, payload) {
  const res = await fetch(CONFIG.SCRIPT_URL, {
    method: "POST", body: JSON.stringify({ action, ...payload }),
    headers: { "Content-Type": "text/plain;charset=utf-8" },     // 사전 요청(CORS preflight) 피하기
  });
  const data = await res.json();
  if (!data.ok) throw new Error(data.error || "서버 오류가 발생했어요");
  return data;
}

// 저장은 실패해도 잃지 않게: 대기열(localStorage)에 넣고 성공할 때까지 재시도
const QKEY = "pendingSaves";
const queue = () => JSON.parse(localStorage.getItem(QKEY) || "[]");
async function flushSaves() {
  let q = queue();
  while (q.length) {
    try { await callScript("save", { sheets: q[0] }); }
    catch (e) { console.warn("저장 재시도 예정", e); return false; }
    q = queue().slice(1);
    localStorage.setItem(QKEY, JSON.stringify(q));
  }
  return true;
}
async function saveSheets(sheets) {
  localStorage.setItem(QKEY, JSON.stringify([...queue(), sheets]));
  for (let i = 0; i < 4; i++) {
    if (await flushSaves()) return true;
    await new Promise((r) => setTimeout(r, 2000 * (i + 1)));
  }
  return false;
}

// ───────── 화면 공통 ─────────
function progress(step) {
  const n = { liked: 1, query: 2, loading: 2, recs: 3 + S.li * 3, ratings: 4 + S.li * 3, survey: 5 + S.li * 3, next: 5 }[step];
  return n ? `단계 ${n}/8` : "";
}
function show(step) {
  S.step = step; save();
  STEPS.forEach((s) => ($(`#s-${s}`).hidden = s !== step));
  $("#progress").textContent = progress(step);
  document.querySelectorAll(".echo-query").forEach((el) => (el.textContent = S.query));
  window.scrollTo(0, 0);
  ({ liked: renderLiked, recs: renderRecs, ratings: renderRatings, survey: renderSurvey })[step]?.();
}
function toast(msg) {
  const t = $("#toast"); t.textContent = msg; t.hidden = false;
  clearTimeout(toast.t); toast.t = setTimeout(() => (t.hidden = true), 4000);
}
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const poster = (id) => `posters/${id}.jpg`;
const noPoster = (m) => `<div class="noposter"><b>${esc(m.title)}</b><span>${m.year}</span></div>`;
const recImg = (m) => m.poster       // 포스터가 없거나 못 불러오면 제목 카드
  ? `<img src="${esc(m.poster)}" alt="" onerror="this.outerHTML=this.nextElementSibling.innerHTML"><template>${noPoster(m)}</template>`
  : noPoster(m);
const shown = (i = S.li) => S.lists[method(i)];
const card = (c) => ({ id: c.key, title: c.title, year: c.year, genres: c.genres, plot: c.plot, poster: c.poster });
const hex = (n) => Array.from(crypto.getRandomValues(new Uint8Array(n)), (b) => b.toString(16).padStart(2, "0")).join("");

// ── 0. 동의
$("#agree").onchange = (e) => ($("#btn-start").disabled = !e.target.checked);
$("#btn-start").onclick = async () => {
  $("#btn-start").disabled = true;
  try {
    const pid = hex(8), ext = new URLSearchParams(location.search).get("id");
    const r = await callScript("start", { pid, ext_id: ext });
    Object.assign(S, { pid, ext_id: ext, order_code: r.order_code, started: new Date().toISOString() });
    show("liked");
  } catch (e) { toast(e.message); $("#btn-start").disabled = false; }
};

// ── 1. 좋아하는 영화 5편
function renderLiked() {
  const slots = [...S.liked, ...Array(5 - S.liked.length).fill(null)];
  $("#picked").innerHTML = slots.map((m, i) => m
    ? `<div class="slot"><img src="${poster(m.id)}" alt=""><button class="remove" data-i="${i}" title="빼기">×</button>${esc(m.title)}</div>`
    : `<div class="slot empty"></div>`).join("");
  $("#picked").querySelectorAll(".remove").forEach((b) => (b.onclick = () => {
    S.liked.splice(+b.dataset.i, 1); renderLiked(); runSearch();
  }));
  $("#btn-liked").disabled = S.liked.length !== 5;
  $("#btn-liked").textContent = `다음 (${S.liked.length}/5)`;
  save();
}
let searchTimer;
$("#search").oninput = () => { clearTimeout(searchTimer); searchTimer = setTimeout(runSearch, 200); };
async function runSearch() {
  await dataReady;
  const q = $("#search").value.trim().toLowerCase();
  if (q.length < 2) { $("#results").innerHTML = ""; return; }
  const list = DATA.movies.filter((m) => m._t.includes(q))
    .sort((a, b) => (b._t.startsWith(q) - a._t.startsWith(q)) || a.year - b.year).slice(0, 20);
  const picked = new Set(S.liked.map((m) => m.id));
  $("#results").innerHTML = list.length
    ? list.map((m) => `<li data-id="${m.id}" class="${picked.has(m.id) || S.liked.length >= 5 ? "disabled" : ""}">
        <img src="${poster(m.id)}" alt="" loading="lazy"><div><div>${esc(m.title)}</div>
        <div class="meta">${m.year} · ${esc(m.genres)}</div></div></li>`).join("")
    : `<li class="disabled">검색 결과가 없어요</li>`;
  $("#results").querySelectorAll("li[data-id]").forEach((li) => (li.onclick = () => {
    if (li.classList.contains("disabled")) return;
    const m = DATA.byId.get(li.dataset.id);
    S.liked.push({ id: m.id, title: m.title, year: m.year, genres: m.genres });
    renderLiked(); runSearch();
  }));
}
$("#btn-liked").onclick = () => show("query");

// ── 2. 질의 → 두 목록 만들기
$("#query").oninput = (e) => ($("#btn-query").disabled = e.target.value.trim().length < 5);
$("#btn-query").onclick = async () => {
  S.query = $("#query").value.trim();
  show("loading");
  try {
    await dataReady;
    const likedIds = S.liked.map((m) => m.id);
    // 감정 목록 (원 논문): ALS 상위 200편 → 감정 시그니처 다양화 10편 → ALS 순위 순
    const top = Rec.alsTop(DATA.als, likedIds);
    const rank = new Map(top.map((t, i) => [t.id, i + 1]));
    const picked = Rec.diversify(top.map((t) => t.id), (id) => DATA.byId.get(id).signature)
      .sort((a, b) => rank.get(a) - rank.get(b));
    // Gemini 목록 + 감정 목록의 TMDB 정보
    const liked = likedIds.map((id) => {
      const m = DATA.byId.get(id);
      return { title: m.title, year: m.year, genres: m.genres, plot: m.plot, imdb_id: id };
    });
    const r = await callScript("recommend", { query: S.query, liked, als_ids: picked });
    S.lists = {
      gemini: r.gemini.map((c) => ({ ...c, source: "gemini", signature: DATA.byId.get(c.imdb_id)?.signature || null })),
      emotion: picked.map((id) => {
        const m = DATA.byId.get(id), t = r.emotion_cards[id];
        const info = t || { tmdb_id: null, title: m.title, year: m.year, plot: m.plot, genres: m.genres, poster: poster(id) };
        return { ...info, imdb_id: id, key: `imdb:${id}`, source: "als", rank: rank.get(id), signature: m.signature };
      }),
    };
    S.gemini_log = r.gemini_log;
    S.li = 0; S.sel = [null, null];
    show("recs");
  } catch (e) { console.error(e); toast(e.message); show("query"); }
};

// ── 3. 추천 목록 + 선택
function renderRecs() {
  $("#list-badge").textContent = LIST_NAME[S.li];
  $("#grid").innerHTML = shown().map(card).map((m) => `
    <div class="poster ${m.id === S.sel[S.li] ? "selected" : ""}" data-id="${m.id}">
      ${recImg(m)}
      <div class="info"><b>${esc(m.title)} (${m.year})</b><div class="g">${esc(m.genres)}</div>${esc(m.plot)}</div>
    </div>`).join("");
  $("#grid").querySelectorAll(".poster").forEach((el) => {
    el.onclick = () => { S.sel[S.li] = el.dataset.id; save(); renderRecs(); };
    el.ontouchstart = () => el.classList.add("touch");
  });
  $("#btn-choice").disabled = !S.sel[S.li];
}
$("#btn-choice").onclick = () => { S.choices[method()] = S.sel[S.li]; show("ratings"); };

// ── 4. 영화별 평가
const Q = [
  ["seen", "이 영화를 본 적이 있나요?", [["true", "예"], ["false", "아니오"]]],
  ["like", "이 영화를 얼마나 좋아할 것 같나요?", [1, 2, 3, 4, 5].map((n) => [String(n), String(n)])],
  ["fit", "이 영화가 내 요청에 맞나요?", [["true", "예"], ["false", "아니오"]]],
];
function renderRatings() {
  $("#rate-badge").textContent = LIST_NAME[S.li];
  $("#rate-warn").textContent = "";
  $("#rate-list").innerHTML = shown().map(card).map((m) => `
    <div class="rate" data-id="${m.id}">
      <div class="thumb">${recImg(m)}</div>
      <div class="body">
        <div class="t">${esc(m.title)} (${m.year})${m.id === S.sel[S.li] ? '<span class="chosen-tag">내가 고른 영화</span>' : ""}</div>
        <div class="g">${esc(m.genres)}</div><div class="p">${esc(m.plot)}</div>
        ${Q.map(([k, label, opts]) => `<div class="q"><span class="label">${label}</span><div class="opts">
          ${opts.map(([v, t]) => `<label><input type="radio" name="${k}-${S.li}-${m.id}" value="${v}">${t}</label>`).join("")}
          </div>${k === "like" ? '<span class="muted" style="font-size:12px">1 전혀 아니다 · 5 매우 좋아할 것</span>' : ""}</div>`).join("")}
      </div>
    </div>`).join("");
}
$("#btn-ratings").onclick = () => {
  const ratings = []; let missing = 0;
  document.querySelectorAll(".rate").forEach((el) => {
    const id = el.dataset.id;
    const v = (k) => document.querySelector(`input[name="${k}-${S.li}-${CSS.escape(id)}"]:checked`)?.value;
    const ok = Q.every(([k]) => v(k));
    el.classList.toggle("missing", !ok);
    if (!ok) { missing++; return; }
    ratings.push({ id, seen: v("seen") === "true", like: +v("like"), fit: v("fit") === "true" });
  });
  if (missing) { $("#rate-warn").textContent = `응답하지 않은 영화가 ${missing}편 있어요`; return; }
  S.ratings[method()] = ratings;
  show("survey");
};

// ── 5. 목록별 설문 (두 번째 목록에는 자유 의견 칸)
async function renderSurvey() {
  await dataReady;
  const m = method(), sv = DATA.survey;
  if (!S.survey_orders[m]) {                    // 참가자·목록마다 순서 섞기, 주의 확인은 중간에
    const codes = sv.items.map((it) => it.code).filter((c) => c !== sv.attention.code);
    for (let i = codes.length - 1; i > 0; i--) { const j = Math.floor(Math.random() * (i + 1)); [codes[i], codes[j]] = [codes[j], codes[i]]; }
    codes.splice(Math.floor(codes.length / 2), 0, sv.attention.code);
    S.survey_orders[m] = codes; save();
  }
  const text = Object.fromEntries(sv.items.map((it) => [it.code, it.text]));
  $("#survey-badge").textContent = LIST_NAME[S.li];
  $("#survey-title").textContent = LIST_NAME[S.li];
  $("#survey-warn").textContent = "";
  $("#comment-box").hidden = S.li !== 1;
  $("#survey-list").innerHTML = S.survey_orders[m].map((c, i) => `
    <div class="item" data-code="${c}"><div class="text">${i + 1}. ${esc(text[c])}</div>
      <div class="likert">${sv.scale.map((s, j) => `<label><input type="radio" name="sv-${S.li}-${c}" value="${j + 1}">${s}</label>`).join("")}</div>
    </div>`).join("");
}
$("#btn-survey").onclick = async () => {
  const answers = {}; let missing = 0;
  document.querySelectorAll("#survey-list .item").forEach((el) => {
    const v = document.querySelector(`input[name="sv-${S.li}-${el.dataset.code}"]:checked`)?.value;
    el.classList.toggle("missing", !v);
    if (v) answers[el.dataset.code] = +v; else missing++;
  });
  if (missing) { $("#survey-warn").textContent = `응답하지 않은 문항이 ${missing}개 있어요`; return; }
  const m = method(), pos = S.li + 1;
  S.surveys[m] = answers;
  if (S.li === 1) S.comment = $("#comment").value.trim().slice(0, 5000);
  save();
  const { resp, items } = Rec.rows(S, m, pos, DATA.survey);
  const sheets = { responses: [resp], items };
  if (S.li === 1) {
    sheets.raw = [{ pid: S.pid, saved: new Date().toISOString(), record: JSON.stringify({
      order_code: S.order_code, ext_id: S.ext_id, started: S.started, liked: S.liked.map((x) => x.id), query: S.query,
      lists: Object.fromEntries(Object.entries(S.lists).map(([k, l]) => [k, l.map((c) => ({
        key: c.key, imdb_id: c.imdb_id, title: c.title, year: c.year, rank: c.rank }))])),
      choices: S.choices, ratings: S.ratings, surveys: S.surveys, survey_orders: S.survey_orders,
      comment: S.comment, gemini_log: S.gemini_log }) }];
  }
  $("#btn-survey").disabled = true;
  const ok = await saveSheets(sheets);
  $("#btn-survey").disabled = false;
  if (!ok) toast("저장이 지연되고 있어요. 이 창을 닫지 않으면 자동으로 다시 시도해요.");
  if (S.li === 0) { show("next"); return; }
  show("done");
  sessionStorage.removeItem("state");
};
$("#btn-next").onclick = () => { S.li = 1; show("recs"); };

// 저장 못 한 응답이 있으면 다시 시도
flushSaves();
setInterval(flushSaves, 30000);

// 새로고침해도 진행 중이던 단계로 (로딩 중이었으면 질의 단계로)
show(S.step === "loading" ? "query" : S.step);
if (S.step === "query") $("#query").value = S.query;
