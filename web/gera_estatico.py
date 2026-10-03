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


def grava(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")), "utf-8")


def i(v) -> int:
    return int(round(float(v))) if v == v else 0


# ------------------------------------------------------------------ 2022: votos por urna
def comparecimento(turno: int) -> pd.DataFrame:
    c = pd.read_parquet(BASELINE / f"carimbos_presidente_2022_t{turno}.parquet",
                        columns=["uf", "cd_municipio", "zona", "secao", "aptos", "comparecimento"])
    c["cd_mun"] = c["cd_municipio"].astype(int)
    c["abst"] = (c["aptos"] - c["comparecimento"]).clip(lower=0)
    return c[SEC + ["aptos", "comparecimento", "abst"]]


def largo(arq: str, turno: int, escopo_uf: bool) -> tuple[pd.DataFrame, dict]:
    """Votos longos -> matriz urna x candidato (+branco, nulo, abst).
    Devolve (tabela larga indexada por SEC, {escopo: [nr, ...] em ordem de votos})."""
    p = BASELINE / arq
    if not p.exists():
        return None, {}
    d = pd.read_parquet(p, columns=["uf", "cd_municipio", "zona", "secao", "nr_votavel", "votos"])
    d["cd_mun"] = d["cd_municipio"].astype(int)
    d["col"] = d["nr_votavel"].replace({"95": "branco", "96": "nulo"})
    tab = d.pivot_table(index=SEC, columns="col", values="votos", aggfunc="sum", fill_value=0)
    ab = comparecimento(turno).set_index(SEC)["abst"]
    tab["abst"] = ab.reindex(tab.index).fillna(0).astype(int)
    for c in ["branco", "nulo"]:
        if c not in tab:
            tab[c] = 0
    cands = [c for c in tab.columns if c not in EXTRA]
    ordem = {}
    if escopo_uf:
        s = d[~d["col"].isin(EXTRA)].groupby(["uf", "col"])["votos"].sum()
        for uf, g in s.groupby(level=0):
            ordem[uf] = list(g.droplevel(0).sort_values(ascending=False).index)
    else:
        s = d[~d["col"].isin(EXTRA)].groupby("col")["votos"].sum().sort_values(ascending=False)
        ordem["BR"] = list(s.index)
    return tab[cands + EXTRA].astype(np.int64), ordem


def nomes_2022(arq: str) -> dict:
    d = pd.read_parquet(BASELINE / arq, columns=["uf", "nr_votavel", "nm_votavel"]).drop_duplicates()
    return {(r.uf, r.nr_votavel): r.nm_votavel.title() for r in d.itertuples()}


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
        self.u26 = u
        self.loc26 = pd.read_parquet(SAIDA / "locais_2026.parquet")
        loc22 = le_universo(2022)
        self.loc22 = (loc22.groupby(["uf", "cd_mun", "zona", "nr_local"], as_index=False)
                      .agg(nm_local=("nm_local", "first"), bairro=("bairro", "first"),
                           lat=("lat", "first"), lon=("lon", "first")))
        print(f"  2026: {len(u):,} urnas  [{time.time() - t0:.0f}s]", flush=True)

        # 2022: votos por urna, com local de votacao de 2022
        self.tab, self.ordem = {}, {}
        for chave, arq, turno, por_uf in [("pr22t1", "presidente_secao_2022_t1.parquet", 1, False),
                                          ("pr22t2", "presidente_secao_2022_t2.parquet", 2, False),
                                          ("gov22t1", "governador_secao_2022_t1.parquet", 1, True),
                                          ("gov22t2", "governador_secao_2022_t2.parquet", 2, True),
                                          ("sen22t1", "senador_secao_2022_t1.parquet", 1, True)]:
            t, o = largo(arq, turno, por_uf)
            if t is not None:
                self.tab[chave], self.ordem[chave] = t, o
                print(f"  {chave}: {len(t):,} urnas, {t.shape[1] - 3} candidatos  [{time.time() - t0:.0f}s]",
                      flush=True)
        self.nomes = {}
        for chave, arq in [("pr22t1", "presidente_secao_2022_t1.parquet"), ("pr22t2", "presidente_secao_2022_t2.parquet"),
                           ("gov22t1", "governador_secao_2022_t1.parquet"), ("gov22t2", "governador_secao_2022_t2.parquet"),
                           ("sen22t1", "senador_secao_2022_t1.parquet")]:
            if (BASELINE / arq).exists():
                self.nomes[chave] = nomes_2022(arq)
        a22 = pd.read_parquet(SAIDA / "alvo_2022_t2.parquet", columns=["uf", "cd_municipio", "zona", "secao",
                                                                      "nr_local", "aptos"])
        a22["cd_mun"] = a22["cd_municipio"].astype(int)
        self.local22 = a22.set_index(SEC)["nr_local"]
        self.aptos22 = comparecimento(1).set_index(SEC)["aptos"]
        self.aptos22_t2 = comparecimento(2).set_index(SEC)["aptos"]
        print(f"  pronto  [{time.time() - t0:.0f}s]", flush=True)

    # ---- agregacao generica: soma por chave de nivel
    def soma22(self, chave: str, niveis: list[str], cols_uf: str | None = None) -> pd.DataFrame:
        t = self.tab[chave].reset_index()
        if "nr_local" in niveis:
            t["nr_local"] = self.local22.reindex(pd.MultiIndex.from_frame(t[SEC])).fillna(-1).astype(int).to_numpy()
        return t.groupby(niveis).sum(numeric_only=True).drop(columns=[c for c in ["zona", "secao", "cd_mun"]
                                                                      if c not in niveis], errors="ignore")

    def cands(self, chave: str, escopo: str) -> list:
        """[[nr, nome, partido], ...] na ordem de votos do escopo."""
        ordem = self.ordem[chave].get(escopo, [])
        nomes = self.nomes.get(chave, {})
        por_nr = {n_: v for (u_, n_), v in nomes.items()}
        out = []
        for nr in ordem:
            nome = nomes.get((escopo, nr)) or por_nr.get(nr, nr)
            sig_p = self.partidos["partidos"]["2022"].get(nr[:2], {}).get("sigla", "")
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
               "2026": {"t1": cands26(base, "presidente", None)}},
        "campos_2026": {"esq": [p26["esq"], p26["cands"][p26["esq"]]["nome"].title()],
                        "dir": [p26["dir"], p26["cands"][p26["dir"]]["nome"].title()]},
        "cores": base.partidos["cores_fixas"], "cores_eixo": base.partidos["cores_eixo"],
        "partidos": base.partidos["partidos"],
        "live_base_default": "dados/live",
    })


