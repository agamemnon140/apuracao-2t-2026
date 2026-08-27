"""Teste de hipotese: cidades grandes (1M+) se des-regionalizam (convergem para o
centro nacional) enquanto nas pequenas o efeito regional e mais forte?

Duas medidas, por ciclo (2010-2022) e por estrato de porte (1M+, 100k-1M, <100k;
populacao municipal do Censo 2022, congelada):

1. Descritiva: dispersao ENTRE regioes do share de esquerda nos validos, dentro de
   cada estrato (desvio-padrao ponderado das medias regionais em torno da media do
   estrato). Convergencia = dispersao caindo no tempo.
2. Modelo: o multinomial reajustado dentro de cada estrato (padronizacao fixa de
   2022); o tamanho medio dos coeficientes regionais (|esq-dir| das dummies N, NE,
   CO, S vs SE) mede o efeito regional LIQUIDO de demografia. Inclui drop-one da
   regiao por estrato.

Saida: sintetico/regionalizacao.json.

Uso:  .venv/Scripts/python -m sintetico.regionalizacao
"""
from __future__ import annotations

import json
import sys

import numpy as np
import pandas as pd

from .caminhos import SAIDA
from .modelo import EIXOS, ajusta, metricas, monta_xy

ANOS = [2010, 2014, 2018, 2022]
CORTES = [(1_000_000, float("inf"), "1M+"),
          (100_000, 1_000_000, "100k-1M"),
          (0, 100_000, "<100k")]
REGS = ["reg_N", "reg_NE", "reg_CO", "reg_S"]


def dispersao_regional(df: pd.DataFrame) -> dict:
    """Desvio-padrao ponderado das medias regionais vs a media do estrato (pp)."""
    validos = df["lula"] + df["bolsonaro"]
    df = df.assign(_v=validos, _e=df["lula"])
    por_reg = df.groupby("regiao").agg(e=("_e", "sum"), v=("_v", "sum"))
    por_reg["m"] = por_reg["e"] / por_reg["v"]
    M = por_reg["e"].sum() / por_reg["v"].sum()
    var = ((por_reg["m"] - M) ** 2 * por_reg["v"]).sum() / por_reg["v"].sum()
    return {"disp_pp": float(100 * np.sqrt(var)), "media": float(100 * M),
            "por_regiao": {r: float(100 * v) for r, v in por_reg["m"].items()}}


def main() -> int:
    with open(SAIDA / "modelo_2022.json", encoding="utf-8") as fh:
        m22 = json.load(fh)
    cols = m22["cols"]
    i_regs = [cols.index(r) for r in REGS]

    saida: dict = {}
    for ano in ANOS:
        base = pd.read_parquet(SAIDA / f"base_{ano}.parquet")
        saida[str(ano)] = {}
        for lo, hi, nome in CORTES:
            df = base[(base["mun_pop"] >= lo) & (base["mun_pop"] < hi)]
            item = {"n_secoes": int(len(df)),
                    "n_municipios": int(df["cd_municipio_tse"].nunique()),
                    **dispersao_regional(df)}

            Xz, cont, _, _, _ = monta_xy(df, m22["mu"], m22["sd"])
            m = ajusta(Xz, cont, max_iter=8000)
            _, ll, ll0, r2 = metricas(m, Xz, cont)
            lb = m.coef_[0] - m.coef_[1]
            item["coef_reg"] = {r: float(lb[i]) for r, i in zip(REGS, i_regs)}
            item["coef_reg_medio"] = float(np.mean([abs(lb[i]) for i in i_regs]))

            idx = [i for i in range(len(cols)) if i not in i_regs]
            m_r = ajusta(Xz[:, idx], cont, max_iter=8000)
            _, _, _, r2_r = metricas(m_r, Xz[:, idx], cont)
            item["drop_regiao_share"] = float((r2 - r2_r) / r2) if r2 > 0 else np.nan

            saida[str(ano)][nome] = item
            print(f"{ano} {nome:8s}: {item['n_municipios']:4d} mun, "
                  f"{item['n_secoes']:6d} sec | dispersao {item['disp_pp']:5.2f}pp | "
                  f"|coef reg| medio {item['coef_reg_medio']:.3f} | "
                  f"drop regiao {100 * item['drop_regiao_share']:.1f}%", flush=True)

    with open(SAIDA / "regionalizacao.json", "w", encoding="utf-8") as fh:
        json.dump(saida, fh, ensure_ascii=False, indent=1)
    print("gravado regionalizacao.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
