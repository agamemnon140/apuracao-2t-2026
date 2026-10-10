"""Gera a base estatica do mapa (docs/dados/): 2022 real x 2026 projetado, do Brasil a secao.

Hierarquia: BR -> UF -> municipio -> zona -> local de votacao -> secao (urna).
Cada unidade leva, por cargo e turno, um VETOR de votos alinhado a lista de candidatos do
escopo, mais [branco, nulo, abstencao]. O navegador baixa so o nivel que clicar.

  meta.json                   candidatos de presidente, cores, eixos, colunas
  br.json                     por UF: presidente 2022 (t1, t2), projecao 2026, alvo
  uf/{UF}.json                candidatos de governador/senador; por municipio: todos os cargos
  mun/{cd}.json               zonas e locais de votacao (com lat/lon) do municipio
  sec/{cd}/{zona}.json        urnas da zona (colunas + linhas)
  dep/{UF}.json               candidatos a deputado (2022 com votos, 2026 lista)
  dep/{UF}/{cd}.json          deputados no municipio: todos os candidatos com voto, por zona

Projecao 2026 (so presidente): a ANCORA por urna (sintetico/ancora_2026.py) vira votos
esperados [Lula, direita, outros, brancos+nulos, abstencao]; o ALVO (sintetico/alvo_2026.py)
e a fatia dos validos que cada campo precisa ali para fazer 50%+1 no pais.

Uso:  .venv/Scripts/python -m web.gera_estatico [--so UF,UF] [--sem-dep]
"""
from __future__ import annotations

import json
import shutil
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

from pipeline.needle_hier import sig
from sintetico.caminhos import BASELINE, SAIDA
from sintetico.universo_2026 import le_universo

RAIZ = Path(__file__).resolve().parents[1]
DOCS = RAIZ / "docs" / "dados"
EXTRA = ["branco", "nulo", "abst"]
SEC = ["uf", "cd_mun", "zona", "secao"]
# perfil do eleitorado (sintetico/perfil_secao_2026.parquet), fracoes 0-1 por secao
PF_PCTS = ["pct_fem", "pct_1624", "pct_2539", "pct_4059", "pct_60m",
           "pct_fund", "pct_medio", "pct_sup"]
# (chave, arquivo, turno, escopo por UF, ano, cargo no detalhe, votos por eleitor); chave = {cargo}{aa}t{turno}.
# Arquivo ausente (ex.: 2o turno de 2026 antes de 25/10) e simplesmente pulado.
TABELAS = [("pr22t1", "presidente_secao_2022_t1.parquet", 1, False, 2022, "PRESIDENTE", 1),
           ("pr22t2", "presidente_secao_2022_t2.parquet", 2, False, 2022, "PRESIDENTE", 1),
           ("gov22t1", "governador_secao_2022_t1.parquet", 1, True, 2022, "PRESIDENTE", 1),
           ("gov22t2", "governador_secao_2022_t2.parquet", 2, True, 2022, "PRESIDENTE", 1),
           ("sen22t1", "senador_secao_2022_t1.parquet", 1, True, 2022, "PRESIDENTE", 1),
           ("pr26t1", "presidente_secao_2026_t1.parquet", 1, False, 2026, "PRESIDENTE", 1),
           ("pr26t2", "presidente_secao_2026_t2.parquet", 2, False, 2026, "PRESIDENTE", 1),
           ("gov26t1", "governador_secao_2026_t1.parquet", 1, True, 2026, "GOVERNADOR", 1),
           ("gov26t2", "governador_secao_2026_t2.parquet", 2, True, 2026, "GOVERNADOR", 1),
           ("sen26t1", "senador_secao_2026_t1.parquet", 1, True, 2026, "SENADOR", 2)]


def ano_de(chave: str) -> str:
    return "20" + chave.split("t")[0][-2:]


def escopo_de(chave: str, uf: str) -> str:
    return "BR" if chave.startswith("pr") else uf