def escreve_br(base: Base) -> None:
    pr1 = base.soma22("pr22t1", ["uf"])
    pr2 = base.soma22("pr22t2", ["uf"])
    ufs = {}
    for uf, g in base.u26.groupby("uf"):
        ufs[uf] = {"pr22t1": base.vetor(pr1.loc[uf] if uf in pr1.index else None, "pr22t1", "BR"),
                   "pr22t2": base.vetor(pr2.loc[uf] if uf in pr2.index else None, "pr22t2", "BR"),
                   **proj(g)}
    tot = {"pr22t1": base.vetor(pr1.sum(), "pr22t1", "BR"), "pr22t2": base.vetor(pr2.sum(), "pr22t2", "BR"),
           **proj(base.u26)}
    grava(DOCS / "br.json", {"br": tot, "ufs": ufs})


def escreve_uf(base: Base, uf: str) -> None:
    u = base.u26[base.u26["uf"] == uf]
    niv = ["uf", "cd_mun"]
    ag = {k: base.soma22(k, niv) for k in base.tab}
    esc = {"pr22t1": "BR", "pr22t2": "BR", "gov22t1": uf, "gov22t2": uf, "sen22t1": uf}
    cands = {"gov": {"2022": {"t1": base.cands("gov22t1", uf) if "gov22t1" in base.tab else [],
                              "t2": base.cands("gov22t2", uf) if uf in base.ordem.get("gov22t2", {}) else []},
                     "2026": cands26(base, "governador", uf)},
             "sen": {"2022": {"t1": base.cands("sen22t1", uf) if "sen22t1" in base.tab else []},
                     "2026": cands26(base, "senador", uf)}}
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


