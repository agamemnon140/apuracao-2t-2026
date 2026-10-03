/* Mapa da apuracao: BR -> UF -> municipio -> zona -> local -> secao, 2022 x 2026. */
(function () {
  "use strict";
  const $ = (s) => document.querySelector(s);
  const fmt = new Intl.NumberFormat("pt-BR");
  const pct = (x, d = 1) => (x == null || !isFinite(x) ? "–" : x.toLocaleString("pt-BR", { minimumFractionDigits: d, maximumFractionDigits: d }) + "%");
  const sinal = (x, d = 1) => (x == null || !isFinite(x) ? "–" : (x > 0 ? "+" : "") + x.toLocaleString("pt-BR", { minimumFractionDigits: d, maximumFractionDigits: d }));
  const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();

  const CARGOS = [["pr", "Presidente"], ["gov", "Governador"], ["sen", "Senador"], ["df", "Dep. federal"], ["de", "Dep. estadual"]];
  const NOME_UF = { AC: "Acre", AL: "Alagoas", AM: "Amazonas", AP: "Amapá", BA: "Bahia", CE: "Ceará", DF: "Distrito Federal", ES: "Espírito Santo", GO: "Goiás", MA: "Maranhão", MG: "Minas Gerais", MS: "Mato Grosso do Sul", MT: "Mato Grosso", PA: "Pará", PB: "Paraíba", PE: "Pernambuco", PI: "Piauí", PR: "Paraná", RJ: "Rio de Janeiro", RN: "Rio Grande do Norte", RO: "Rondônia", RR: "Roraima", RS: "Rio Grande do Sul", SC: "Santa Catarina", SE: "Sergipe", SP: "São Paulo", TO: "Tocantins", ZZ: "Exterior" };
  // divergente: vermelho = esquerda (Lula), azul = direita
  const RAMPA_E = ["#f5c4c0", "#e8837c", "#cf4a42", "#9e2a24"];
  const RAMPA_MAIS = ["#c3ecc7", "#7fd18a", "#37a34a", "#20702f"];
  const RAMPA_MENOS = ["#e8c9f2", "#c78bdd", "#9c4bbb", "#6b2e85"];
  const RAMPA_D = ["#b7d3f6", "#6da7ec", "#2a78d6", "#184f95"];
  const SEQ = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#1c5cab"];

  const S = { uf: null, mun: null, zona: null, local: null, secao: null, cargo: "pr", turno: 1, eixo: false, metrica: null, lente: "esq" };
  let FILTRO = "", ORDEM = "apt";          // busca e ordenacao da lista (nao vao para a URL)
  let LIVE_MUN = null;
  let META, BR, LIVE = null, LIVE_UF = {}, UFD = null, MUND = null, SECD = null, DEP = null, DEPM = null, GEO = {};

  // ------------------------------------------------------------ estado <-> URL
  function leHash() {
    const h = new URLSearchParams(location.hash.slice(1));
    S.uf = h.get("uf"); S.mun = h.get("mun"); S.zona = h.get("zona"); S.local = h.get("local"); S.secao = h.get("secao");
    S.cargo = h.get("cargo") || "pr"; S.turno = +(h.get("turno") || 1); S.eixo = h.get("eixo") === "1"; S.metrica = h.get("m");
    S.lente = h.get("lente") === "dir" ? "dir" : "esq";
  }
  function gravaHash() {
    const h = new URLSearchParams();
    for (const k of ["uf", "mun", "zona", "local", "secao"]) if (S[k] != null) h.set(k, S[k]);
    h.set("cargo", S.cargo); h.set("turno", S.turno); if (S.eixo) h.set("eixo", "1"); if (S.metrica) h.set("m", S.metrica);
    if (S.lente !== "esq") h.set("lente", S.lente);
    history.replaceState(null, "", "#" + h.toString());
  }
  function vai(mud) {
    if (["uf", "mun", "zona", "local", "secao"].some((k) => k in mud)) FILTRO = "";
    Object.assign(S, mud);
    gravaHash();
    render();
  }

  // ------------------------------------------------------------ candidatos, cores, categorias
  function corPartido(nr, ano) {
    const p = META.partidos[ano] && META.partidos[ano][String(nr).slice(0, 2)];
    return p ? p.cor : META.cores.outros;
  }
  function eixoPartido(nr, ano) {
    const p = META.partidos[ano] && META.partidos[ano][String(nr).slice(0, 2)];
    return p ? p.eixo : "centro";
  }
  function listaCands(cargo, turno) {
    if (cargo === "pr") return META.pr["2022"]["t" + turno] || [];
    if (!UFD) return [];
    const c = UFD.cands[cargo];
    return (c && c["2022"]["t" + turno]) || [];
  }
  const EXTRAS = () => [
    { nome: "Brancos", cor: css("--branco-v"), extra: true },
    { nome: "Nulos", cor: css("--nulo-v"), extra: true },
    { nome: "Abstenção", cor: css("--abst-v"), extra: true },
  ];

  /* vetor [cands..., branco, nulo, abst] -> categorias para as bolhas, com dobra em "Outros" */
  function categorias(vetor, cands, ano, bnJunto) {
    if (!vetor) return null;
    const nc = cands.length;
    const validos = vetor.slice(0, nc).reduce((a, b) => a + b, 0);
    let cats;
    if (S.eixo) {
      const g = { esquerda: 0, centro: 0, direita: 0 };
      cands.forEach((c, i) => { g[eixoPartido(c[0], ano)] += vetor[i]; });
      cats = [["esquerda", "Esquerda"], ["centro", "Centro"], ["direita", "Direita"]]
        .map(([k, n]) => ({ nome: n, cor: META.cores_eixo[k], n: g[k], valido: true }));
    } else {
      cats = [];
      let outros = 0;
      cands.forEach((c, i) => {
        const v = vetor[i] || 0;
        if (cats.length < 5 && validos && v / validos >= 0.025) cats.push({ nome: c[1], nr: c[0], partido: c[2], cor: corPartido(c[0], ano), n: v, valido: true });
        else outros += v;
      });
      if (outros) cats.push({ nome: "Outros", cor: META.cores.outros, n: outros, valido: true });
    }
    const ex = EXTRAS();
    if (bnJunto) {
      cats.push({ nome: "Brancos + nulos", cor: css("--nulo-v"), extra: true, n: (vetor[nc] || 0) + (vetor[nc + 1] || 0) });
      cats.push({ ...ex[2], n: vetor[nc + 2] || 0 });
    } else [vetor[nc], vetor[nc + 1], vetor[nc + 2]].forEach((v, i) => cats.push({ ...ex[i], n: v || 0 }));
    return cats;
  }

  function cats26(u) {
    const c = META.campos_2026;
    const lv = liveDaUnidade();
    const base = lv && lv.proj ? lv.proj : u && u.proj26;
    if (!base) return null;
    let [e, d, o, bn, ab] = base;
    if (S.turno === 2 && !(lv && lv.proj)) {         // 2o turno: terceiros se repartem entre os dois campos
      const v = e + d + o; e = v * e / (e + d); d = v - e; o = 0;
    }
    const ap = lv && lv.apur ? lv.apur : [0, 0, 0, 0, 0];
    const cats = S.eixo
      ? [{ nome: "Esquerda", cor: META.cores_eixo.esquerda, n: e, ap: ap[0], valido: true },
         { nome: "Direita", cor: META.cores_eixo.direita, n: d, ap: ap[1], valido: true },
         { nome: "Outros", cor: META.cores.outros, n: o, ap: ap[2], valido: true }]
      : [{ nome: c.esq[1], nr: c.esq[0], cor: corPartido(c.esq[0], "2026"), n: e, ap: ap[0], valido: true },
         { nome: c.dir[1], nr: c.dir[0], cor: corPartido(c.dir[0], "2026"), n: d, ap: ap[1], valido: true },
         { nome: "Outros", cor: META.cores.outros, n: o, ap: ap[2], valido: true }];
    cats.push({ nome: "Brancos + nulos", cor: css("--nulo-v"), n: bn, ap: ap[3], extra: true });
    cats.push({ nome: "Abstenção", cor: css("--abst-v"), n: ab, ap: ap[4], extra: true });
    return cats;
  }

  /* boletins raspados de 2026 (live/mun/{cd}.json, modo local/tunel) no nivel corrente */
  function registroBU() {
    if (!LIVE_MUN || (LIVE && (LIVE.turno || 1) !== S.turno)) return null;
    const nv = nivel();
    if (nv === "mun") return LIVE_MUN.mun;
    if (nv === "zona") return LIVE_MUN.zonas[S.zona];
    if (nv === "local") return LIVE_MUN.locais[`${S.zona}:${S.local}`];
    if (nv === "secao") return LIVE_MUN.secoes[`${S.zona}:${S.secao}`];
    return null;
  }
  function catsBU(rec, cargo) {
    const u = rec && rec[cargo];
    if (!u) return null;
    let cands, vet;
    if (cargo === "df" || cargo === "de") {
      const porP = {};
      for (const [nr, v] of Object.entries(u.c)) porP[nr.slice(0, 2)] = (porP[nr.slice(0, 2)] || 0) + v;
      for (const [p, v] of Object.entries(u.l)) porP[p] = (porP[p] || 0) + v;
      const ps = Object.entries(porP).sort((a, b) => b[1] - a[1]);
      cands = ps.map(([p]) => { const x = META.partidos["2026"][p] || {}; return [p, x.sigla || p, x.sigla || p]; });
      vet = ps.map((x) => x[1]);
    } else {
      const lista = cargo === "pr" ? META.pr["2026"].t1 : ((UFD && UFD.cands[cargo] && UFD.cands[cargo]["2026"]) || []);
      const nome = Object.fromEntries(lista.map((c) => [c[0], c]));
      const ord = Object.entries(u.c).sort((a, b) => b[1] - a[1]);
      cands = ord.map(([nr]) => nome[nr] || [nr, nr, ""]);
      vet = ord.map((x) => x[1]);
    }
    const ccBU = categorias(vet.concat([u.b, u.n, u.a]), cands, "2026");
    if (ccBU) for (const c of ccBU) c.ap = c.n;        // boletim de urna: tudo apurado
    return ccBU;
  }
  /* governador/senador na UF: vetor projetado ao vivo x validos esperados da ancora */
  function catsEstadualLive(u) {
    if (!LIVE || (LIVE.turno || 1) !== S.turno || nivel() !== "uf" || !(S.cargo === "gov" || S.cargo === "sen")) return null;
    const r = LIVE[S.cargo] && LIVE[S.cargo][S.uf];
    if (!r || !r.proj || !u || !u.proj26) return null;
    const [e, d, o, bn, ab] = u.proj26, val = e + d + o;
    const lista = (UFD.cands[S.cargo] && UFD.cands[S.cargo]["2026"]) || [];
    const nome = Object.fromEntries(lista.map((c) => [c[0], c]));
    const ord = Object.entries(r.proj).sort((a, b) => b[1] - a[1]);
    const ccEst = categorias(ord.map(([, sh]) => Math.round(sh * val)).concat([Math.round(bn / 2), Math.round(bn / 2), ab]),
      ord.map(([nr]) => nome[nr] || [nr, nr, ""]), "2026");
    if (ccEst) for (const c of ccEst) c.ap = 0;        // projecao do needle estadual
    return ccEst;
  }

  // ------------------------------------------------------------ unidade corrente
  function nivel() {
    if (S.secao != null) return "secao";
    if (S.local != null) return "local";
    if (S.zona != null) return "zona";
    if (S.mun != null) return "mun";
    if (S.uf != null) return "uf";
    return "br";
  }
  function linhaSecao(num) {
    if (!SECD) return null;
    const c = SECD.cols;
    const row = SECD.rows.find((r) => String(r[0]) === String(num));
    if (!row) return null;
    const o = {};
    c.forEach((k, i) => { o[k] = row[i]; });
    return o;
  }
  function unidade() {
    const nv = nivel();
    if (nv === "br") return BR && BR.br;
    if (nv === "uf") return UFD && UFD.tot;
    if (nv === "mun") return UFD && UFD.mun[S.mun];
    if (nv === "zona") return MUND && MUND.zonas[S.zona];
    if (nv === "local") return MUND && MUND.locais.find((l) => String(l.z) === String(S.zona) && String(l.l) === String(S.local));
    return linhaSecao(S.secao);
  }
  function chave22() {
    if (S.cargo === "df" || S.cargo === "de") return null;
    return `${S.cargo}22t${S.turno}`;
  }

  /* ao vivo da unidade: {apur:[e,d,o,bn,abst?], proj:[e,d,o,bn,abst], pct, sh_esq...} ou null */
  function liveDaUnidade() {
    if (!LIVE || !LIVE.pr || S.cargo !== "pr" || (LIVE.turno || 1) !== S.turno) return null;
    const nv = nivel();
    if (nv === "br") {
      const p = LIVE.pr, apt = BR && BR.br.aptos26;
      return { pct: LIVE.pct_secoes, proj: [p.proj.esq, p.proj.dir, p.proj.out, p.proj.bn, Math.max(0, (apt || p.proj.comp) - p.proj.comp)],
        apur: [p.apur.esq, p.apur.dir, Math.max(0, p.apur.val - p.apur.esq - p.apur.dir), p.apur.bn || 0, 0],
        sh_esq: p.sh_esq, sh_dir: p.sh_dir, apur_esq: p.apur.val ? 100 * p.apur.esq / p.apur.val : null, margem: p.margem, sigma: p.sigma };
    }
    if (nv === "uf") {
      const r = LIVE.ufs && LIVE.ufs[S.uf];
      if (!r) return null;
      const C = LIVE.ufs_cols, g = (k) => r[C.indexOf(k)];
      return { pct: g("pct"), sh_esq: g("proj_esq"), sh_dir: g("proj_dir"), apur_esq: g("apur_esq"), margem: g("margem"), sigma: g("sigma") };
    }
    if (nv === "mun") {
      const d = LIVE_UF[S.uf];
      if (!d) return null;
      const C = d.cols, r = d.mun.find((x) => String(x[0]) === String(S.mun));
      if (!r) return null;
      const g = (k) => r[C.indexOf(k)];
      const val = g("proj_val"), comp = g("proj_comp"), e = g("proj_esq"), dd = g("proj_dir");
      const apt = (UFD && UFD.mun[S.mun] && UFD.mun[S.mun].aptos26) || comp;
      return { pct: 100 * g("st") / Math.max(1, g("ts")), proj: [e, dd, val - e - dd, comp - val, Math.max(0, apt - comp)],
        apur: [g("apur_esq"), g("apur_dir"), Math.max(0, g("apur_val") - g("apur_esq") - g("apur_dir")), 0, 0],
        sh_esq: 100 * e / val, sh_dir: 100 * dd / val, apur_esq: g("apur_val") ? 100 * g("apur_esq") / g("apur_val") : null };
    }
    return null;
  }

  // ------------------------------------------------------------ metricas do mapa
  function idxCand(cands, nr) { return cands.findIndex((c) => c[0] === nr); }
  const nomeLente = () => (S.lente === "esq" ? META.campos_2026.esq[1] : META.campos_2026.dir[1]);
  /* votos totais de 2022 (1º turno): soma do vetor menos a abstenção (= comparecimento) */
  function votos22(r) {
    const v = r && r.pr22t1;
    if (!v) return null;
    let t = 0;
    for (let i = 0; i < v.length - 1; i++) t += v[i] || 0;
    return t;
  }
  /* fatia do candidato da lente nos VALIDOS (%), ao vivo quando ha, senao projecao demografica */
  function fatiaLente(r, id, filho) {
    const lv = filho != null ? liveFilho(id, filho) : liveDaUnidade();
    if (lv && lv.sh_esq != null && lv.sh_dir != null) return { v: S.lente === "esq" ? lv.sh_esq : lv.sh_dir, live: true };
    if (lv && S.lente === "esq" && lv.sh_esq != null) return { v: lv.sh_esq, live: true };
    if (!r || !r.proj26) return null;
    const [e, d, o] = r.proj26, val = e + d + o;
    if (!val) return null;
    return { v: 100 * (S.lente === "esq" ? e : d) / val, live: false };
  }
  function margemPr(vet, cands) {
    if (!vet) return null;
    const ie = idxCand(cands, "13"), id = idxCand(cands, "22");
    const val = vet.slice(0, cands.length).reduce((a, b) => a + b, 0);
    return val ? 100 * ((vet[ie] || 0) - (vet[id] || 0)) / val : null;
  }
  function metricas() {
    const m = [];
    if (S.cargo === "pr") {
      const nm = nomeLente();
      m.push(["dalvo", `${nm} − alvo de 50%+1 (pontos de válidos)`],
        ["alvo", `alvo de ${nm} (% dos válidos)`],
        ["m22t2", "2022 · 2º turno · margem Lula − Bolsonaro"],
        ["m22t1", "2022 · 1º turno · margem Lula − Bolsonaro"],
        ["m26", "2026 · projeção demográfica · margem"]);
    } else if (S.cargo === "gov" || S.cargo === "sen") {
      m.push(["venc", `2022 · ${S.turno}º turno · mais votado`]);
    }
    m.push(["abst", `2022 · ${S.turno}º turno · abstenção`]);
    return m;
  }
  function valorMetrica(r, id, filho) {
    if (!r) return null;
    const cpr = META.pr["2022"];
    switch (S.metrica) {
      case "m22t1": return { v: margemPr(r.pr22t1, cpr.t1), tipo: "div" };
      case "m22t2": return { v: margemPr(r.pr22t2, cpr.t2), tipo: "div" };
      case "m26": return r.proj26 ? { v: 100 * (r.proj26[0] - r.proj26[1]) / (r.proj26[0] + r.proj26[1] + r.proj26[2]), tipo: "div" } : null;
      case "alvo": return r.alvo26 ? { v: r.alvo26[S.lente === "esq" ? 0 : 1], tipo: "alvo" } : null;
      case "dalvo": {
        const f = fatiaLente(r, id, filho);
        if (!f || !r || !r.alvo26) return null;
        return { v: f.v - r.alvo26[S.lente === "esq" ? 0 : 1], tipo: "dalvo", live: f.live };
      }
      case "venc": {
        const k = chave22(), cands = listaCands(S.cargo, S.turno), vet = r[k];
        if (!vet) return null;
        let mi = 0; for (let i = 1; i < cands.length; i++) if (vet[i] > vet[mi]) mi = i;
        const val = vet.slice(0, cands.length).reduce((a, b) => a + b, 0);
        return { v: val ? 100 * vet[mi] / val : null, tipo: "venc", cor: corPartido(cands[mi][0], "2022"), quem: cands[mi][1] };
      }
      case "abst": {
        const k = chave22() || `pr22t${S.turno}`, vet = r[k] || r.pr22t1;
        if (!vet) return null;
        const tot = vet.reduce((a, b) => a + b, 0);
        return { v: tot ? 100 * vet[vet.length - 1] / tot : null, tipo: "seq" };
      }
    }
    return null;
  }
  function liveFilho(id, filho) {
    if (!LIVE) return null;
    if (filho === "uf") {
      const r = LIVE.ufs && LIVE.ufs[id]; if (!r) return null;
      const C = LIVE.ufs_cols;
      return { margem: r[C.indexOf("margem")], sh_esq: r[C.indexOf("proj_esq")], sh_dir: r[C.indexOf("proj_dir")] };
    }
    if (filho === "mun") {
      const d = LIVE_UF[S.uf]; if (!d) return null;
      const C = d.cols, r = d.mun.find((x) => String(x[0]) === String(id)); if (!r) return null;
      const g = (k) => r[C.indexOf(k)];
      return { margem: 100 * (g("proj_esq") - g("proj_dir")) / g("proj_val"), sh_esq: 100 * g("proj_esq") / g("proj_val"),
        sh_dir: 100 * g("proj_dir") / g("proj_val") };
    }
    return null;
  }
  function cor(mv) {
    if (!mv || mv.v == null || !isFinite(mv.v)) return css("--sem-dado");
    const v = mv.v;
    if (mv.tipo === "venc") return mv.cor;
    if (mv.tipo === "dalvo") {
      const a = Math.abs(v), lim = [0.75, 2.5, 6, 12];
      if (a < lim[0]) return css("--neutro");
      const k = a < lim[1] ? 0 : a < lim[2] ? 1 : a < lim[3] ? 2 : 3;
      return v > 0 ? RAMPA_MAIS[k] : RAMPA_MENOS[k];
    }
    if (mv.tipo === "seq") return SEQ[Math.min(4, Math.max(0, Math.floor((v - 10) / 5)))];
    let d = v;
    if (mv.tipo === "alvo") d = (v - 50) * 2;
    const lim = mv.tipo === "desvio" ? [0.5, 2, 5, 10] : [2, 8, 16, 30];
    const a = Math.abs(d);
    if (a < lim[0]) return css("--neutro");
    const k = a < lim[1] ? 0 : a < lim[2] ? 1 : a < lim[3] ? 2 : 3;
    return d > 0 ? RAMPA_E[k] : RAMPA_D[k];
  }
  function legendaMapa() {
    const el = $("#mapa-legenda");
    const t = S.metrica;
    if (t === "venc") { el.innerHTML = "cor do partido do mais votado"; return; }
    if (t === "abst") { el.innerHTML = `<span>10%</span><span class="rampa">${SEQ.map((c) => `<span style="background:${c}"></span>`).join("")}</span><span>35%+</span>`; return; }
    if (t === "dalvo") {
      const r2 = [...RAMPA_MENOS].reverse().concat([css("--neutro")]).concat(RAMPA_MAIS);
      el.innerHTML = `<span>${nomeLente()} abaixo do alvo</span><span class="rampa">${r2.map((c) => `<span style="background:${c}"></span>`).join("")}</span><span>acima do alvo</span>`;
      return;
    }
    const rot = t === "alvo" ? [`alvo de ${nomeLente()} < 50%`, "> 50%"] : ["direita à frente", "Lula à frente"];
    const r = [...RAMPA_D].reverse().concat([css("--neutro")]).concat(RAMPA_E);
    el.innerHTML = `<span>${rot[0]}</span><span class="rampa">${r.map((c) => `<span style="background:${c}"></span>`).join("")}</span><span>${rot[1]}</span>`;
  }

  // ------------------------------------------------------------ tooltip
  const tip = $("#tip");
  function mostraTip(ev, html) {
    tip.innerHTML = html; tip.hidden = false;
    const x = Math.min(ev.clientX + 14, window.innerWidth - 290);
    tip.style.left = x + "px"; tip.style.top = (ev.clientY + 14) + "px";
  }
  function escondeTip() { tip.hidden = true; }

  // ------------------------------------------------------------ mapa
  async function geo(nome) {
    if (!GEO[nome]) GEO[nome] = await Dados.json(`geo/${nome}.json`);
    return GEO[nome];
  }
  function svgBase() {
    const box = $("#mapa");
    box.innerHTML = "";
    const W = box.clientWidth || 500, H = box.clientHeight || W;
    const raiz = d3.select(box).append("svg").attr("viewBox", `0 0 ${W} ${H}`).attr("role", "img");
    const svg = raiz.append("g");
    return { svg, W, H };
  }
  async function desenhaMapa() {
    const nv = nivel();
    legendaMapa();
    if (nv === "br") {
      const t = await geo("br");
      const fc = topojson.feature(t, t.objects.a);
      const { svg, W, H } = svgBase();
      const proj = d3.geoMercator().fitSize([W, H], fc), path = d3.geoPath(proj);
      svg.selectAll("path").data(fc.features).join("path").attr("class", "area").attr("d", path)
        .attr("fill", (f) => cor(valorMetrica(BR.ufs[f.properties.id], f.properties.id, "uf")))
        .on("mousemove", (ev, f) => { const r = BR.ufs[f.properties.id]; mostraTip(ev, tipUnidade(NOME_UF[f.properties.id], r, f.properties.id, "uf")); })
        .on("mouseleave", escondeTip)
        .on("click", (ev, f) => vai({ uf: f.properties.id, mun: null, zona: null, local: null, secao: null }));
      return;
    }
    if (S.uf === "ZZ") { svgBase().svg.append("text").attr("x", 20).attr("y", 30).attr("fill", css("--muda")).text("Exterior: sem mapa — use a lista."); return; }
    const t = await geo(S.uf);
    const fc = topojson.feature(t, t.objects.a);
    if (nv === "uf") {
      const { svg, W, H } = svgBase();
      const proj = d3.geoMercator().fitSize([W, H], fc), path = d3.geoPath(proj);
      svg.selectAll("path").data(fc.features).join("path").attr("class", "area").attr("d", path)
        .attr("fill", (f) => cor(valorMetrica(UFD.mun[f.properties.id], f.properties.id, "mun")))
        .on("mousemove", (ev, f) => { const r = UFD.mun[f.properties.id]; mostraTip(ev, tipUnidade(r ? r.nome : f.properties.id, r, f.properties.id, "mun")); })
        .on("mouseleave", escondeTip)
        .on("click", (ev, f) => vai({ mun: String(f.properties.id), zona: null, local: null, secao: null }));
      return;
    }
    // municipio e abaixo: contorno + locais de votacao como pontos
    const feat = fc.features.find((f) => String(f.properties.id) === String(S.mun));
    const { svg, W, H } = svgBase();
    const locais = (MUND ? MUND.locais : []).filter((l) => l.lat != null && !l.so22 && (S.zona == null || String(l.z) === String(S.zona)));
    const pts = { type: "FeatureCollection", features: locais.map((l) => ({ type: "Feature", geometry: { type: "Point", coordinates: [l.lon, l.lat] } })) };
    const alvoFit = pts.features.length > 2 ? pts : (feat || pts);
    const proj = d3.geoMercator().fitExtent([[14, 14], [W - 14, H - 14]], alvoFit), path = d3.geoPath(proj);
    if (feat) svg.append("path").attr("class", "contorno").attr("d", path(feat));
    const maxA = d3.max(locais, (l) => l.aptos26 || 1) || 1;
    const rr = d3.scaleSqrt().domain([0, maxA]).range([2, Math.max(5, Math.min(W, H) / 38)]);
    svg.selectAll("circle").data(locais).join("circle").attr("class", (l) => "ponto" + (String(l.l) === String(S.local) && String(l.z) === String(S.zona) ? " ativo" : ""))
      .attr("cx", (l) => proj([l.lon, l.lat])[0]).attr("cy", (l) => proj([l.lon, l.lat])[1]).attr("r", (l) => rr(l.aptos26 || 1))
      .attr("fill", (l) => cor(valorMetrica(l, null, "local")))
      .on("mousemove", (ev, l) => mostraTip(ev, tipUnidade(`${l.nome || "Local " + l.l}<br><span style="color:var(--muda)">zona ${l.z} · ${l.bairro || ""}</span>`, l, null, "local")))
      .on("mouseleave", escondeTip)
      .on("click", (ev, l) => vai({ zona: String(l.z), local: String(l.l), secao: null }));
  }
  function tipUnidade(nome, r, id, filho) {
    if (!r) return `<b>${nome}</b><br>sem dados`;
    const mv = valorMetrica(r, id, filho);
    const txt = !mv || mv.v == null ? "–" : mv.tipo === "venc" ? `${mv.quem}: ${pct(mv.v)}` : mv.tipo === "alvo" || mv.tipo === "seq" ? pct(mv.v) : sinal(mv.v) + " pts";
    const extraLente = mv && mv.tipo === "dalvo" ? `<br><span style="color:var(--muda)">${mv.live ? "projeção ao vivo" : "projeção demográfica"} de ${nomeLente()}</span>` : "";
    return `<b>${nome}</b><br>${(metricas().find((m) => m[0] === S.metrica) || ["", ""])[1]}: <b>${txt}</b>${extraLente}<br>aptos 2026: ${fmt.format(r.aptos26 || 0)}`;
  }

  // ------------------------------------------------------------ lista de filhos
  function listaFilhos() {
    const nv = nivel(), el = $("#lista");
    let linhas = [], cab = "";
    const col = (r, id, f) => { const mv = valorMetrica(r, id, f); return mv && mv.v != null ? (mv.tipo === "venc" ? mv.quem.split(" ")[0] + " " + pct(mv.v, 0) : mv.tipo === "alvo" || mv.tipo === "seq" ? pct(mv.v) : sinal(mv.v)) : "–"; };
    const v22col = (r) => { const t = votos22(r); return t == null ? "–" : fmt.format(t); };
    const nomeMet = (metricas().find((m) => m[0] === S.metrica) || ["", "métrica"])[1];
    if (nv === "br") {
      cab = "Estado";
      linhas = Object.entries(BR.ufs).map(([uf, r]) => ({ id: uf, nome: NOME_UF[uf] || uf, apt: r.aptos26, v22: v22col(r), v22n: votos22(r), mvv: (valorMetrica(r, uf, "uf") || {}).v, v: col(r, uf, "uf"), cor: cor(valorMetrica(r, uf, "uf")), ir: () => vai({ uf, mun: null, zona: null, local: null, secao: null }) }));
    } else if (nv === "uf") {
      cab = "Município";
      linhas = Object.entries(UFD.mun).map(([cd, r]) => ({ id: cd, nome: r.nome, apt: r.aptos26, v22: v22col(r), v22n: votos22(r), mvv: (valorMetrica(r, cd, "mun") || {}).v, v: col(r, cd, "mun"), cor: cor(valorMetrica(r, cd, "mun")), ir: () => vai({ mun: cd, zona: null, local: null, secao: null }) }));
    } else if (nv === "mun" && MUND) {
      cab = "Zona";
      linhas = Object.entries(MUND.zonas).map(([z, r]) => ({ id: z, nome: `Zona ${z} · ${r.ns} urnas`, apt: r.aptos26, v22: v22col(r), v22n: votos22(r), mvv: (valorMetrica(r, null, "zona") || {}).v, v: col(r, null, "zona"), cor: cor(valorMetrica(r, null, "zona")), ir: () => vai({ zona: z, local: null, secao: null }) }));
    } else if (nv === "zona" && MUND) {
      cab = "Local de votação";
      linhas = MUND.locais.filter((l) => String(l.z) === String(S.zona)).map((l) => ({ id: l.l, nome: (l.nome || "Local " + l.l) + (l.so22 ? " (só 2022)" : ""), apt: l.aptos26, v22: v22col(l), v22n: votos22(l), mvv: (valorMetrica(l, null, "local") || {}).v, v: col(l, null, "local"), cor: cor(valorMetrica(l, null, "local")), ir: () => vai({ local: String(l.l), secao: null }) }));
    } else if ((nv === "local" || nv === "secao") && SECD) {
      cab = "Seção";
      const i = SECD.cols.indexOf("nr_local");
      linhas = SECD.rows.filter((r) => String(r[i]) === String(S.local)).map((r) => {
        const o = {}; SECD.cols.forEach((k, j) => { o[k] = r[j]; });
        return { id: r[0], nome: `Seção ${r[0]}` + (o.n_agreg > 1 ? ` (+${o.n_agreg - 1} agregada)` : ""), apt: o.aptos26, v22: v22col(o), v22n: votos22(o), mvv: (valorMetrica(o, null, "secao") || {}).v, v: col(o, null, "secao"), cor: cor(valorMetrica(o, null, "secao")), ir: () => vai({ secao: String(r[0]) }) };
      });
    }
    if (!linhas.length) { el.innerHTML = ""; return; }
    const chata = (x) => String(x).toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "");
    el.innerHTML = `<div class="lista-barra">
        <input id="lb-busca" type="search" placeholder="buscar ${cab.toLowerCase()} por nome ou número" aria-label="buscar na lista">
        <select id="lb-ordem" aria-label="ordenar lista">
          <option value="apt">maiores (aptos 2026)</option>
          <option value="nome">A → Z</option>
          <option value="v22">mais votos em 2022</option>
          <option value="mv">${S.metrica === "dalvo" ? "× alvo (maior → menor)" : "métrica do mapa"}</option>
        </select></div>
      <table><thead><tr><th>${cab} <span style="font-weight:400;color:var(--muda)">· toque para abrir</span></th><th class="num">votos 2022</th><th class="num">aptos 2026</th><th class="num" title="${nomeMet}">${S.metrica === "dalvo" ? "× alvo" : "mapa"}</th><th></th></tr></thead><tbody id="lb-corpo"></tbody></table>`;
    const busca = el.querySelector("#lb-busca"), ordem = el.querySelector("#lb-ordem");
    busca.value = FILTRO;
    ordem.value = ORDEM;
    let visiveis = [];
    const corpo = () => {
      const q = chata(FILTRO.trim());
      visiveis = linhas.filter((l) => !q || chata(l.nome + " " + l.id).includes(q));
      const vn = (x) => (x == null || isNaN(x) ? -Infinity : +x);
      if (ORDEM === "nome") visiveis.sort((a, b) => String(a.nome).localeCompare(String(b.nome), "pt", { numeric: true }));
      else if (ORDEM === "v22") visiveis.sort((a, b) => vn(b.v22n) - vn(a.v22n));
      else if (ORDEM === "mv") visiveis.sort((a, b) => vn(b.mvv) - vn(a.mvv));
      else visiveis.sort((a, b) => (b.apt || 0) - (a.apt || 0));
      const tb = el.querySelector("#lb-corpo");
      tb.innerHTML = visiveis.map((l, k) => `<tr class="clica" data-k="${k}"><td><span class="barrinha" style="width:8px;background:${l.cor}"></span> ${l.nome}</td><td class="num">${l.v22 || "–"}</td><td class="num">${fmt.format(l.apt || 0)}</td><td class="num">${l.v}</td><td class="seta">›</td></tr>`).join("")
        || `<tr><td colspan="5" style="color:var(--muda)">nada encontrado — limpe a busca</td></tr>`;
      tb.querySelectorAll("tr.clica").forEach((tr) => tr.addEventListener("click", () => visiveis[+tr.dataset.k].ir()));
    };
    corpo();
    busca.addEventListener("input", (e) => { FILTRO = e.target.value; corpo(); });
    ordem.addEventListener("change", (e) => { ORDEM = e.target.value; corpo(); });
  }

  // ------------------------------------------------------------ paineis
  function selo26(cats) {
    if (!cats || !cats.some((c) => c.ap != null)) return "";
    const tot = cats.reduce((a, c) => a + (c.n || 0), 0);
    const ap = cats.reduce((a, c) => a + Math.min(c.ap == null ? c.n : c.ap, c.n || 0), 0);
    if (ap <= 0) return ' <span class="selo selo-proj">projeção</span>';
    if (ap >= 0.999 * tot) return ' <span class="selo selo-apur">apurado</span>';
    return ' <span class="selo selo-parcial">parcial — sólido = apurado</span>';
  }

  function painel(el, titulo, nota, cats, esc) {
    if (!cats) { el.innerHTML = `<h3>${titulo}</h3><div class="vazio">${nota}</div>`; return; }
    titulo += selo26(cats);
    const tot = cats.reduce((a, c) => a + (c.n || 0), 0);
    const vot = tot - cats.filter((c) => c.nome === "Abstenção").reduce((a, c) => a + c.n, 0);
    el.innerHTML = `<h3>${titulo}</h3><p class="nota">${nota} · ${fmt.format(Math.round(vot))} votos de ${fmt.format(Math.round(tot))} eleitores · 1 ponto = ${esc.porPonto === 1 ? "1 eleitor" : fmt.format(esc.porPonto) + " eleitores"}</p><canvas></canvas>
      <div class="leg">${cats.filter((c) => c.n > 0).map((c) => `<span><i style="background:${c.cor}"></i>${c.nome}</span>`).join("")}</div>`;
    const cv = el.querySelector("canvas");
    const hit = Bolhas.desenha(cv, cats, esc);
    const validos = cats.filter((c) => c.valido).reduce((a, c) => a + c.n, 0);
    cv.addEventListener("mousemove", (ev) => {
      const b = cv.getBoundingClientRect(), c = hit(ev.clientX - b.left, ev.clientY - b.top);
      if (!c) return escondeTip();
      mostraTip(ev, `<b>${c.nome}</b>${c.partido ? " · " + c.partido : ""}<br>${fmt.format(c.n)} ${c.extra && c.nome === "Abstenção" ? "eleitores" : "votos"}<br>` +
        (c.valido ? `${pct(100 * c.n / validos)} dos válidos · ` : "") + `${pct(100 * c.n / tot)} dos aptos`);
    });
    cv.addEventListener("mouseleave", escondeTip);
  }

  function tabela(c22, c26) {
    const el = $("#tabela");
    if (!c22 && !c26) { el.innerHTML = ""; return; }
    const v22 = c22 ? c22.filter((c) => c.valido).reduce((a, c) => a + c.n, 0) : 0;
    const v26 = c26 ? c26.filter((c) => c.valido).reduce((a, c) => a + c.n, 0) : 0;
    const t22 = c22 ? c22.reduce((a, c) => a + c.n, 0) : 0, t26 = c26 ? c26.reduce((a, c) => a + c.n, 0) : 0;
    const chave = (c) => (c.nr && !S.eixo ? "nr" + c.nr : c.nome);
    const nomes = [];
    for (const c of [...(c22 || []), ...(c26 || [])]) if (!nomes.some((x) => x.k === chave(c))) nomes.push({ k: chave(c), c });
    const acha = (lista, k) => lista && lista.find((x) => chave(x) === k);
    const temAp = (c26 || []).some((c) => c.ap != null && c.ap > 0 && c.ap < 0.999 * c.n);
    const proj26q = (c26 || []).some((c) => c.ap != null && c.ap < 0.999 * (c.n || 0));
    const linhas = nomes.map(({ k, c }) => {
      const a = acha(c22, k), b = acha(c26, k);
      const base22 = c.valido ? v22 : t22, base26 = c.valido ? v26 : t26;
      const p22 = a && base22 ? 100 * a.n / base22 : null, p26 = b && base26 ? 100 * b.n / base26 : null;
      const dlt = p22 != null && p26 != null ? p26 - p22 : null;
      const bProj = b && b.ap != null && b.ap < 0.999 * (b.n || 0);
      const cel26 = !b ? "–" : (bProj ? `<span class="projetado" title="projeção — ainda não apurado por completo">≈ ${fmt.format(Math.round(b.n))}</span>` : fmt.format(Math.round(b.n)));
      const celAp = temAp ? `<td>${b && b.ap != null ? fmt.format(Math.round(b.ap)) : "–"}</td>` : "";
      return `<tr><td><i style="background:${c.cor}"></i>${c.nome}${c.nr && c.nome !== "Outros" ? ` <span style="color:var(--muda)">${c.nr}</span>` : ""}</td>
        <td>${a ? fmt.format(a.n) : "–"}</td><td>${pct(p22)}</td><td>${cel26}</td><td class="${bProj ? "projetado" : ""}">${pct(p26)}</td>${celAp}
        <td class="${dlt > 0 ? "delta-pos" : dlt < 0 ? "delta-neg" : ""}">${dlt == null ? "–" : sinal(dlt)}</td></tr>`;
    });
    let extras = [];
    if (!S.eixo && (S.cargo === "pr" || S.cargo === "gov" || S.cargo === "sen")) {
      const lista26 = S.cargo === "pr" ? (META.pr["2026"] && META.pr["2026"].t1) || []
        : (UFD && UFD.cands[S.cargo] && UFD.cands[S.cargo]["2026"]) || [];
      const ja = new Set((c26 || []).filter((c) => c.nr).map((c) => c.nr));
      const nc = temAp ? 7 : 6;
      extras = lista26.filter((c) => !ja.has(c[0])).map((c) =>
        `<tr><td><i style="background:${corPartido(c[0], "2026")}"></i>${c[1]} <span style="color:var(--muda)">${c[0]} · ${c[2]}</span></td><td>–</td><td>–</td><td>0</td><td>–</td>${temAp ? "<td>–</td>" : ""}<td>–</td></tr>`);
      if (extras.length) extras.unshift(`<tr><td colspan="${nc}" style="color:var(--muda);font-size:12px;padding-top:10px">Na urna em 2026 — os votos aparecem aqui com a apuração</td></tr>`);
    }
    el.innerHTML = `<table><thead><tr><th>categoria</th><th>2022</th><th>%</th><th>2026</th><th>%</th>${temAp ? "<th>apurado</th>" : ""}<th>Δ pts</th></tr></thead><tbody>${linhas.join("")}${extras.join("")}</tbody></table>
      <p class="nota" style="font-size:12px;color:var(--muda);margin:6px 0 2px">Candidatos: % dos válidos. Brancos, nulos e abstenção: % dos aptos.${proj26q ? " <b>≈</b> e pontos esmaecidos = projeção; números sem ≈ são votos apurados." : ""} Cores do mesmo partido em anos diferentes não são o mesmo candidato.</p>`;
  }

  function caixaAlvo(u) {
    const el = $("#alvo");
    if (S.cargo !== "pr" || !u || !u.alvo26) { el.innerHTML = ""; return; }
    const lv = liveDaUnidade();
    const c = META.campos_2026;
    const L = S.lente === "esq" ? 0 : 1;
    const cand = L === 0 ? c.esq : c.dir;
    const outro = L === 0 ? c.dir : c.esq;
    const corC = corPartido(cand[0], "2026");
    const cpr = META.pr["2022"];
    const t2 = u.pr22t2, ie = idxCand(cpr.t2, "13"), id = idxCand(cpr.t2, "22");
    const real22dois = t2 ? 100 * t2[L === 0 ? ie : id] / (t2[ie] + t2[id]) : null;
    const pv = u.proj26 ? u.proj26[0] + u.proj26[1] + u.proj26[2] : 0;
    const anc = pv ? 100 * u.proj26[L] / pv : null;
    const alvoC = u.alvo26[L], alvoO = u.alvo26[1 - L];
    const ancO = pv ? 100 * u.proj26[1 - L] / pv : null;
    const shLive = lv ? (L === 0 ? lv.sh_esq : lv.sh_dir) : null;
    const atual = shLive != null ? shLive : anc;
    const marcas = [
      { v: alvoC, nome: `alvo de ${cand[1]}`, cor: corC, oco: true },
      { v: anc, nome: "projeção demográfica", cor: css("--muda") },
      { v: real22dois, nome: "2022 · 2º turno (dois a dois)", cor: css("--tinta-2") },
    ];
    if (shLive != null) marcas.push({ v: shLive, nome: "ao vivo: projeção", cor: corC });
    const vs = marcas.map((m) => m.v).filter((v) => v != null && isFinite(v));
    const lo = Math.floor(Math.min(...vs, 50) - 3), hi = Math.ceil(Math.max(...vs, 50) + 3);
    const x = (v) => (100 * (v - lo) / (hi - lo)).toFixed(2) + "%";
    const nv = nivel();
    const dlt = atual != null && alvoC != null ? atual - alvoC : null;
    let numeros = `
      <div><div class="n" style="color:${corC}">≈ ${pct(atual)}</div><div class="r">${cand[1]} ${shLive != null ? `projeção ao vivo · ${pct(lv.pct, 0)} apurado` : "pela demografia"} (% dos válidos)</div></div>
      <div><div class="n">${pct(alvoC)}</div><div class="r">alvo de ${cand[1]} aqui (50%+1 no país)</div></div>
      <div><div class="n ${dlt >= 0 ? "delta-pos" : "delta-neg"}">${sinal(dlt)}</div><div class="r">${cand[1]} − alvo (pontos de válidos)</div></div>
      <div><div class="n">${pct(ancO)} <span style="font-size:14px;color:var(--muda)">alvo ${pct(alvoO)}</span></div><div class="r">${outro[1]}: projeção e alvo</div></div>`;
    if (nv === "br" && LIVE && LIVE.pr) {
      const p = LIVE.pr;
      numeros += `<div><div class="n">${pct(100 * p.p_lider, 1)}</div><div class="r">chance de ${p.lider} terminar à frente (±${p.sigma} pts)</div></div>
        <div><div class="n">${pct(100 * (L === 0 ? p.p_esq50 : p.p_dir50), 1)}</div><div class="r">chance de ${cand[1]} liquidar no 1º turno</div></div>`;
    }
    el.innerHTML = `<h3>Alvo de vitória no 1º turno — fatia dos válidos com ganho relativo igual em todo o país</h3>
      <div class="linhas">${numeros}</div>
      <div class="trilho"><div class="fundo"></div>${nv === "br" ? `<div class="meio" style="left:${x(50)}"></div>` : ""}
        ${marcas.filter((m) => m.v != null && isFinite(m.v)).map((m) => `<div class="marca ${m.oco ? "oco" : ""}" style="left:${x(m.v)};background:${m.cor};color:${m.cor}" title="${m.nome}: ${pct(m.v)}"></div>`).join("")}</div>
      <div class="leg-trilho">${marcas.filter((m) => m.v != null && isFinite(m.v)).map((m) => `<span><i style="background:${m.oco ? "transparent" : m.cor};border:2px solid ${m.cor}"></i>${m.nome} ${pct(m.v)}</span>`).join("")}
        <span style="margin-left:auto">escala ${lo}%–${hi}%</span></div>`;
  }

  async function painelDeputados(u) {
    const box = $("#deputados");
    const dep = S.cargo === "df" || S.cargo === "de";
    box.hidden = !dep;
    if (!dep) return null;
    if (!S.uf || S.uf === "ZZ") { box.innerHTML = "<p>Escolha um estado para ver os candidatos a deputado.</p>"; return null; }
    DEP = await Dados.json(`dep/${S.uf}.json`);
    const nv = nivel();
    let registro = null, linhas = null, nota = "", usouDepsec = false;
    if (nv !== "uf" && S.mun) {
      DEPM = await Dados.json(`dep/${S.uf}/${S.mun}.json`);
      const d = DEPM && DEPM[S.cargo];
      if (d) registro = nv === "mun" ? d.mun : (d.zonas[S.zona] || (Object.keys(d.zonas).length === 0 ? d.mun : null));
    }
    if (nv === "local" || nv === "secao") {
      const ds = await Dados.json(`depsec/${S.mun}/${S.zona}_${S.cargo}.json`);
      if (ds && ds.sec) {
        usouDepsec = true;
        let alvos;
        if (nv === "secao") alvos = [String(S.secao)];
        else {
          const i = SECD ? SECD.cols.indexOf("nr_local") : -1;
          alvos = SECD && i >= 0 ? SECD.rows.filter((r) => String(r[i]) === String(S.local)).map((r) => String(r[0])) : [];
        }
        const acc = {};
        for (const sNum of alvos) for (const [nr, v] of (ds.sec[sNum] || [])) acc[nr] = (acc[nr] || 0) + v;
        linhas = Object.entries(acc).sort((a, b) => b[1] - a[1]);
        if (nv === "local") nota = `<p class='nota'>Soma das ${alvos.length} urnas deste local.</p>`;
      } else {
        nota = "<p class='nota'>O detalhe por seção não está publicado no Pages (400 MB): disponível no modo local/túnel após <code>web.gera_estatico --depsec</code>. Abaixo, a zona.</p>";
        if (registro) linhas = registro.cands;
      }
    } else if (nv === "uf") linhas = (DEP[S.cargo]["2022"] || []).map((c) => [c[0], c[3]]);
    else if (registro) linhas = registro.cands;
    linhas = linhas || [];
    const lista = DEP[S.cargo]["2022"];
    const nomes = Object.fromEntries(lista.map((c) => [c[0], c]));
    const soCand = linhas.filter(([nr]) => !nr.startsWith("L"));
    const tot = soCand.reduce((a, c) => a + c[1], 0);
    box.innerHTML = `<h3 style="margin:0 0 6px;font-size:15px">Candidatos a ${S.cargo === "df" ? "deputado federal" : "deputado estadual"} · 2022</h3>${nota}
      <input type="search" placeholder="buscar candidato ou partido" aria-label="buscar candidato">
      <div class="rolagem"><table><thead><tr><th>#</th><th>candidato</th><th>partido</th><th>votos</th><th>% nominais</th></tr></thead><tbody></tbody></table></div>
      <p class="nota" style="font-size:12px;color:var(--muda)">2026: ${DEP[S.cargo]["2026"].length} candidaturas registradas no estado.</p>`;
    const tb = box.querySelector("tbody");
    const pinta = (q) => {
      q = (q || "").toLowerCase();
      tb.innerHTML = soCand.filter(([nr]) => !q || (nomes[nr] && (nomes[nr][1] + " " + nomes[nr][2] + " " + nr).toLowerCase().includes(q))).slice(0, 400)
        .map(([nr, v], k) => `<tr><td>${k + 1}</td><td><i style="display:inline-block;width:9px;height:9px;border-radius:50%;background:${corPartido(nr, "2022")};margin-right:6px"></i>${nomes[nr] ? nomes[nr][1] : nr} <span style="color:var(--muda)">${nr}</span></td><td>${nomes[nr] ? nomes[nr][2] : ""}</td><td>${fmt.format(v)}</td><td>${pct(100 * v / tot)}</td></tr>`).join("");
    };
    pinta("");
    box.querySelector("input").addEventListener("input", (e) => pinta(e.target.value));
    // vetor por partido para as bolhas: nominais + legenda + brancos/nulos + abstencao
    if (!linhas.length) return null;
    const porP = {};
    for (const [nr, v] of linhas) {
      const pp = nr.startsWith("L") ? nr.slice(1) : nr.slice(0, 2);
      porP[pp] = (porP[pp] || 0) + v;
    }
    if (registro && !usouDepsec) for (const [pp, v] of Object.entries(registro.leg)) porP[pp] = (porP[pp] || 0) + v;
    const partidos = Object.entries(porP).sort((a, b) => b[1] - a[1]);
    const pseudo = partidos.map(([pp]) => [pp, (META.partidos["2022"][pp] || {}).sigla || pp, (META.partidos["2022"][pp] || {}).sigla || pp]);
    let abst = registro ? registro.abst : (u && u.pr22t1 ? u.pr22t1[u.pr22t1.length - 1] : 0);
    let bn = registro ? registro.bn : 0;
    if (usouDepsec) {
      // na urna, o comparecimento e o mesmo em todo cargo: brancos+nulos de deputado
      // = comparecimento (do presidente) - validos de deputado desta unidade
      const comp = votos22(u);
      const val = linhas.reduce((a, c) => a + c[1], 0);
      bn = comp != null ? Math.max(comp - val, 0) : 0;
      abst = u && u.pr22t1 ? u.pr22t1[u.pr22t1.length - 1] : 0;
    }
    const vet = partidos.map((x) => x[1]).concat([bn, 0, abst]);
    return { vet, cands: pseudo };
  }

  // ------------------------------------------------------------ render
  function migalhas() {
    const itens = [["Brasil", { uf: null, mun: null, zona: null, local: null, secao: null }]];
    if (S.uf) itens.push([NOME_UF[S.uf] || S.uf, { mun: null, zona: null, local: null, secao: null }]);
    if (S.mun) itens.push([(UFD && UFD.mun[S.mun] && UFD.mun[S.mun].nome) || S.mun, { zona: null, local: null, secao: null }]);
    if (S.zona) itens.push([`Zona ${S.zona}`, { local: null, secao: null }]);
    if (S.local) { const l = MUND && MUND.locais.find((x) => String(x.l) === String(S.local) && String(x.z) === String(S.zona)); itens.push([l && l.nome ? l.nome : `Local ${S.local}`, { secao: null }]); }
    if (S.secao) itens.push([`Seção ${S.secao}`, {}]);
    const el = $("#migalhas");
    el.innerHTML = itens.map((it, k) => (k ? '<span class="sep">›</span>' : "") + `<button data-k="${k}" ${k === itens.length - 1 ? 'aria-current="page"' : ""}>${it[0]}</button>`).join("");
    el.querySelectorAll("button").forEach((b) => b.addEventListener("click", () => { const k = +b.dataset.k; if (k < itens.length - 1) vai(itens[k][1]); }));
    return itens[itens.length - 1][0];
  }

  function controles() {
    const lt = $("#abas-lente");
    if (lt) {
      const c = META.campos_2026;
      lt.innerHTML = [["esq", c.esq], ["dir", c.dir]].map(([k, cc]) =>
        `<button role="tab" data-k="${k}" aria-selected="${S.lente === k}" ${S.cargo !== "pr" ? "disabled" : ""}>` +
        `<i style="display:inline-block;width:9px;height:9px;border-radius:50%;background:${corPartido(cc[0], "2026")};margin-right:6px"></i>${cc[1]} × 50%+1</button>`).join("");
      lt.querySelectorAll("button").forEach((b) => b.addEventListener("click", () =>
        vai({ lente: b.dataset.k, metrica: S.metrica === "dalvo" || S.metrica === "alvo" ? S.metrica : null })));
    }
    const ac = $("#abas-cargo");
    ac.innerHTML = CARGOS.map(([k, n]) => `<button role="tab" data-k="${k}" aria-selected="${S.cargo === k}">${n}</button>`).join("");
    ac.querySelectorAll("button").forEach((b) => b.addEventListener("click", () => vai({ cargo: b.dataset.k, turno: b.dataset.k === "df" || b.dataset.k === "de" || b.dataset.k === "sen" ? 1 : S.turno, metrica: null })));
    const at = $("#abas-turno");
    const t2ok = S.cargo === "pr" || (S.cargo === "gov" && (!S.uf || (UFD && UFD.cands.gov["2022"].t2.length)));
    at.innerHTML = [1, 2].map((t) => `<button role="tab" data-t="${t}" aria-selected="${S.turno === t}" ${t === 2 && !t2ok ? "disabled" : ""}>${t}º turno</button>`).join("");
    at.querySelectorAll("button").forEach((b) => b.addEventListener("click", () => vai({ turno: +b.dataset.t })));
    $("#eixo").checked = S.eixo;
    const ms = metricas();
    if (!ms.some((m) => m[0] === S.metrica)) S.metrica = ms[0][0];
    $("#metrica").innerHTML = ms.map(([k, n]) => `<option value="${k}" ${k === S.metrica ? "selected" : ""}>${n}</option>`).join("");
  }

  async function carrega() {
    UFD = S.uf ? await Dados.json(`uf/${S.uf}.json`) : null;
    MUND = S.mun ? await Dados.json(`mun/${S.mun}.json`) : null;
    SECD = S.mun && S.zona ? await Dados.json(`sec/${S.mun}/${S.zona}.json`) : null;
    if (S.uf && LIVE && !LIVE_UF[S.uf]) LIVE_UF[S.uf] = await Dados.live(`uf/${S.uf}.json`);
    LIVE_MUN = S.mun && LIVE ? await Dados.live(`mun/${S.mun}.json`) : null;
    if (S.turno === 2 && S.cargo === "gov" && UFD && !UFD.cands.gov["2022"].t2.length) S.turno = 1;
  }

  let gen = 0;
  async function render() {
    const minha = ++gen;
    document.body.classList.add("carregando");
    try {
      await carrega();
    } finally {
      if (minha === gen) document.body.classList.remove("carregando");
    }
    if (minha !== gen) return;
    controles();
    const nome = migalhas();
    const u = unidade();
    const nv = nivel();
    $("#titulo-unidade").textContent = nome;
    const sub = [];
    if (u && u.aptos26) sub.push(`${fmt.format(u.aptos26)} aptos em 2026`);
    const v22u = votos22(u);
    if (v22u != null) sub.push(`${fmt.format(v22u)} votos em 2022 (1º turno)`);
    if (u && u.ns) sub.push(`${fmt.format(u.ns)} urnas`);
    if (nv === "secao" && u) sub.push(`âncora: ${u.nivel_ancora === "secao" ? "a própria seção em 2022" : "média do " + u.nivel_ancora}`);
    if (nv === "local" && u && u.so22) sub.push("local que existia em 2022 e não recebe urnas em 2026");
    $("#sub-unidade").textContent = sub.join(" · ");

    let c22 = null, nota22 = "";
    const dep = S.cargo === "df" || S.cargo === "de";
    if (dep) {
      const d = await painelDeputados(u);
      if (d) { c22 = categorias(d.vet, d.cands, "2022", true); nota22 = "por partido (nominal + legenda)"; }
      else nota22 = nv === "br" ? "escolha um estado" : "sem detalhe neste nível";
    } else {
      $("#deputados").hidden = true;
      const k = chave22();
      const cands = listaCands(S.cargo, S.turno);
      if ((S.cargo === "gov" || S.cargo === "sen") && nv === "br") nota22 = "escolha um estado";
      else if (u && u[k]) c22 = categorias(u[k], cands, "2022");
      else nota22 = S.turno === 2 && S.cargo === "gov" ? "sem 2º turno neste estado" : "sem dados de 2022 aqui (seção nova?)";
    }
    let c26 = null, nota26 = "";
    const lv = liveDaUnidade();
    const bu = registroBU();
    const cbu = catsBU(bu, S.cargo);
    const cest = catsEstadualLive(u);
    if (cbu) {
      c26 = cbu;
      nota26 = `apurado · ${fmt.format(LIVE_MUN.n_bu)} boletins raspados no município (${LIVE_MUN.instante.slice(0, 5)})`;
    } else if (cest) {
      c26 = cest;
      const r = LIVE[S.cargo][S.uf];
      nota26 = `ao vivo · projeção com ${pct(r.pct_secoes, 0)} apurado (brancos/nulos/abstenção da âncora)`;
    } else if (S.cargo === "pr") {
      c26 = cats26(u);
      nota26 = lv && lv.proj ? `ao vivo · projeção com ${pct(lv.pct, 0)} apurado`
        : (LIVE && LIVE.modo === "aguardando" ? "aguardando apuração · 0 urnas — projeção demográfica como referência"
           : "projeção demográfica (âncora)");
      if (!c26) nota26 = "sem projeção aqui";
    } else {
      const lista = dep ? (DEP && DEP[S.cargo]["2026"]) : (UFD && UFD.cands[S.cargo] && UFD.cands[S.cargo]["2026"]);
      nota26 = lista && lista.length ? `${lista.length} candidaturas em 2026: ${lista.slice(0, 6).map((c) => c[1]).join(", ")}${lista.length > 6 ? "…" : ""}. Resultado aparece com a apuração.` : "resultado aparece com a apuração";
    }
    const tot22 = c22 ? c22.reduce((a, c) => a + c.n, 0) : 0, tot26 = c26 ? c26.reduce((a, c) => a + c.n, 0) : 0;
    const esc = Bolhas.escala([tot22, tot26], window.innerWidth < 600 ? 6000 : 20000);
    const t = S.turno;
    painel($("#p22"), `2022 · ${t}º turno`, c22 ? nota22 || "resultado oficial" : nota22, c22, esc);
    painel($("#p26"), `2026 · ${t}º turno`, nota26, c26, esc);
    tabela(c22, c26);
    caixaAlvo(u);
    await desenhaMapa();
    listaFilhos();
  }

  // ------------------------------------------------------------ ao vivo
  async function atualizaLive() {
    const novo = await Dados.live("br.json");
    const pill = $("#status-live");
    if (!novo) { LIVE = null; pill.hidden = true; return false; }
    const mudou = !LIVE || novo.gerado_em !== LIVE.gerado_em;
    LIVE = novo;
    pill.hidden = false;
    pill.className = "live-pill" + (novo.modo === "ao-vivo" ? "" : " replay");
    pill.textContent = novo.modo === "aguardando"
      ? "aguardando apuração · 04/10 às 17h"
      : (novo.modo === "ao-vivo" ? "ao vivo" : "replay 2022 (teste)") + ` · ${novo.instante.slice(0, 5)} · ${pct(novo.pct_secoes, 0)} apurado`;
    if (mudou && S.uf) LIVE_UF[S.uf] = await Dados.live(`uf/${S.uf}.json`);
    return mudou;
  }

  // ------------------------------------------------------------ inicio
  async function inicia() {
    leHash();
    [META, BR] = await Promise.all([Dados.json("meta.json"), Dados.json("br.json")]);
    if (!META || !BR) { $("#titulo-unidade").textContent = "Base do mapa ainda não gerada (web/gera_estatico.py)."; return; }
    await atualizaLive();
    $("#eixo").addEventListener("change", (e) => vai({ eixo: e.target.checked }));
    $("#metrica").addEventListener("change", (e) => vai({ metrica: e.target.value }));
    window.addEventListener("hashchange", () => { leHash(); render(); });
    let rz; window.addEventListener("resize", () => { clearTimeout(rz); rz = setTimeout(render, 200); });
    await render();
    setInterval(async () => { if (await atualizaLive()) render(); }, 60000);
  }
  inicia();
})();
