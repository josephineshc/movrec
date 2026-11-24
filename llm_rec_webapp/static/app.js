// 실험 화면 흐름: 동의 → 선호 영화 5편 → 질의 → 추천 10편 → 선택 → 영화별 평가 → 설문 → 완료
const $ = (s) => document.querySelector(s);
const STEPS = ["consent", "liked", "query", "loading", "recs", "ratings", "survey", "gform", "done"];
const LABEL = { liked: "1/5", query: "2/5", loading: "2/5", recs: "3/5", ratings: "4/5", survey: "5/5" };

const S = JSON.parse(sessionStorage.getItem("state") || "null") || {
  step: "consent", pid: null, liked: [], query: "", recs: [], choice: null,
};
const save = () => sessionStorage.setItem("state", JSON.stringify(S));

function show(step) {
  S.step = step; save();
  STEPS.forEach((s) => ($(`#s-${s}`).hidden = s !== step));
  $("#progress").textContent = LABEL[step] ? `단계 ${LABEL[step]}` : "";
  window.scrollTo(0, 0);
  ({ liked: renderLiked, recs: renderRecs, ratings: renderRatings, survey: loadSurvey, gform: () => ($("#gform-link").href = S.gform) })[step]?.();
}

async function api(path, body) {
  const res = await fetch(path, body
    ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }
    : {});
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || "오류가 발생했어요. 잠시 후 다시 시도해 주세요.");
  return data;
}
function toast(msg) {
  const t = $("#toast"); t.textContent = msg; t.hidden = false;
  clearTimeout(toast.t); toast.t = setTimeout(() => (t.hidden = true), 3500);
}
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const poster = (id) => `/poster/${id}.jpg`;                       // 데이터셋 영화 (선호작 고르기)
const recImg = (m) => m.poster                                       // 추천 영화 (TMDB 포스터, 없으면 제목 카드)
  ? `<img src="${esc(m.poster)}" alt="${esc(m.title)}">`
  : `<div class="noposter"><b>${esc(m.title)}</b><span>${m.year}</span></div>`;

