"""Consolida tudo que o relatorio precisa em sintetico/relatorio_dados.json:
metricas 2022, coeficientes, drop-one, erro por UF, dispersao municipal,
projecao 2026 e o comparativo entre ciclos (backfill).

Uso:  .venv/Scripts/python -m sintetico.relatorio_dados
"""
from __future__ import annotations

import json
import sys

import numpy as np
import pandas as pd

from .caminhos import SAIDA


def main() -> int:
    M = json.load(open(SAIDA / "modelo_2022.json", encoding="utf-8"))
    P = json.load(open(SAIDA / "projecao_2026.json", encoding="utf-8"))
    comp = json.load(open(SAIDA / "comparativo.json", encoding="utf-8"))
    pred = pd.read_parquet(SAIDA / "pred_2022.parquet")

    coef = np.array(M["coef"])
    cols = M["cols"]
    lb = (coef[0] - coef[1]).round(3)
    nen = (coef[2] - (coef[0] + coef[1]) / 2).round(3)

    aptos = pred["aptos"].to_numpy(float)
    cont = np.c_[pred["sh_lula"], pred["sh_bolsonaro"], pred["sh_nenhum"]] * aptos[:, None]
    p = np.c_[pred["p_lula"], pred["p_bolsonaro"], pred["p_nenhum"]]
    sh = cont / aptos[:, None]
    ll = (cont * np.log(np.clip(p, 1e-12, None))).sum()
    p0 = cont.sum(0) / cont.sum()
    ll0 = (cont * np.log(p0)).sum()
    llsat = (cont[sh > 0] * np.log(sh[sh > 0])).sum()
    vs_obs = sh[:, 0] / (sh[:, 0] + sh[:, 1])
    vs_prev = p[:, 0] / (p[:, 0] + p[:, 1])
    r2_val = float(1 - np.average((vs_obs - vs_prev) ** 2, weights=aptos) /
                   np.average((vs_obs - np.average(vs_obs, weights=aptos)) ** 2, weights=aptos))

    por_uf = {}
    for uf, v in M["por_uf"].items():
        pv, rl = v["prev"], v["real"]
        por_uf[uf] = {"prev": 100 * pv[0] / (pv[0] + pv[1]),
                      "real": 100 * rl[0] / (rl[0] + rl[1])}

    pred = pred.assign(vo=vs_obs, vp=vs_prev)
    g = pred.groupby(["uf", "cd_municipio_tse"]).apply(
        lambda d: pd.Series({"o": np.average(d["vo"], weights=d["aptos"]),
                             "p": np.average(d["vp"], weights=d["aptos"]),
                             "w": d["aptos"].sum()}), include_groups=False).reset_index()
    disp = [[round(r.o, 4), round(r.p, 4), int(r.w), r.uf] for r in g.itertuples()]

    out = {"n_secoes": len(pred), "aptos": int(aptos.sum()),
           "dev_expl": float((ll - ll0) / (llsat - ll0)),
           "r2_validos": r2_val,
           "mae_validos": float(np.average(np.abs(vs_obs - vs_prev), weights=aptos)),
           "coefs": {c: {"lb": float(a), "nen": float(b)} for c, a, b in zip(cols, lb, nen)},
           "drop": {k: 100 * v["perda"] / M["pseudo_r2"] for k, v in M["drop_one"].items()},
           "por_uf": por_uf, "proj": P, "disp": disp, "comp": comp}
    with open(SAIDA / "relatorio_dados.json", "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False)
    print(f"dev_expl {out['dev_expl']:.4f} | r2 {r2_val:.3f} | "
          f"drop top: {max(out['drop'], key=out['drop'].get)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