def grava(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")), "utf-8")


def i(v) -> int:
    return int(round(float(v))) if v == v else 0


# ------------------------------------------------------------------ votos por urna
def comparecimento(turno: int, ano: int = 2022, cargo: str | tuple = "PRESIDENTE") -> pd.DataFrame:
    """Aptos/comparecimento/abstencao por urna. 2022: carimbos do presidente (valem para
    todo cargo). 2026: detalhe_votacao_secao do proprio cargo (estadual tem aptos_est)."""
    if ano == 2022:
        c = pd.read_parquet(BASELINE / f"carimbos_presidente_2022_t{turno}.parquet",
                            columns=["uf", "cd_municipio", "zona", "secao", "aptos", "comparecimento"])
    else:
        cargos = [cargo] if isinstance(cargo, str) else list(cargo)
        c = pd.read_parquet(BASELINE / f"detalhe_secao_{ano}.parquet",
                            columns=["uf", "cd_municipio", "zona", "secao", "cargo", "turno", "aptos",
                                     "comparecimento"],
                            filters=[("cargo", "in", cargos), ("turno", "==", str(turno))])
        c = c.groupby(["uf", "cd_municipio", "zona", "secao"], as_index=False)[["aptos", "comparecimento"]].sum()
    c["cd_mun"] = c["cd_municipio"].astype(int)
    c["abst"] = (c["aptos"] - c["comparecimento"]).clip(lower=0)
    return c[SEC + ["aptos", "comparecimento", "abst"]]


def largo(arq: str, turno: int, escopo_uf: bool, ano: int = 2022, cargo: str = "PRESIDENTE",
          votos_por_eleitor: int = 1) -> tuple[pd.DataFrame, dict]:
    """Votos longos -> matriz urna x candidato (+branco, nulo, abst).
    Devolve (tabela larga indexada por SEC, {escopo: [nr, ...] em ordem de votos}).
    Senado de 2 vagas: cada eleitor da 2 votos, entao a abstencao entra em votos (x2) para
    as fatias do vetor continuarem comparaveis."""
    p = BASELINE / arq
    if not p.exists():
        return None, {}
    d = le_longo(p, ["uf", "cd_municipio", "zona", "secao", "nr_votavel", "votos"])
    d["col"] = d["nr_votavel"].cat.rename_categories(
        {k: v for k, v in {"95": "branco", "96": "nulo"}.items() if k in d["nr_votavel"].cat.categories})
    ab = comparecimento(turno, ano, cargo).set_index(SEC)["abst"] * votos_por_eleitor
    # pivot por UF, so com os candidatos da UF: o pivot nacional de governador/senador tem uma
    # coluna por candidato do pais (~300 x 470 mil urnas) e nao cabe na RAM da maquina da noite
    tabs, ordem = {}, {}
    for uf, g in d.groupby("uf", observed=True):
        t = g.pivot_table(index=["cd_mun", "zona", "secao"], columns="col", values="votos",
                          aggfunc="sum", fill_value=0, observed=True)
        t.columns = t.columns.astype(str)
        t = pd.concat({str(uf): t}, names=["uf"])
        t["abst"] = ab.reindex(t.index).fillna(0).astype(int)
        for c in ["branco", "nulo"]:
            if c not in t:
                t[c] = 0
        cands = [c for c in t.columns if c not in EXTRA]
        tabs[str(uf)] = t[cands + EXTRA].astype(np.int64)
        if escopo_uf:
            ordem[str(uf)] = list(t[cands].sum().sort_values(ascending=False).index)
    del d
    if escopo_uf:
        return tabs, ordem
    tab = pd.concat(tabs.values()).fillna(0)
    cands = [c for c in tab.columns if c not in EXTRA]
    ordem["BR"] = list(tab[cands].sum().sort_values(ascending=False).index)
    return tab[cands + EXTRA].astype(np.int64), ordem


def le_longo(p: Path, cols: list[str], filters=None) -> pd.DataFrame:
    """Parquet longo com texto como categoria (milhoes de linhas: objeto str custaria GBs);
    cd_municipio vira cd_mun inteiro."""
    import pyarrow.parquet as pq
    d = pq.read_table(p, columns=cols, filters=filters).to_pandas(strings_to_categorical=True)
    if "cd_municipio" in d:
        cm = d.pop("cd_municipio")
        d["cd_mun"] = cm.cat.categories.astype(int).to_numpy()[cm.cat.codes.to_numpy()]
    return d


def le_texto(p: Path, cols: list[str], filters=None) -> pd.DataFrame:
    """le_longo com as categorias de volta a str -- cada linha aponta para o MESMO objeto da
    categoria (8 bytes/linha), sem a armadilha do groupby categorico (produto cartesiano)."""
    d = le_longo(p, cols, filters)
    for c in d.select_dtypes("category").columns:
        d[c] = np.asarray(d[c].cat.categories, dtype=object)[d[c].cat.codes.to_numpy()]
    return d


def prefixo(s: pd.Series) -> pd.Series:
    """2 primeiros digitos (partido) sem criar uma string nova por linha."""
    return s.map({n: n[:2] for n in s.unique()})


def nomes_2022(arq: str) -> dict:
    d = le_longo(BASELINE / arq, ["uf", "nr_votavel", "nm_votavel"])
    d = d.groupby(["uf", "nr_votavel"], observed=True)["nm_votavel"].first().reset_index()
    return {(str(r.uf), str(r.nr_votavel)): str(r.nm_votavel).title() for r in d.itertuples()}


# ------------------------------------------------------------------ montagem
class Base:
    def __init__(self):
        t0 = time.time()
        self.partidos = json.loads((RAIZ / "config" / "partidos.json").read_text("utf-8"))
        self.cand26 = json.loads((RAIZ / "config" / "candidatos_2026.json").read_text("utf-8"))
        self.mun = pd.read_parquet(SAIDA / "municipios_2026.parquet")
        self.nome_mun = dict(zip(self.mun["cd_mun"], self.mun["nm_municipio"].str.title()))

        # 2026: urnas (ancora) + alvo + locais
        anc = pd.read_parquet(SAIDA / "ancora_2026.parquet",
                              columns=SEC + ["nr_local", "aptos", "n_agregadas", "a_ed", "a_part", "a_out",
                                             "a_bn", "nivel_ancora"])
        alvo = pd.read_parquet(SAIDA / "alvo_2026_t1.parquet", columns=SEC + ["v_esp", "alvo_esq", "alvo_dir",
                                                                             "ancora_esq"])
        u = anc.merge(alvo, on=SEC, how="left")
        val = u["aptos"] * sig(u["a_part"])
        out = val * sig(u["a_out"])
        dois = val - out
        esq = dois * sig(u["a_ed"])
        bn = val * np.exp(u["a_bn"])
        u["p_esq"], u["p_dir"], u["p_out"] = esq, dois - esq, out
        u["p_bn"], u["p_abst"] = bn, (u["aptos"] - val - bn).clip(lower=0)
        u["w_alvo"] = u["v_esp"]
        u["t_esq"], u["t_dir"], u["t_anc"] = (u["alvo_esq"] * u["v_esp"], u["alvo_dir"] * u["v_esp"],
                                              u["ancora_esq"] * u["v_esp"])
        perf = SAIDA / "perfil_secao_2026.parquet"
        if perf.exists():
            pf = (pd.read_parquet(perf)
                  .rename(columns={"cd_municipio_tse": "cd_mun", "eleitores": "pf_n"}))
            u = u.merge(pf[SEC + ["pf_n"] + PF_PCTS], on=SEC, how="left")
            print(f"  perfil: {u['pf_n'].notna().sum():,} de {len(u):,} urnas com perfil TSE", flush=True)
        else:
            u["pf_n"] = np.nan
            for c in PF_PCTS:
                u[c] = np.nan
        self.u26 = u
        self.loc26 = pd.read_parquet(SAIDA / "locais_2026.parquet")
        loc22 = le_universo(2022)
        self.loc22 = (loc22.groupby(["uf", "cd_mun", "zona", "nr_local"], as_index=False)
                      .agg(nm_local=("nm_local", "first"), bairro=("bairro", "first"),
                           lat=("lat", "first"), lon=("lon", "first")))
        print(f"  2026: {len(u):,} urnas  [{time.time() - t0:.0f}s]", flush=True)

        # votos por urna: 2022 (com local de votacao de 2022) e 2026 apurado (dados abertos)
        self.tab, self.ordem = {}, {}
        self.nomes = {}
        for chave, arq, turno, por_uf, ano, cargo, vpe in TABELAS:
            t, o = largo(arq, turno, por_uf, ano, cargo, vpe)
            if t is not None:
                self.tab[chave], self.ordem[chave] = t, o
                self.nomes[chave] = nomes_2022(arq)
                n = sum(len(x) for x in t.values()) if isinstance(t, dict) else len(t)
                print(f"  {chave}: {n:,} urnas  [{time.time() - t0:.0f}s]", flush=True)
        a22 = pd.read_parquet(SAIDA / "alvo_2022_t2.parquet", columns=["uf", "cd_municipio", "zona", "secao",
                                                                      "nr_local", "aptos"])
        a22["cd_mun"] = a22["cd_municipio"].astype(int)
        self.local22 = a22.set_index(SEC)["nr_local"]
        self.local26 = u.set_index(SEC)["nr_local"]
        self.aptos22 = comparecimento(1).set_index(SEC)["aptos"]
        self.aptos22_t2 = comparecimento(2).set_index(SEC)["aptos"]
        print(f"  pronto  [{time.time() - t0:.0f}s]", flush=True)

    # ---- agregacao generica: soma por chave de nivel
    def local_de(self, chave: str) -> pd.Series:
        """Urna -> local de votacao do ANO da chave (2026 usa o local da urna em 2026)."""
        return self.local26 if ano_de(chave) == "2026" else self.local22

    def tabela(self, chave: str, uf: str) -> pd.DataFrame | None:
        """Matriz urna x candidato da UF (cargos estaduais ja vem separados por UF)."""
        t = self.tab[chave]
        if isinstance(t, dict):
            return t.get(uf)
        t = t[t.index.get_level_values(0) == uf]
        return t if len(t) else None

    def soma22(self, chave: str, niveis: list[str], uf: str | None = None) -> pd.DataFrame | None:
        t = self.tab[chave] if uf is None else self.tabela(chave, uf)
        if t is None:
            return None
        t = t.reset_index()
        if "nr_local" in niveis:
            t["nr_local"] = self.local_de(chave).reindex(pd.MultiIndex.from_frame(t[SEC])).fillna(-1).astype(int).to_numpy()
        return t.groupby(niveis).sum(numeric_only=True).drop(columns=[c for c in ["zona", "secao", "cd_mun"]
                                                                      if c not in niveis], errors="ignore")

    def cands(self, chave: str, escopo: str) -> list:
        """[[nr, nome, partido], ...] na ordem de votos do escopo."""
        if chave not in self.ordem:
            return []
        ordem = self.ordem[chave].get(escopo, [])
        nomes = self.nomes.get(chave, {})
        por_nr = {n_: v for (u_, n_), v in nomes.items()}
        out = []
        for nr in ordem:
            nome = nomes.get((escopo, nr)) or por_nr.get(nr, nr)
            sig_p = self.partidos["partidos"][ano_de(chave)].get(nr[:2], {}).get("sigla", "")
            out.append([nr, nome, sig_p])
        return out

    def vetor(self, linha: pd.Series | None, chave: str, escopo: str) -> list | None:
        if linha is None:
            return None
        cols = self.ordem[chave].get(escopo, []) + EXTRA
        return [i(linha.get(c, 0)) for c in cols]


def proj(g: pd.DataFrame) -> dict:
    w = g["w_alvo"].sum()
    return {"aptos26": i(g["aptos"].sum()),
            "proj26": [i(g[c].sum()) for c in ["p_esq", "p_dir", "p_out", "p_bn", "p_abst"]],
            "alvo26": [round(100 * g["t_esq"].sum() / w, 2), round(100 * g["t_dir"].sum() / w, 2)] if w else None,
            "anc26": round(100 * g["t_anc"].sum() / w, 2) if w else None}


def cands26(base: Base, cargo: str, uf: str | None) -> list:
    if cargo == "presidente":
        p = base.cand26["presidente"]
        c = p["cands"]
        ordem = [p["esq"], p["dir"]] + sorted(k for k in c if k not in (p["esq"], p["dir"]))
    else:
        c = base.cand26[cargo].get(uf, {})
        ordem = sorted(c)
    return [[nr, c[nr]["nome"].title(), c[nr]["partido"]] for nr in ordem]


# ------------------------------------------------------------------ escritores
def escreve_meta(base: Base) -> None:
    p26 = base.cand26["presidente"]
    grava(DOCS / "meta.json", {
        "gerado_em": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "extra": EXTRA, "proj_cols": ["esq", "dir", "outros", "bn", "abst"],
        "pr": {"2022": {"t1": base.cands("pr22t1", "BR"), "t2": base.cands("pr22t2", "BR")},
               "2026": {"t1": cands26(base, "presidente", None)},
               # 2026 apurado: lista alinhada aos vetores pr26t{1,2} (ordem de votos no pais)
               "r26": {"t1": base.cands("pr26t1", "BR"), "t2": base.cands("pr26t2", "BR")}},
        "campos_2026": {"esq": [p26["esq"], p26["cands"][p26["esq"]]["nome"].title()],
                        "dir": [p26["dir"], p26["cands"][p26["dir"]]["nome"].title()]},
        "cores": base.partidos["cores_fixas"], "cores_eixo": base.partidos["cores_eixo"],
        "partidos": base.partidos["partidos"],
        "live_base_default": "dados/live",
    })


def escreve_br(base: Base) -> None:
    ks = [k for k in base.tab if k.startswith("pr")]
    ag = {k: base.soma22(k, ["uf"]) for k in ks}
    ufs = {}
    for uf, g in base.u26.groupby("uf"):
        ufs[uf] = {**{k: base.vetor(t.loc[uf] if uf in t.index else None, k, "BR") for k, t in ag.items()},
                   **proj(g)}
    tot = {**{k: base.vetor(t.sum(), k, "BR") for k, t in ag.items()}, **proj(base.u26)}
    grava(DOCS / "br.json", {"br": tot, "ufs": ufs})


def escreve_uf(base: Base, uf: str) -> None:
    u = base.u26[base.u26["uf"] == uf]
    niv = ["uf", "cd_mun"]
    ag = {k: t for k in base.tab if (t := base.soma22(k, niv, uf)) is not None}
    esc = {k: escopo_de(k, uf) for k in base.tab}
    cands = {"gov": {"2022": {"t1": base.cands("gov22t1", uf) if "gov22t1" in base.tab else [],
                              "t2": base.cands("gov22t2", uf) if uf in base.ordem.get("gov22t2", {}) else []},
                     "2026": cands26(base, "governador", uf),
                     "r26": {"t1": base.cands("gov26t1", uf),
                             "t2": base.cands("gov26t2", uf) if uf in base.ordem.get("gov26t2", {}) else []}},
             "sen": {"2022": {"t1": base.cands("sen22t1", uf) if "sen22t1" in base.tab else []},
                     "2026": cands26(base, "senador", uf),
                     "r26": {"t1": base.cands("sen26t1", uf)}}}
    muns = {}
    for cd, g in u.groupby("cd_mun"):
        r = {"nome": base.nome_mun.get(cd, str(cd)), "nz": int(g["zona"].nunique()), "ns": len(g), **proj(g)}
        for k, t in ag.items():
            if uf in base.ordem[k] or esc[k] == "BR":
                ln = t.loc[(uf, cd)] if (uf, cd) in t.index else None
                v = base.vetor(ln, k, esc[k])
                if v is not None:
                    r[k] = v
        muns[str(cd)] = r
    tot = {}
    for k, t in ag.items():
        if uf in base.ordem[k] or esc[k] == "BR":
            s = t.loc[uf].sum() if uf in t.index.get_level_values(0) else None
            v = base.vetor(s, k, esc[k])
            if v is not None:
                tot[k] = v
    tot.update(proj(u))
    grava(DOCS / "uf" / f"{uf}.json", {"uf": uf, "cands": cands, "tot": tot, "mun": muns})


def _dic(t: pd.DataFrame, cols: list[str]) -> dict:
    """tabela indexada -> {chave: vetor} (colunas do escopo; ausentes = 0)."""
    m = t.reindex(columns=cols, fill_value=0).to_numpy(dtype=np.int64)
    return dict(zip(t.index, m.tolist()))


def _proj_dic(u: pd.DataFrame, niv: list[str]) -> dict:
    g = u.groupby(niv)[["aptos", "p_esq", "p_dir", "p_out", "p_bn", "p_abst", "w_alvo", "t_esq", "t_dir",
                        "t_anc"]].sum()
    out = {}
    for k, r in zip(g.index, g.to_numpy()):
        apt, pe, pd_, po, pb, pa, w, te, td, ta = r
        out[k] = {"aptos26": i(apt), "proj26": [i(pe), i(pd_), i(po), i(pb), i(pa)],
                  "alvo26": [round(100 * te / w, 2), round(100 * td / w, 2)] if w else None,
                  "anc26": round(100 * ta / w, 2) if w else None}
    return out


def _perfil_dic(u: pd.DataFrame, niv: list[str]) -> dict:
    """Perfil medio da abrangencia ponderado pelos eleitores com perfil (eixo a eixo,
    ignorando secoes sem o eixo): {chave: [% fem, 16-24, 25-39, 40-59, 60+, fund, medio, sup]}."""
    d = u[u["pf_n"].fillna(0) > 0]
    if d.empty:
        return {}
    acc = {}
    for c in PF_PCTS:
        ok = d[d[c].notna()]
        soma = (ok[c] * ok["pf_n"]).groupby([ok[cc] for cc in niv]).sum()
        n = ok.groupby(niv)["pf_n"].sum()
        acc[c] = (100 * soma / n).round(1)
    tab = pd.DataFrame(acc)
    return {k: [None if x != x else x for x in row]
            for k, row in zip(tab.index, tab.to_numpy().tolist())}


def _perfil_sec(row) -> list | None:
    n = getattr(row, "pf_n", np.nan)
    if n != n or not n:
        return None
    return [None if x != x else round(100 * float(x), 1)
            for x in (getattr(row, c) for c in PF_PCTS)]


def escreve_municipios(base: Base, uf: str) -> None:
    u = base.u26[base.u26["uf"] == uf]
    esc = {k: escopo_de(k, uf) for k in base.tab}
    chaves = [k for k in base.tab if (esc[k] == "BR" or uf in base.ordem[k]) and base.tabela(k, uf) is not None]
    cols = {k: base.ordem[k][esc[k]] + EXTRA for k in chaves}
    zon, loc, sec = {}, {}, {}
    for k in chaves:
        t = base.tabela(k, uf)
        sec[k] = _dic(t, cols[k])
        tl = t.reset_index()
        tl["nr_local"] = base.local_de(k).reindex(pd.MultiIndex.from_frame(tl[SEC])).fillna(-1).astype(int).to_numpy()
        zon[k] = _dic(tl.groupby(["cd_mun", "zona"]).sum(numeric_only=True), cols[k])
        loc[k] = _dic(tl[tl["nr_local"] >= 0].groupby(["cd_mun", "zona", "nr_local"]).sum(numeric_only=True), cols[k])
    pz = _proj_dic(u, ["cd_mun", "zona"])
    pl = _proj_dic(u, ["cd_mun", "zona", "nr_local"])
    pfz = _perfil_dic(u, ["cd_mun", "zona"])
    pfl = _perfil_dic(u, ["cd_mun", "zona", "nr_local"])
    nsz = u.groupby(["cd_mun", "zona"]).size().to_dict()
    nsl = u.groupby(["cd_mun", "zona", "nr_local"]).size().to_dict()
    info = {}
    for df_ in (base.loc22[base.loc22["uf"] == uf], base.loc26[base.loc26["uf"] == uf]):   # 2026 sobrescreve
        for r in df_.itertuples(index=False):
            info[(r.cd_mun, r.zona, r.nr_local)] = (
                str(r.nm_local).title(), str(r.bairro).title(),
                None if pd.isna(r.lat) else round(float(r.lat), 5), None if pd.isna(r.lon) else round(float(r.lon), 5))
    locs22 = {}
    for k in chaves:
        for (cd, z, l_) in loc[k]:
            locs22.setdefault(cd, set()).add((z, l_))
    colunas_sec = ["secao", "nr_local", "aptos22", "n_agreg", "nivel_ancora", "aptos26", "proj26", "alvo26",
                   "pf"] + chaves

    for cd, gm in u.groupby("cd_mun"):
        zonas = {}
        for z in sorted(gm["zona"].unique()):
            r = {**pz[(cd, z)], "ns": int(nsz[(cd, z)])}
            if (cd, z) in pfz:
                r["pf"] = pfz[(cd, z)]
            for k in chaves:
                v = zon[k].get((cd, z))
                if v is not None:
                    r[k] = v
            zonas[str(z)] = r
        ks26 = set(zip(gm["zona"].tolist(), gm["nr_local"].tolist()))
        locais = []
        for (z, l_) in sorted(ks26 | locs22.get(cd, set())):
            r = {"z": int(z), "l": int(l_), "so22": (z, l_) not in ks26}
            inf = info.get((cd, z, l_))
            if inf:
                r.update({"nome": inf[0], "bairro": inf[1], "lat": inf[2], "lon": inf[3]})
            if (cd, z, l_) in pl:
                r.update(pl[(cd, z, l_)])
                r["ns"] = int(nsl[(cd, z, l_)])
            if (cd, z, l_) in pfl:
                r["pf"] = pfl[(cd, z, l_)]
            for k in chaves:
                v = loc[k].get((cd, z, l_))
                if v is not None:
                    r[k] = v
            locais.append(r)
        grava(DOCS / "mun" / f"{cd}.json", {"uf": uf, "cd": int(cd), "nome": base.nome_mun.get(cd, ""),
                                            "zonas": zonas, "locais": locais})
        for z, gz in gm.groupby("zona"):
            linhas = []
            for row in gz.itertuples(index=False):
                kk = (uf, cd, z, row.secao)
                w = row.w_alvo
                ln = [int(row.secao), int(row.nr_local), i(base.aptos22.get(kk, np.nan)), int(row.n_agregadas),
                      row.nivel_ancora, int(row.aptos),
                      [i(row.p_esq), i(row.p_dir), i(row.p_out), i(row.p_bn), i(row.p_abst)],
                      [round(100 * row.alvo_esq, 2), round(100 * row.alvo_dir, 2)] if w == w else None,
                      _perfil_sec(row)]
                ln += [sec[k].get(kk) for k in chaves]
                linhas.append(ln)
            grava(DOCS / "sec" / str(cd) / f"{z}.json", {"cols": colunas_sec, "rows": linhas})


# ------------------------------------------------------------------ deputados
DEP_CARGOS = {"df": ("depfederal", "DEPUTADO FEDERAL"),
              "de": ("depestadual", ("DEPUTADO ESTADUAL", "DEPUTADO DISTRITAL"))}


def escreve_deputados(base: Base, uf: str) -> None:
    """dep/{UF}.json: {df: {"2022": [[nr, nome, partido, votos, sit]], "2026": idem (ou a lista
    registrada [[nr, nome, partido]] antes da apuracao)}}; dep/{UF}/{cd}.json: {df, de} = 2022 e
    {df26, de26} = 2026 apurado, cada um {mun, zonas}."""
    out_uf = {}
    por_mun: dict = {}
    for cargo, (pref, cargo_det) in DEP_CARGOS.items():
        out_uf[cargo] = {}
        for ano in (2022, 2026):
            arqc = BASELINE / f"{pref}_candidato_secao_{ano}_t1.parquet"
            if not arqc.exists():
                out_uf[cargo][str(ano)] = [[nr, v["nome"].title(), v["partido"]]
                                           for nr, v in base.cand26[pref].get(uf, {}).items()]
                continue
            ab = comparecimento(1, ano, cargo_det)
            ab = ab[ab["uf"] == uf]
            lista, blocos = _deputados_ano(uf, pref, ano, ab)
            out_uf[cargo][str(ano)] = lista
            chave = cargo if ano == 2022 else cargo + "26"
            for cd, v in blocos.items():
                por_mun.setdefault(cd, {})[chave] = v
    grava(DOCS / "dep" / f"{uf}.json", out_uf)
    for cd, v in por_mun.items():
        grava(DOCS / "dep" / uf / f"{cd}.json", v)


def _deputados_ano(uf: str, pref: str, ano: int, ab: pd.DataFrame) -> tuple[list, dict]:
    ab_m = ab.groupby("cd_mun")[["comparecimento", "abst"]].sum()
    ab_z = ab.groupby(["cd_mun", "zona"])[["comparecimento", "abst"]].sum()
    c = le_texto(BASELINE / f"{pref}_candidato_secao_{ano}_t1.parquet",
                 ["cd_municipio", "zona", "secao", "nr", "votos"], [("uf", "==", uf)])
    p = le_texto(BASELINE / f"{pref}_partido_secao_{ano}_t1.parquet",
                 ["cd_municipio", "zona", "secao", "partido", "votos"], [("uf", "==", uf)])
    n = pd.read_parquet(BASELINE / f"{pref}_candidatos_{ano}.parquet")
    n = n[n["uf"] == uf].drop_duplicates("nr").set_index("nr")
    tot = c.groupby("nr")["votos"].sum().sort_values(ascending=False)
    lista = [[nr, str(n["nome"].get(nr, nr)).title(), str(n["partido"].get(nr, "")), int(v),
              str(n["sit"].get(nr, "")).title()] for nr, v in tot.items()]
    por_mun = {}
    # legenda = nominal+legenda do partido - nominais dos candidatos do partido
    c["partido"] = prefixo(c["nr"])
    for cd, gm in c.groupby("cd_mun"):
        pm = p[p["cd_mun"] == cd]
        leg = (pm.groupby("partido")["votos"].sum()
               - gm.groupby("partido")["votos"].sum()).fillna(pm.groupby("partido")["votos"].sum()).clip(lower=0)
        validos = int(pm["votos"].sum())
        compar = int(ab_m["comparecimento"].get(cd, validos))
        abst = int(ab_m["abst"].get(cd, 0))
        reg = {"cands": [[nr, int(v)] for nr, v in gm.groupby("nr")["votos"].sum().sort_values(ascending=False).items()],
               "leg": {k: int(v) for k, v in leg.items() if v > 0}, "bn": max(compar - validos, 0), "abst": abst}
        zonas = {}
        if gm["zona"].nunique() > 1:
            for z, gz in gm.groupby("zona"):
                pz = pm[pm["zona"] == z]
                lz = (pz.groupby("partido")["votos"].sum() - gz.groupby("partido")["votos"].sum()).clip(lower=0)
                vz = int(pz["votos"].sum())
                cz = ab_z.loc[(cd, z)] if (cd, z) in ab_z.index else None
                zonas[str(z)] = {"cands": [[nr, int(v)] for nr, v in
                                           gz.groupby("nr")["votos"].sum().sort_values(ascending=False).items()],
                                 "leg": {k: int(v) for k, v in lz.dropna().items() if v > 0},
                                 "bn": max((int(cz["comparecimento"]) if cz is not None else vz) - vz, 0),
                                 "abst": int(cz["abst"]) if cz is not None else 0}
        por_mun[cd] = {"mun": reg, "zonas": zonas}
    return lista, por_mun



# ------------------------------------------------------------------ deputados por secao
def escreve_depsec(uf: str) -> None:
    """Detalhe candidato x SECAO de deputado: docs/dados/depsec/{mun}/{zona}_{df|de}.json
    (2022) e {zona}_{df|de}26.json (2026 apurado, chave = urna de 2026).

    ~50 M linhas no pais por ano (~400 MB de JSON): fica FORA do git (.gitignore) e so e
    servido pelo modo local/tunel. Formato: {"sec": {secao: [[nr, votos]...]}}, com os votos
    de legenda do partido como entradas "L<partido>". Gerar: web.gera_estatico --depsec."""
    from collections import defaultdict
    for cargo, (pref, _), ano in [(c, v, a) for a in (2022, 2026) for c, v in DEP_CARGOS.items()]:
        arqc = BASELINE / f"{pref}_candidato_secao_{ano}_t1.parquet"
        if not arqc.exists():
            continue
        c = le_texto(arqc, ["cd_municipio", "zona", "secao", "nr", "votos"], [("uf", "==", uf)])
        if c.empty:
            continue
        pt = le_texto(BASELINE / f"{pref}_partido_secao_{ano}_t1.parquet",
                      ["cd_municipio", "zona", "secao", "partido", "votos"], [("uf", "==", uf)])
        suf = "" if ano == 2022 else "26"
        c["pp"] = prefixo(c["nr"])
        nom = c.groupby(["cd_mun", "zona", "secao", "pp"])["votos"].sum()
        pt = pt.groupby(["cd_mun", "zona", "secao", "partido"])["votos"].sum()
        leg = (pt - nom.reindex(pt.index, fill_value=0)).clip(lower=0)
        leg = leg[leg > 0]
        por_zona: dict = defaultdict(lambda: defaultdict(list))
        for m, z, sec_, nr, v in zip(c["cd_mun"], c["zona"], c["secao"], c["nr"], c["votos"]):
            por_zona[(m, z)][str(sec_)].append([nr, int(v)])
        for (m, z, sec_, pp), v in leg.items():
            por_zona[(m, z)][str(sec_)].append(["L" + pp, int(v)])
        for (m, z), secs in por_zona.items():
            for k in secs:
                secs[k].sort(key=lambda x: -x[1])
            grava(DOCS / "depsec" / str(m) / f"{z}_{cargo}{suf}.json", {"sec": secs})
        del c, pt, nom, leg, por_zona


def main() -> int:
    a = sys.argv[1:]
    so = a[a.index("--so") + 1].split(",") if "--so" in a else None
    t0 = time.time()
    if "--depsec" in a:
        u26 = pd.read_parquet(SAIDA / "municipios_2026.parquet", columns=["uf"])
        for uf in (so or sorted(u26["uf"].unique())):
            if uf == "ZZ":
                continue
            escreve_depsec(uf)
            print(f"  depsec {uf} ok  [{time.time() - t0:.0f}s]", flush=True)
        tam = sum(f.stat().st_size for f in (DOCS / "depsec").rglob("*.json")) / 1e6
        print(f"depsec: {tam:.0f} MB (fora do git; servido so no modo local/tunel)")
        return 0
    base = Base()
    ufs = so or sorted(base.u26["uf"].unique())
    if not so:
        for d in ["uf", "mun", "sec", "dep"]:
            shutil.rmtree(DOCS / d, ignore_errors=True)
    escreve_meta(base)
    escreve_br(base)
    for uf in ufs:
        escreve_uf(base, uf)
        escreve_municipios(base, uf)
        if "--sem-dep" not in a and uf != "ZZ":
            escreve_deputados(base, uf)
        print(f"  {uf} ok  [{time.time() - t0:.0f}s]", flush=True)
    tam = {d: sum(f.stat().st_size for f in (DOCS / d).rglob("*.json")) / 1e6
           for d in ["uf", "mun", "sec", "dep", "geo"] if (DOCS / d).exists()}
    print("tamanho (MB):", {k: round(v, 1) for k, v in tam.items()})
    return 0


if __name__ == "__main__":
    sys.exit(main())