// ── 0. 동의
$("#agree").onchange = (e) => ($("#btn-start").disabled = !e.target.checked);
$("#btn-start").onclick = async () => {
  $("#btn-start").disabled = true;
  try {
    const ext = new URLSearchParams(location.search).get("id");
    S.pid = (await api("/api/start", { ext_id: ext })).pid;
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
$("#search").oninput = () => { clearTimeout(searchTimer); searchTimer = setTimeout(runSearch, 250); };
async function runSearch() {
  const q = $("#search").value.trim();
  if (q.length < 2) { $("#results").innerHTML = ""; return; }
  const list = await api(`/api/search?q=${encodeURIComponent(q)}`);
  const picked = new Set(S.liked.map((m) => m.id));
  $("#results").innerHTML = list.length
    ? list.map((m) => `<li data-id="${m.id}" class="${picked.has(m.id) || S.liked.length >= 5 ? "disabled" : ""}">
        <img src="${poster(m.id)}" alt="" loading="lazy"><div><div>${esc(m.title)}</div>
        <div class="meta">${m.year} · ${esc(m.genres)}</div></div></li>`).join("")
    : `<li class="disabled">검색 결과가 없어요</li>`;
  $("#results").querySelectorAll("li[data-id]").forEach((li) => (li.onclick = () => {
    if (li.classList.contains("disabled")) return;
    S.liked.push(list.find((m) => m.id === li.dataset.id));
    renderLiked(); runSearch();
  }));
}
$("#btn-liked").onclick = () => show("query");

// ── 2. 질의 → 추천
$("#query").oninput = (e) => ($("#btn-query").disabled = e.target.value.trim().length < 5);
$("#btn-query").onclick = async () => {
  S.query = $("#query").value.trim();
  show("loading");
  try {
    const r = await api("/api/recommend", { pid: S.pid, liked: S.liked.map((m) => m.id), query: S.query });
    S.recs = r.movies; S.choice = null;
    show("recs");
  } catch (e) { toast(e.message); show("query"); }
};

// ── 3. 추천 목록 + 선택
function renderRecs() {
  $("#echo-query").textContent = S.query;
  $("#grid").innerHTML = S.recs.map((m) => `
    <div class="poster ${m.id === S.choice ? "selected" : ""}" data-id="${m.id}">
      ${recImg(m)}
      <div class="info"><b>${esc(m.title)} (${m.year})</b><div class="g">${esc(m.genres)}</div>${esc(m.plot)}</div>
    </div>`).join("");
  $("#grid").querySelectorAll(".poster").forEach((el) => {
    el.onclick = () => { S.choice = el.dataset.id; save(); renderRecs(); };
    el.ontouchstart = () => el.classList.add("touch");          // 터치 기기: 탭하면 정보 표시
  });
  $("#btn-choice").disabled = !S.choice;
}
$("#btn-choice").onclick = async () => {
  try { await api("/api/choice", { pid: S.pid, movie_id: S.choice }); show("ratings"); }
  catch (e) { toast(e.message); }
};

// ── 4. 영화별 평가
const Q = [
  ["seen", "이 영화를 본 적이 있나요?", [["true", "예"], ["false", "아니오"]]],
  ["like", "이 영화를 얼마나 좋아할 것 같나요?", [1, 2, 3, 4, 5].map((n) => [String(n), String(n)])],
  ["fit", "이 영화가 내 요청에 맞나요?", [["true", "예"], ["false", "아니오"]]],
];
function renderRatings() {
  $("#echo-query2").textContent = S.query;
  $("#rate-list").innerHTML = S.recs.map((m) => `
    <div class="rate" data-id="${m.id}">
      <div class="thumb">${recImg(m)}</div>
      <div class="body">
        <div class="t">${esc(m.title)} (${m.year})${m.id === S.choice ? '<span class="chosen-tag">내가 고른 영화</span>' : ""}</div>
        <div class="g">${esc(m.genres)}</div><div class="p">${esc(m.plot)}</div>
        ${Q.map(([k, label, opts]) => `<div class="q"><span class="label">${label}</span><div class="opts">
          ${opts.map(([v, t]) => `<label><input type="radio" name="${k}-${m.id}" value="${v}">${t}</label>`).join("")}
          </div>${k === "like" ? '<span class="muted" style="font-size:12px">1 전혀 아니다 · 5 매우 좋아할 것</span>' : ""}</div>`).join("")}
      </div>
    </div>`).join("");
}
$("#btn-ratings").onclick = async () => {
  const ratings = []; let missing = 0;
  document.querySelectorAll(".rate").forEach((el) => {
    const id = el.dataset.id;
    const v = (k) => document.querySelector(`input[name="${k}-${id}"]:checked`)?.value;
    const ok = Q.every(([k]) => v(k));
    el.classList.toggle("missing", !ok);
    if (!ok) { missing++; return; }
    ratings.push({ id, seen: v("seen") === "true", like: +v("like"), fit: v("fit") === "true" });
  });
  if (missing) { $("#rate-warn").textContent = `응답하지 않은 영화가 ${missing}편 있어요`; return; }
  try {
    const r = await api("/api/ratings", { pid: S.pid, ratings });
    if (r.survey_url) { S.gform = r.survey_url; show("gform"); } else show("survey");
  } catch (e) { toast(e.message); }
};

// ── 5. 설문
async function loadSurvey() {
  const { items, scale } = await api(`/api/survey?pid=${S.pid}`);
  $("#survey-list").innerHTML = items.map((it, i) => `
    <div class="item" data-code="${it.code}"><div class="text">${i + 1}. ${esc(it.text)}</div>
      <div class="likert">${scale.map((s, j) => `<label><input type="radio" name="${it.code}" value="${j + 1}">${s}</label>`).join("")}</div>
    </div>`).join("");
}
$("#btn-survey").onclick = async () => {
  const answers = {}; let missing = 0;
  document.querySelectorAll(".item").forEach((el) => {
    const v = document.querySelector(`input[name="${el.dataset.code}"]:checked`)?.value;
    el.classList.toggle("missing", !v);
    if (v) answers[el.dataset.code] = +v; else missing++;
  });
  if (missing) { $("#survey-warn").textContent = `응답하지 않은 문항이 ${missing}개 있어요`; return; }
  try {
    const { code } = await api("/api/survey", { pid: S.pid, answers });
    $("#code").textContent = code; show("done");
    sessionStorage.removeItem("state");
  } catch (e) { toast(e.message); }
};

// 새로고침해도 진행 중이던 단계로 (로딩 중이었으면 질의 단계로)
show(S.step === "loading" ? "query" : S.step);
if (S.step === "query") $("#query").value = S.query;