def escreve_municipios(base: Base, uf: str) -> None:
    u = base.u26[base.u26["uf"] == uf]
    esc = {"pr22t1": "BR", "pr22t2": "BR", "gov22t1": uf, "gov22t2": uf, "sen22t1": uf}
    chaves = [k for k in base.tab if esc[k] == "BR" or uf in base.ordem[k]]
    cols = {k: base.ordem[k][esc[k]] + EXTRA for k in chaves}
    zon, loc, sec = {}, {}, {}
    for k in chaves:
        t = base.tab[k]
        t = t[t.index.get_level_values(0) == uf]
        sec[k] = _dic(t, cols[k])
        tl = t.reset_index()
        tl["nr_local"] = base.local22.reindex(pd.MultiIndex.from_frame(tl[SEC])).fillna(-1).astype(int).to_numpy()
        zon[k] = _dic(tl.groupby(["cd_mun", "zona"]).sum(numeric_only=True), cols[k])
        loc[k] = _dic(tl[tl["nr_local"] >= 0].groupby(["cd_mun", "zona", "nr_local"]).sum(numeric_only=True), cols[k])
    pz = _proj_dic(u, ["cd_mun", "zona"])
    pl = _proj_dic(u, ["cd_mun", "zona", "nr_local"])
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
    colunas_sec = ["secao", "nr_local", "aptos22", "n_agreg", "nivel_ancora", "aptos26", "proj26", "alvo26"] + chaves

    for cd, gm in u.groupby("cd_mun"):
        zonas = {}
        for z in sorted(gm["zona"].unique()):
            r = {**pz[(cd, z)], "ns": int(nsz[(cd, z)])}
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
                      [round(100 * row.alvo_esq, 2), round(100 * row.alvo_dir, 2)] if w == w else None]
                ln += [sec[k].get(kk) for k in chaves]
                linhas.append(ln)
            grava(DOCS / "sec" / str(cd) / f"{z}.json", {"cols": colunas_sec, "rows": linhas})


# ------------------------------------------------------------------ deputados
def escreve_deputados(base: Base, uf: str) -> None:
    ab = comparecimento(1)
    ab = ab[ab["uf"] == uf]
    ab_m = ab.groupby("cd_mun")[["comparecimento", "abst"]].sum()
    ab_z = ab.groupby(["cd_mun", "zona"])[["comparecimento", "abst"]].sum()
    out_uf = {}
    por_mun: dict = {}
    for cargo, arqc, arqp, arqn in [("df", "depfederal_candidato_secao_2022_t1.parquet",
                                     "depfederal_partido_secao_2022_t1.parquet", "depfederal_candidatos_2022.parquet"),
                                    ("de", "depestadual_candidato_secao_2022_t1.parquet",
                                     "depestadual_partido_secao_2022_t1.parquet", "depestadual_candidatos_2022.parquet")]:
        c = pd.read_parquet(BASELINE / arqc, filters=[("uf", "==", uf)])
        p = pd.read_parquet(BASELINE / arqp, filters=[("uf", "==", uf)])
        n = pd.read_parquet(BASELINE / arqn)
        n = n[n["uf"] == uf].set_index("nr")
        for d in (c, p):
            d["cd_mun"] = d["cd_municipio"].astype(int)
        tot = c.groupby("nr")["votos"].sum().sort_values(ascending=False)
        cand22 = [[nr, str(n["nome"].get(nr, nr)).title(), str(n["partido"].get(nr, "")), int(v),
                   str(n["sit"].get(nr, "")).title()] for nr, v in tot.items()]
        chave26 = "depfederal" if cargo == "df" else "depestadual"
        cand26 = [[nr, v["nome"].title(), v["partido"]] for nr, v in base.cand26[chave26].get(uf, {}).items()]
        out_uf[cargo] = {"2022": cand22, "2026": cand26}
        # legenda = nominal+legenda do partido - nominais dos candidatos do partido
        c["partido"] = c["nr"].str[:2]
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
            por_mun.setdefault(cd, {})[cargo] = {"mun": reg, "zonas": zonas}
    grava(DOCS / "dep" / f"{uf}.json", out_uf)
    for cd, v in por_mun.items():
        grava(DOCS / "dep" / uf / f"{cd}.json", v)



# ------------------------------------------------------------------ deputados por secao
def escreve_depsec(uf: str) -> None:
    """Detalhe candidato x SECAO de deputado: docs/dados/depsec/{mun}/{zona}_{df|de}.json.

    ~50 M linhas no pais (~400 MB de JSON): fica FORA do git (.gitignore) e so e servido
    pelo modo local/tunel. Formato: {"sec": {secao: [[nr, votos]...]}}, com os votos de
    legenda do partido como entradas "L<partido>". Gerar: web.gera_estatico --depsec."""
    from collections import defaultdict
    for cargo, arqc, arqp in [("df", "depfederal_candidato_secao_2022_t1.parquet",
                               "depfederal_partido_secao_2022_t1.parquet"),
                              ("de", "depestadual_candidato_secao_2022_t1.parquet",
                               "depestadual_partido_secao_2022_t1.parquet")]:
        c = pd.read_parquet(BASELINE / arqc, filters=[("uf", "==", uf)])
        if c.empty:
            continue
        pt = pd.read_parquet(BASELINE / arqp, filters=[("uf", "==", uf)])
        for d in (c, pt):
            d["cd_mun"] = d["cd_municipio"].astype(int)
        c["pp"] = c["nr"].str[:2]
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
            grava(DOCS / "depsec" / str(m) / f"{z}_{cargo}.json", {"sec": secs})


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
