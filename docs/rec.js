// 추천 계산 (브라우저에서 실행) — ALS fold-in, 감정 다양화, 조작 점검 지표, 시트에 넣을 행 만들기
// 파이썬 recommender.py / export.py 와 같은 계산
(function (root) {
  const EMOTIONS = ["joy", "trust", "fear", "surprise", "sadness", "disgust", "anger", "anticipation"];
  const N_SHOW = 10, N_ALS_TOP = 200;

  // ───────── ALS (원 논문 평점 모델) ─────────
  function solve(A, b) {                      // 가우스 소거 (부분 피벗)
    const n = b.length, M = A.map((row, i) => [...row, b[i]]);
    for (let c = 0; c < n; c++) {
      let p = c;
      for (let r = c + 1; r < n; r++) if (Math.abs(M[r][c]) > Math.abs(M[p][c])) p = r;
      [M[c], M[p]] = [M[p], M[c]];
      for (let r = c + 1; r < n; r++) {
        const f = M[r][c] / M[c][c];
        for (let k = c; k <= n; k++) M[r][k] -= f * M[c][k];
      }
    }
    const x = new Array(n).fill(0);
    for (let r = n - 1; r >= 0; r--) {
      let s = M[r][n];
      for (let k = r + 1; k < n; k++) s -= M[r][k] * x[k];
      x[r] = s / M[r][r];
    }
    return x;
  }

  // als = {ids, pos: Map(id→행), bi, mu, reg, k, Q: Float32Array(n*k)}
  function alsTop(als, likedIds, n = N_ALS_TOP, likedRating = 5) {
    const idx = likedIds.map((m) => als.pos.get(m)).filter((i) => i !== undefined);
    if (!idx.length) throw new Error("선호 영화가 ALS 모델에 없어요");
    const d = als.k + 1;
    const X = idx.map((i) => [1, ...Array.from(als.Q.subarray(i * als.k, (i + 1) * als.k))]);
    const y = idx.map((i) => likedRating - als.mu - als.bi[i]);
    const A = Array.from({ length: d }, (_, a) => Array.from({ length: d }, (_, b) =>
      X.reduce((s, row) => s + row[a] * row[b], 0) + (a === b ? als.reg * idx.length : 0)));
    const rhs = Array.from({ length: d }, (_, a) => X.reduce((s, row, r) => s + row[a] * y[r], 0));
    const sol = solve(A, rhs);
    const scores = new Float64Array(als.ids.length);
    for (let i = 0; i < als.ids.length; i++) {
      let s = als.mu + als.bi[i] + sol[0];
      const off = i * als.k;
      for (let f = 0; f < als.k; f++) s += als.Q[off + f] * sol[f + 1];
      scores[i] = s;
    }
    idx.forEach((i) => (scores[i] = -Infinity));
    const order = Array.from(scores.keys()).sort((a, b) => scores[b] - scores[a]).slice(0, n);
    return order.map((i) => ({ id: als.ids[i], score: scores[i] }));
  }

  // ───────── 감정 다양화 (Lansman et al. 2025, Table 2) ─────────
  function diversify(ids, sigOf, h = N_SHOW) {
    const Q = ids.map((id) => EMOTIONS.map((e) => sigOf(id)[e]));
    const l1 = (a, b) => a.reduce((s, v, i) => s + Math.abs(v - b[i]), 0);
    const centroid = EMOTIONS.map((_, j) => Q.reduce((s, q) => s + q[j], 0) / Q.length);
    let remaining = ids.map((_, i) => i);
    const first = remaining.reduce((best, i) => (l1(Q[i], centroid) < l1(Q[best], centroid) ? i : best));
    const chosen = [first];
    remaining = remaining.filter((i) => i !== first);
    while (chosen.length < h && remaining.length) {
      const dist = (i) => chosen.reduce((s, c) => s + l1(Q[i], Q[c]), 0);
      const nxt = remaining.reduce((best, i) => (dist(i) > dist(best) ? i : best));
      chosen.push(nxt);
      remaining = remaining.filter((i) => i !== nxt);
    }
    return chosen.map((i) => ids[i]);
  }

  // ───────── 조작 점검 지표 (데이터셋 감정 시그니처) ─────────
  const sigs = (list) => list.filter((m) => m.signature).map((m) => EMOTIONS.map((e) => m.signature[e]));
  const pairs = (n) => { const p = []; for (let i = 0; i < n; i++) for (let j = i + 1; j < n; j++) p.push([i, j]); return p; };
  const mean = (a) => a.reduce((s, v) => s + v, 0) / a.length;
  function aesr(list) {
    const Q = sigs(list);
    if (Q.length < 2) return null;
    return mean(EMOTIONS.map((_, j) => Math.max(...Q.map((q) => q[j])) - Math.min(...Q.map((q) => q[j]))));
  }
  function aeed(list) {
    const Q = sigs(list);
    if (Q.length < 2) return null;
    return mean(pairs(Q.length).map(([i, j]) => Math.sqrt(Q[i].reduce((s, v, k) => s + (v - Q[j][k]) ** 2, 0))));
  }
  function aghd(list, nGenres = 19) {
    const G = list.map((m) => new Set(String(m.genres || "").split(",").map((g) => g.trim()).filter(Boolean)));
    return mean(pairs(G.length).map(([i, j]) => {
      let d = 0;
      G[i].forEach((g) => { if (!G[j].has(g)) d++; });
      G[j].forEach((g) => { if (!G[i].has(g)) d++; });
      return d / nGenres;
    }));
  }
  const r3 = (v) => (v === null || v === undefined || Number.isNaN(v) ? null : Math.round(v * 1000) / 1000);

  // ───────── 시트에 넣을 행 ─────────
  // st: 참가자 상태, m: "gemini"|"emotion", pos: 1|2, survey: survey.json
  function rows(st, m, pos, survey) {
    const list = st.lists[m], keys = list.map((c) => c.key);
    const ch = st.choices[m], rt = st.ratings[m] || [], sv = st.surveys[m] || {};
    const byKey = Object.fromEntries(list.map((c) => [c.key, c]));
    const resp = {
      pid: st.pid, ext_id: st.ext_id || "", order_code: st.order_code, list_pos: pos, method: m, query: st.query,
      choice_title: ch ? byKey[ch].title : null, choice_pos: ch ? keys.indexOf(ch) + 1 : null,
      mean_like: rt.length ? r3(mean(rt.map((x) => x.like))) : null,
      fit_rate: rt.length ? r3(mean(rt.map((x) => (x.fit ? 1 : 0)))) : null,
      seen_n: rt.filter((x) => x.seen).length,
      sig_n: sigs(list).length, AESR: r3(aesr(list)), AEED: r3(aeed(list)), AGHD: r3(aghd(list)),
      attention_ok: sv[survey.attention.code] === survey.attention.answer,
    };
    const scored = survey.items.filter((it) => it.code !== survey.attention.code);
    scored.forEach((it) => (resp[it.code] = sv[it.code] ?? null));       // 원점수
    [...new Set(scored.map((it) => it.construct))].forEach((k) => {     // 구성개념 평균 (역문항 8-점수)
      const v = scored.filter((it) => it.construct === k && sv[it.code] != null)
        .map((it) => (it.reverse ? 8 - sv[it.code] : sv[it.code]));
      resp[`${k}_mean`] = v.length ? r3(mean(v)) : null;
    });
    resp.comment = pos === 2 ? st.comment || "" : "";
    resp.saved_at = new Date().toISOString();
    const items = rt.map((x) => {
      const c = byKey[x.id], sig = c.signature || {};
      return {
        pid: st.pid, order_code: st.order_code, list_pos: pos, method: m, movie_key: x.id, imdb_id: c.imdb_id || "",
        title: c.title, year: c.year, genres: c.genres, display_pos: keys.indexOf(x.id) + 1, source_rank: c.rank,
        seen: x.seen, like: x.like, fit: x.fit, chosen: x.id === ch,
        ...Object.fromEntries(EMOTIONS.map((e) => [`emo_${e}`, sig[e] ?? null])),
      };
    });
    return { resp, items };
  }

  const Rec = { EMOTIONS, N_SHOW, N_ALS_TOP, solve, alsTop, diversify, aesr, aeed, aghd, rows };
  if (typeof module !== "undefined") module.exports = Rec; else root.Rec = Rec;
})(this);
