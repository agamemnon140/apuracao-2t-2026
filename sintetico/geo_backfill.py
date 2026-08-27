"""Vinculo geografico dos anos antigos: os locais de votacao de cada ano (o TSE
retro-geocodificou ate 2010) ganham entorno nas DUAS fotografias censitarias
(setores 2010 e 2022) e o atributo final e a mistura linear decidida pelo usuario:

    w = (data da eleicao - censo 2010) / (censo 2022 - censo 2010)
    atributo = (1-w) * censo2010 + w * censo2022      (renda no espaco log)

2010: w=0 (Censo 2010 puro). 2014: w=0.354. 2018: w=0.688.

Saidas: locais_atributos_{ano}.parquet e municipio_atributos_{ano}.parquet.

Uso:  .venv/Scripts/python -m sintetico.geo_backfill <2010|2014|2018>
"""
from __future__ import annotations

import sys

import numpy as np
import pandas as pd

from .caminhos import SAIDA
from .geo import ATRIBS, carrega_locais, carrega_setores, crosswalk, vincula

PESO = {2010: 0.0, 2014: 0.354, 2018: 0.688}
CHAVE = ["uf", "cd_municipio_tse", "zona", "nr_local"]


def mistura(a10: pd.DataFrame, a22: pd.DataFrame, w: float, chave) -> pd.DataFrame:
    m = a10.merge(a22, on=chave, how="outer", suffixes=("_10", "_22"))
    for c in ATRIBS:
        v10, v22 = m[f"{c}_10"], m[f"{c}_22"]
        if c == "renda_media":     # nominal 2010 vs 2022: interpolar em log
            comb = np.exp((1 - w) * np.log(v10.clip(lower=1)) + w * np.log(v22.clip(lower=1)))
        else:
            comb = (1 - w) * v10 + w * v22
        m[c] = comb.where(v10.notna() & v22.notna(), v22 if w >= 0.5 else v10)
        m[c] = m[c].fillna(v22).fillna(v10)
        m = m.drop(columns=[f"{c}_10", f"{c}_22"])
    if "origem_10" in m.columns:
        m["origem"] = np.where((m["origem_10"] == "voronoi") | (m["origem_22"] == "voronoi"),
                               "voronoi", "municipio")
        m = m.drop(columns=["origem_10", "origem_22"])
    return m


def main() -> int:
    ano = int(sys.argv[1])
    w = PESO[ano]
    locais = carrega_locais(ano)
    s22 = carrega_setores(2022)
    s10 = carrega_setores(2010)
    liga = crosswalk(locais, s22)     # lista de municipios IBGE 2022 (nomes atuais)
    locais = locais.merge(liga, on="cd_municipio_tse", how="left")

    print(f"== {ano}: Voronoi contra setores 2010")
    l10, m10 = vincula(s10, locais)
    print(f"== {ano}: Voronoi contra setores 2022")
    l22, m22 = vincula(s22, locais)

    df = mistura(l10.drop(columns=["cd_mun"]), l22, w, CHAVE)
    mun = mistura(m10, m22, w, ["cd_mun"])
    print(f"{ano} (w={w}): {len(df)} locais, voronoi {100 * (df['origem'] == 'voronoi').mean():.1f}%")

    df.to_parquet(SAIDA / f"locais_atributos_{ano}.parquet", index=False)
    mun = mun.merge(liga, on="cd_mun", how="left")
    mun.to_parquet(SAIDA / f"municipio_atributos_{ano}.parquet", index=False)
    print(f"gravados locais_atributos_{ano}.parquet e municipio_atributos_{ano}.parquet")
    return 0


if __name__ == "__main__":
    sys.exit(main())
