"""Governador e Senado ao vivo: o modelo estadual validado (pipeline/modelo_estadual.projeta)
alimentado por boletins de urna raspados.

Cada UF vira uma tabela de secoes: primeiro as ja raspadas (com votos por candidato), depois
as que faltam (universo de 2026, com eleitorado apto). O eixo geografico de cada secao e a
propria ANCORA do needle presidencial (z = 2*sigma(a_ed) - 1, a margem esq-dir esperada),
de modo que governo e Senado andam sobre a mesma base que o presidente.

Incerteza: RMS do erro da margem lider-vice nas 27 corridas de 2022 de cada cargo, por
estagio de apuracao (calibra()). Senado 2026 tem 2 vagas: alem de P(lider), sai
P(entre os 2) do 2o colocado, pela margem 2o-3o.

Uso:
  .venv/Scripts/python -m pipeline.estadual_live --calibra     grava baseline/calib_estadual_hier.json
"""
from __future__ import annotations

import json
import math
import sys

import numpy as np
import pandas as pd

from pipeline.modelo_estadual import projeta
from sintetico.caminhos import BASELINE

MARCOS = [0.5, 1, 2, 3, 5, 7, 10, 15, 20, 30, 50, 70, 90]
ARQ_CALIB = BASELINE / "calib_estadual_hier.json"


def phi(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def calibra() -> dict:
    from probe.calibracao import corridas
    erros: dict = {}
    for cargo, uf, sec, comp in corridas():
        final = sec[comp].sum() / sec[comp].sum().sum()
        for p in MARCOS:
            n = max(5, int(len(sec) * p / 100))
            pr = projeta(sec, comp, n)
            if pr.empty:
                continue
            po = pr.sort_values(ascending=False)
            m_hat = float(po.iloc[0] - po.iloc[1])
            m_fin = float(final[po.index[0]] - final[po.index[1]])
            erros.setdefault(cargo, {}).setdefault(p, []).append(100 * (m_hat - m_fin))
    out = {"pct": [0.0] + MARCOS + [100.0]}
    for cargo, d in erros.items():
        s = [max(1.0, 1.25 * float(np.sqrt(np.mean(np.square(d[p]))))) for p in MARCOS]
        s = list(np.maximum.accumulate(s[::-1])[::-1])            # envoltoria conservadora
        out[cargo] = [30.0] + s + [0.2]
    ARQ_CALIB.write_text(json.dumps(out, indent=1), "utf-8")
    return out


def sigma(calib: dict, cargo: str, pct: float) -> float:
    return float(np.interp(pct, calib["pct"], calib[cargo]))


def corrida(anc_uf: pd.DataFrame, obs: pd.DataFrame, cands: list[str]) -> pd.Series | None:
    """anc_uf: urnas da UF (cd_mun, zona, secao, aptos, a_ed). obs: urnas raspadas com colunas
    = numeros dos candidatos. Devolve fatia projetada dos validos por candidato."""
    chave = ["cd_mun", "zona", "secao"]
    if obs is None or obs.empty:
        return None
    cands = [c for c in cands if c in obs.columns] or [c for c in obs.columns if c not in chave]
    o = obs[chave + cands].copy()
    o["validos"] = o[cands].sum(axis=1)
    o = o[o["validos"] > 0]
    if len(o) < 3:
        return None
    base = anc_uf[chave + ["aptos", "a_ed"]].copy()
    base["z"] = 2 / (1 + np.exp(-base["a_ed"])) - 1
    ap = o.merge(base[chave + ["aptos", "z"]], on=chave, how="left")
    ap["z"] = ap["z"].fillna(float(np.average(base["z"], weights=base["aptos"])))
    ap["aptos"] = ap["aptos"].fillna(ap["validos"] * 1.3)
    falta = base.merge(o[chave], on=chave, how="left", indicator=True)
    falta = falta[falta["_merge"] == "left_only"].drop(columns="_merge")
    for c in cands:
        falta[c] = 0.0
    falta["validos"] = 0.0
    sec = pd.concat([ap[chave + ["aptos", "z", "validos"] + cands], falta[chave + ["aptos", "z", "validos"] + cands]],
                    ignore_index=True).rename(columns={"cd_mun": "cd_municipio"})
    return projeta(sec, cands, len(ap))


def painel(cargo: str, uf: str, pr: pd.Series | None, pct: float, calib: dict, nomes: dict,
           tela: dict | None = None, vagas: int = 1) -> dict:
    """Linha do live.json (contrato do index.html): lider, share, segundo, share2, p_lider."""
    fonte = pr if pr is not None and not pr.empty else (pd.Series(tela) / max(sum(tela.values()), 1) if tela else None)
    if fonte is None or fonte.empty or len(fonte) < 2:
        return {"uf": uf, "pct_secoes": round(pct, 1), "lider": "–", "share": 0, "segundo": "–", "share2": 0,
                "p_lider": 0.5}
    po = fonte.sort_values(ascending=False)
    sg = sigma(calib, "GOV" if cargo == "governador" else "SEN", pct)
    d = {"uf": uf, "pct_secoes": round(pct, 1),
         "lider": nomes.get(po.index[0], po.index[0]).title()[:24], "share": round(100 * po.iloc[0], 1),
         "segundo": nomes.get(po.index[1], po.index[1]).title()[:24], "share2": round(100 * po.iloc[1], 1),
         "p_lider": round(min(0.999, phi(100 * (po.iloc[0] - po.iloc[1]) / sg)), 3),
         "projetado": pr is not None and not pr.empty,
         "proj": {str(k): round(float(v), 5) for k, v in po.items()}}
    if vagas == 2 and len(po) >= 3:
        d["terceiro"] = nomes.get(po.index[2], po.index[2]).title()[:24]
        d["share3"] = round(100 * po.iloc[2], 1)
        d["p_top2"] = round(min(0.999, phi(100 * (po.iloc[1] - po.iloc[2]) / sg)), 3)
    return d


if __name__ == "__main__":
    if "--calibra" in sys.argv:
        c = calibra()
        for k in [x for x in c if x != "pct"]:
            print(k, [round(v, 2) for v in c[k]])
    sys.exit(0)
