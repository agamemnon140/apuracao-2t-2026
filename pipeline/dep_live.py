"""Bancadas de deputado ao vivo: quociente, sobras e cláusula, urna a urna.

O motor e o mesmo do needle_dep validado no replay (498/513 eleitos reproduzidos):

  1. share de cada AGREMIACAO (federacao = partido unico) projetado pelo modelo estadual
     sobre o eixo da ancora; incerteza k_p por estagio (calibrada em 2022);
  2. ordem NOMINAL dentro da agremiacao: share apurado de cada candidato tratado como
     amostra de tamanho efetivo ESS_p (Dirichlet);
  3. cada sorteio vira uma eleicao completa: totais -> quociente eleitoral -> pisos
     individuais (10% do QE para vaga de quociente; 80% da agremiacao / 20% do candidato
     nas sobras, EC 111) -> eleitos. Bancada = distribuicao dos sorteios (p10/med/p90).

Sobre o resultado nacional entra a CLAUSULA DE DESEMPENHO de 2026 (EC 97/2017): 2,5% dos
validos nacionais com 1,5% em pelo menos 9 UFs, OU 13 deputados federais eleitos em pelo
menos 9 UFs. Ela nao tira cadeira de ninguem -- restringe fundo partidario e propaganda --
entao entra como flag informativa por agremiacao (federacao avaliada como bloco).

Fontes de observacao:
  FonteBU      boletins raspados (live/bu.sqlite) -- a noite real
  FonteReplay  o voto de 2022 nas urnas ja "raspadas" do replay

Calibracao: baseline/calib_federal.json (estagios 3/5/10/20% de 2022). O estadual so foi
medido aos 10% (k 14%% menor, ESS igual); usa a curva federal escalada por essa razao.
Fora de 3-20% os valores sao grampeados (conservador).

Uso (teste):  .venv/Scripts/python -m pipeline.dep_live --replay --uf AC --pct 10
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

from pipeline import quociente
from pipeline.modelo_estadual import projeta
from pipeline.quociente import CADEIRAS, aloca
from sintetico.caminhos import BASELINE
from sintetico.caminhos import SAIDA as SAIDA_SINT

RAIZ = Path(__file__).resolve().parents[1]
CADEIRAS_EST = {uf: (3 * f if f <= 12 else 36 + (f - 12)) for uf, f in CADEIRAS.items()}
CARGOS_BU = {"federal": ("DEPUTADO FEDERAL",), "estadual": ("DEPUTADO ESTADUAL", "DEPUTADO DISTRITAL")}
MIN_URNAS = 5            # urnas observadas para projetar uma UF (mesmo piso do needle de 2022)
NDRAWS = 150

# clausula de desempenho valida para a eleicao de 2026 (EC 97/2017, art. 3o, III)
CLAUSULA = {"nacional": 0.025, "por_uf": 0.015, "n_ufs": 9, "eleitos": 13}


def _calib() -> dict:
    fed = {float(k): v for k, v in json.loads((BASELINE / "calib_federal.json").read_text()).items()}
    est10 = json.loads((BASELINE / "calib_estadual.json").read_text())["10"]
    ps = sorted(fed)
    razao_k = est10["k"] / fed[10.0]["k"]
    out = {"pct": ps,
           "federal": {"k": [fed[p]["k"] for p in ps], "ess": [fed[p]["ess"] for p in ps]},
           "estadual": {"k": [fed[p]["k"] * razao_k for p in ps], "ess": [fed[p]["ess"] for p in ps]}}
    return out


class FonteBU:
    """Boletins raspados: votos por partido (nominal + legenda) e por candidato."""

    def __init__(self, db: Path):
        self.db = db

    def obs(self, cargo: str, uf: str):
        if not self.db.exists():
            return None, None
        con = sqlite3.connect(self.db, timeout=30)
        marc = ",".join("?" * len(CARGOS_BU[cargo]))
        v = pd.read_sql(f"SELECT mun AS cd_mun, zona, secao, nr, votos FROM votos "
                        f"WHERE uf=? AND cargo IN ({marc})", con, params=(uf.lower(), *CARGOS_BU[cargo]))
        con.close()
        if v.empty:
            return None, None
        v["partido"] = np.where(v["nr"].str.startswith("L"), v["nr"].str[1:], v["nr"].str[:2])
        nominal = v[~v["nr"].str.startswith("L")].groupby("nr")["votos"].sum().astype(float)
        return v.groupby(["cd_mun", "zona", "secao", "partido"], as_index=False)["votos"].sum(), nominal


class FonteReplay:
    """O voto real de 2022 nas urnas que o replay considera raspadas (cache por UF)."""

    def __init__(self, anc: pd.DataFrame):
        self.anc = anc[["uf", "cd_mun", "zona", "secao"]].reset_index(drop=True)
        self.idx = np.zeros(0, dtype=int)
        self._p: dict = {}
        self._c: dict = {}

    def define_idx(self, idx: np.ndarray) -> None:
        self.idx = np.asarray(idx, dtype=int) if idx is not None and len(idx) else np.zeros(0, int)

    def _carrega(self, cargo: str, uf: str):
        if (cargo, uf) not in self._p:
            p = pd.read_parquet(BASELINE / f"dep{cargo}_partido_secao_2022_t1.parquet",
                                filters=[("uf", "==", uf)])
            p["cd_mun"] = p["cd_municipio"].astype(np.int32)
            self._p[(cargo, uf)] = p[["cd_mun", "zona", "secao", "partido", "votos"]]
            c = pd.read_parquet(BASELINE / f"dep{cargo}_candidato_secao_2022_t1.parquet",
                                filters=[("uf", "==", uf)])
            c["cd_mun"] = c["cd_municipio"].astype(np.int32)
            self._c[(cargo, uf)] = c[["cd_mun", "zona", "secao", "nr", "votos"]]
        return self._p[(cargo, uf)], self._c[(cargo, uf)]

    def obs(self, cargo: str, uf: str):
        if not len(self.idx):
            return None, None
        a = self.anc.iloc[self.idx]
        k = a.loc[a["uf"] == uf, ["cd_mun", "zona", "secao"]]
        if k.empty:
            return None, None
        p, c = self._carrega(cargo, uf)
        po = p.merge(k, on=["cd_mun", "zona", "secao"])
        if po.empty:
            return None, None
        nominal = c.merge(k, on=["cd_mun", "zona", "secao"]).groupby("nr")["votos"].sum().astype(float)
        return po, nominal


class DepLive:
    def __init__(self, anc: pd.DataFrame, ano: int, fonte, ndraws: int = NDRAWS):
        quociente.define_ano(ano)
        self.mapa_agr = quociente.federacoes(ano)
        self.fonte, self.ndraws = fonte, ndraws
        self.calib = _calib()
        cfg = json.loads((RAIZ / "config" / "partidos.json").read_text("utf-8"))
        self.sigla = {nr: d["sigla"] for nr, d in cfg["partidos"][str(ano)].items()}
        a = anc[anc["uf"] != "ZZ"]
        base = pd.DataFrame({"uf": a["uf"], "cd_municipio": a["cd_mun"].astype(str),
                             "cd_mun": a["cd_mun"], "zona": a["zona"], "secao": a["secao"],
                             "aptos": a["aptos"].astype(float),
                             "z": 2.0 / (1.0 + np.exp(-a["a_ed"].to_numpy(float))) - 1.0})
        self.uni = {uf: g.reset_index(drop=True) for uf, g in base.groupby("uf")}

    def rotulo(self, agr: str) -> str:
        return agr[4:].replace("/", "·") if agr.startswith("FED-") else self.sigla.get(agr, agr)

    def _kess(self, cargo: str, pct: float) -> tuple[float, float]:
        c = self.calib
        return (float(np.interp(pct, c["pct"], c[cargo]["k"])),
                float(np.interp(pct, c["pct"], c[cargo]["ess"])))

    def _monta(self, uf: str, po: pd.DataFrame):
        """Observado por agremiacao + universo que falta -> tabela do modelo estadual."""
        po = po.copy()
        po["agr"] = po["partido"].map(lambda x: self.mapa_agr.get(x, x))
        wide = (po.pivot_table(index=["cd_mun", "zona", "secao"], columns="agr", values="votos",
                               aggfunc="sum", fill_value=0).reset_index())
        agrs = [c for c in wide.columns if c not in ("cd_mun", "zona", "secao")]
        uni = self.uni[uf]
        ap = wide.merge(uni[["cd_mun", "zona", "secao", "cd_municipio", "aptos", "z"]],
                        on=["cd_mun", "zona", "secao"], how="left")
        ap["z"] = ap["z"].fillna(float(np.average(uni["z"], weights=uni["aptos"])))
        ap["cd_municipio"] = ap["cd_municipio"].fillna(ap["cd_mun"].astype(str))
        ap["validos"] = ap[agrs].sum(axis=1)
        ap["aptos"] = ap["aptos"].fillna(ap["validos"] * 1.25)
        falta = uni.merge(wide[["cd_mun", "zona", "secao"]], on=["cd_mun", "zona", "secao"],
                          how="left", indicator=True)
        falta = falta[falta["_merge"] == "left_only"].drop(columns="_merge")
        for c in agrs:
            falta[c] = 0.0
        falta["validos"] = 0.0
        cols = ["cd_municipio", "aptos", "z", "validos"] + agrs
        sec = pd.concat([ap[cols], falta[cols]], ignore_index=True)
        n = len(ap)
        taxa = ap["validos"].sum() / max(ap["aptos"].sum(), 1.0)
        validos_proj = float(ap["validos"].sum() + taxa * falta["aptos"].sum())
        pct = 100.0 * n / max(len(uni), 1)
        return sec, agrs, n, validos_proj, pct

    def _uf(self, cargo: str, uf: str, rng) -> dict | None:
        po, nominal = self.fonte.obs(cargo, uf)
        if po is None:
            return None
        sec, agrs, n, validos, pct = self._monta(uf, po)
        if n < MIN_URNAS:
            return None
        pr = projeta(sec, agrs, n)
        if pr.empty:
            return None
        k, ess = self._kess(cargo, pct)
        cadeiras = (CADEIRAS if cargo == "federal" else CADEIRAS_EST)[uf]

        por_agr: dict[str, dict] = {}
        for nr, v in nominal.items():
            por_agr.setdefault(self.mapa_agr.get(nr[:2], nr[:2]), {})[nr] = float(v)
        va_ap = sec[agrs].iloc[:n].sum()
        f_nom = {a: min(1.0, sum(d.values()) / float(va_ap[a])) if va_ap.get(a, 0) > 0 else 0.9
                 for a, d in por_agr.items()}

        s = pr.to_numpy(float)
        seats_draws = []
        for dr in range(self.ndraws):
            eps = rng.normal(0, k * np.sqrt(np.clip(s * (1 - s), 1e-9, None)))
            sd = np.clip(s + eps, 0, None)
            sd /= sd.sum()
            votos_agr = {a: float(sd[i] * validos) for i, a in enumerate(pr.index)}
            nominais = {}
            for a, d in por_agr.items():
                if a not in votos_agr:
                    continue
                nrs = list(d)
                wv = np.array([d[x] for x in nrs], float)
                alpha = np.clip(wv / max(wv.sum(), 1e-9) * ess, 1e-3, None)
                tot = votos_agr[a] * f_nom.get(a, 0.9)
                for x, sh in zip(nrs, rng.dirichlet(alpha)):
                    nominais[x] = tot * sh
            por = {}
            for e in aloca(votos_agr, nominais, uf, vagas=cadeiras):
                a_ = self.mapa_agr.get(e[:2], e[:2])
                por[a_] = por.get(a_, 0) + 1
            seats_draws += [(dr, a_, c_) for a_, c_ in por.items()]

        # projecao de ponto (para a clausula)
        votos_pt = {a: float(pr[a] * validos) for a in pr.index}
        nom_pt = {}
        for a, d in por_agr.items():
            if a not in votos_pt:
                continue
            ss = sum(d.values())
            for x, v in d.items():
                nom_pt[x] = votos_pt[a] * (v / ss) * f_nom.get(a, 0.9)
        eleitos_pt = aloca(votos_pt, nom_pt, uf, vagas=cadeiras)
        el_agr: dict[str, int] = {}
        for e in eleitos_pt:
            a_ = self.mapa_agr.get(e[:2], e[:2])
            el_agr[a_] = el_agr.get(a_, 0) + 1
        return {"uf": uf, "pct": pct, "n": n, "validos": validos,
                "draws": pd.DataFrame(seats_draws, columns=["draw", "agr", "seats"]),
                "votos_pt": votos_pt, "eleitos_pt": el_agr}

    def _junta(self, cargo: str, por_uf: dict) -> dict:
        """Soma as UFs (mesmo indice de sorteio: estados independentes) -> contrato live.json."""
        dfs = []
        for uf, r in por_uf.items():
            d = r["draws"].copy()
            d["uf"] = uf
            dfs.append(d)
        s = pd.concat(dfs, ignore_index=True)
        nac = (s.pivot_table(index="draw", columns="agr", values="seats", aggfunc="sum")
               .reindex(range(self.ndraws)).fillna(0))
        linhas = []
        for a in nac.columns:
            v = nac[a].to_numpy()
            linhas.append({"agr": self.rotulo(a), "_agr": a, "p10": int(np.percentile(v, 10)),
                           "med": int(np.median(v)), "p90": int(np.percentile(v, 90))})
        linhas.sort(key=lambda x: -x["med"])
        por = {}
        for uf, g in s.groupby("uf"):
            piv = (g.pivot_table(index="draw", columns="agr", values="seats", aggfunc="sum")
                   .reindex(range(self.ndraws)).fillna(0))
            por[uf] = sorted(({"agr": self.rotulo(a), "med": int(piv[a].median())}
                              for a in piv.columns if piv[a].median() >= 1), key=lambda x: -x["med"])
        if cargo == "federal":
            self._clausula(linhas, por_uf)
        for x in linhas:
            x.pop("_agr", None)
        return {"nacional": [x for x in linhas if x["p90"] >= 1], "por_uf": por,
                "ufs_cobertas": len(por_uf),
                "pct_medio": round(float(np.mean([r["pct"] for r in por_uf.values()])), 1)}

    def _clausula(self, linhas: list, por_uf: dict) -> None:
        """EC 97/2017 para 2026: 2,5% nacional com 1,5% em >=9 UFs, ou 13 eleitos em >=9 UFs.
        Informativa (fundo/propaganda), nao tira cadeira; federacao avaliada como bloco."""
        tot_nac = sum(r["validos"] for r in por_uf.values())
        for x in linhas:
            a = x["_agr"]
            v_nac = sum(r["votos_pt"].get(a, 0.0) for r in por_uf.values())
            n_ufs_voto = sum(1 for r in por_uf.values()
                             if r["votos_pt"].get(a, 0.0) / r["validos"] >= CLAUSULA["por_uf"])
            el = sum(r["eleitos_pt"].get(a, 0) for r in por_uf.values())
            n_ufs_el = sum(1 for r in por_uf.values() if r["eleitos_pt"].get(a, 0) >= 1)
            por_voto = (v_nac / tot_nac >= CLAUSULA["nacional"]) and n_ufs_voto >= CLAUSULA["n_ufs"]
            por_eleito = el >= CLAUSULA["eleitos"] and n_ufs_el >= CLAUSULA["n_ufs"]
            x["clausula"] = bool(por_voto or por_eleito)
            x["sh_nac"] = round(100 * v_nac / tot_nac, 2)

    def roda(self, seed: int = 2026) -> dict:
        rng = np.random.default_rng(seed)
        out = {}
        for cargo, chave in (("federal", "camara"), ("estadual", "assembleias")):
            por_uf = {}
            for uf in sorted(self.uni):
                try:
                    r = self._uf(cargo, uf, rng)
                except Exception as e:                      # uma UF nao derruba a bancada
                    import logging
                    logging.warning("dep %s %s: %s", cargo, uf, e)
                    r = None
                if r is not None:
                    por_uf[uf] = r
            out[chave] = self._junta(cargo, por_uf) if len(por_uf) == len(self.uni) else None
            if out[chave] is None and por_uf:
                out[chave + "_parcial"] = sorted(set(self.uni) - set(por_uf))
        return out


def main() -> int:
    import sys
    a = sys.argv[1:]
    uf = a[a.index("--uf") + 1] if "--uf" in a else "AC"
    pct = float(a[a.index("--pct") + 1]) if "--pct" in a else 10.0
    anc = pd.read_parquet(SAIDA_SINT / "ancora_2022_calib.parquet")
    car = pd.read_parquet(BASELINE / "carimbos_presidente_2022_t1.parquet")
    car["cd_mun"] = car["cd_municipio"].astype(int)
    ordem = anc.merge(car[["uf", "cd_mun", "zona", "secao", "prim_tot"]],
                      on=["uf", "cd_mun", "zona", "secao"], how="left")["prim_tot"]
    corte = ordem.dropna().sort_values().iloc[int(ordem.notna().sum() * pct / 100)]
    idx = np.flatnonzero((ordem <= corte).to_numpy())
    fonte = FonteReplay(anc)
    fonte.define_idx(idx)
    dep = DepLive(anc, 2022, fonte)
    rng = np.random.default_rng(2026)
    for cargo in ("federal", "estadual"):
        r = dep._uf(cargo, uf, rng)
        if r is None:
            print(f"{cargo} {uf}: sem dados")
            continue
        j = dep._junta(cargo, {uf: r})
        print(f"{cargo} {uf} ({r['pct']:.1f}% das urnas): "
              f"{[(x['agr'], x['med'], (x['p10'], x['p90'])) for x in j['nacional']]}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
