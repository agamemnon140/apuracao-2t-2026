"""Heterogeneidade interna dos municipios e o vies que ela produz na apuracao.

Duas grandezas diferentes, que costumam ser confundidas:

  H_m   -- HETEROGENEIDADE: o quanto as secoes de um municipio diferem entre si politicamente
           (desvio-padrao do eixo esquerda-direita de 2018 dentro da cidade, ponderado por
           eleitorado). Alta = a cidade tem bairros que votam de formas opostas.

  rho_m -- ORDEM: correlacao entre a ordem de chegada das secoes e o eixo delas. Alta = a
           cidade apura de um lado politico para o outro.

A tese: heterogeneidade sozinha nao enviesa nada. Uma cidade partida ao meio, mas que apura
suas secoes em ordem politicamente aleatoria, entrega um parcial nao-enviesado desde o comeco.
O estrago vem do PRODUTO -- ser heterogenea E apurar em ordem. Este script mede qual das duas
explica o vies real observado em 2022.

Uso:  .venv/Scripts/python -m probe.heterogeneidade
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

BASE = Path(r"D:\Claude\eleicoes-dados\baseline")
CHAVE = ["uf", "cd_municipio", "zona", "secao"]
MIN_SECOES = 10          # abaixo disso, "ordem interna" nao quer dizer nada


def carrega() -> pd.DataFrame:
    votos = pd.read_parquet(BASE / "presidente_secao_2022.parquet")
    ancora = pd.read_parquet(BASE / "presidente_secao_2018.parquet")
    quando = pd.read_parquet(BASE / "carimbos_presidente_2022_t1.parquet")

    dois = ancora["t2_esq"] + ancora["t2_dir"]
    ancora = ancora.assign(z=(ancora["t2_esq"] - ancora["t2_dir"]) / dois.where(dois > 0))[CHAVE + ["z"]]

    df = votos.merge(quando[CHAVE + ["aptos", "prim_tot"]], on=CHAVE).merge(ancora, on=CHAVE)
    df = df[(df["validos_t1"] > 0) & df["z"].notna()].copy()
    df["m"] = (df["t1_esq"] - df["t1_dir"]) / df["validos_t1"]
    return df


def por_municipio(df: pd.DataFrame) -> pd.DataFrame:
    linhas = []
    for (uf, cd), g in df.groupby(["uf", "cd_municipio"], sort=False):
        if len(g) < MIN_SECOES:
            continue
        g = g.sort_values("prim_tot")
        w = g["validos_t1"].to_numpy(float)
        z, m = g["z"].to_numpy(), g["m"].to_numpy()
        zbar = np.average(z, weights=w)
        H = float(np.sqrt(np.average((z - zbar) ** 2, weights=w)))
        rho = float(np.corrcoef(np.arange(len(g)), z)[0, 1]) if len(g) > 2 else 0.0

        k = max(3, len(g) // 4)                       # primeiro quarto a chegar
        parcial = float(np.average(m[:k], weights=w[:k]))
        finalm = float(np.average(m, weights=w))
        linhas.append({"uf": uf, "cd_municipio": cd, "secoes": len(g),
                       "eleitorado": float(g["aptos"].sum()),
                       "H": H, "rho": rho, "H_x_rho": H * rho,
                       "vies_real": 100 * (parcial - finalm)})
    return pd.DataFrame(linhas)


def main() -> None:
    d = por_municipio(carrega())
    print(f"municipios com >= {MIN_SECOES} secoes: {len(d):,} "
          f"({100*d['eleitorado'].sum()/d['eleitorado'].sum():.0f}% do eleitorado deles)\n")

    print("HETEROGENEIDADE INTERNA (desvio-padrao do eixo dentro da cidade)")
    print(d["H"].describe(percentiles=[.1, .25, .5, .75, .9]).round(3).to_string())

    print("\nVIES REAL do primeiro quarto apurado (pontos de margem), por faixa de heterogeneidade")
    d["faixa_H"] = pd.qcut(d["H"], 5, labels=["1 (homogeneo)", "2", "3", "4", "5 (heterogeneo)"])
    d["faixa_ordem"] = pd.qcut(d["rho"].abs(), 5, labels=["1 (ordem aleatoria)", "2", "3", "4", "5 (ordem forte)"])
    print(d.groupby("faixa_H", observed=True)["vies_real"]
          .agg(mediana_abs=lambda s: s.abs().median(), p90_abs=lambda s: s.abs().quantile(.9),
               n="size").round(2).to_string())

    print("\nO MESMO, por faixa de ORDEM (correlacao entre chegada e eixo)")
    print(d.groupby("faixa_ordem", observed=True)["vies_real"]
          .agg(mediana_abs=lambda s: s.abs().median(), p90_abs=lambda s: s.abs().quantile(.9),
               n="size").round(2).to_string())

    print("\nCRUZAMENTO: |vies real| mediano por heterogeneidade x ordem")
    tab = d.pivot_table(index="faixa_H", columns="faixa_ordem",
                        values="vies_real", aggfunc=lambda s: s.abs().median(), observed=True)
    print(tab.round(2).to_string())

    print("\nCORRELACAO com |vies real|:")
    for c in ("H", "rho", "H_x_rho"):
        val = d[c].abs().corr(d["vies_real"].abs())
        print(f"  {c:>8}  {val:+.3f}")

    grandes = d.nlargest(12, "eleitorado")[["uf", "secoes", "eleitorado", "H", "rho", "vies_real"]]
    print("\n12 maiores cidades:")
    print(grandes.assign(eleitorado=(grandes["eleitorado"] / 1e3).round(0)).round(3).to_string(index=False))


if __name__ == "__main__":
    main()
