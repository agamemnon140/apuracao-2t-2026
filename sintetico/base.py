"""Monta a base de modelagem: uma linha por secao com os 3 shares e as covariaveis.

Juncoes:
  alvo (shares + nr_local)  x  perfil TSE (sexo/idade/escolaridade da secao)
  x  atributos do local (Voronoi sobre setores: renda, raca, rural)
  x  atributos municipais (religiao, VAB, ocupacao, hierarquia urbana, populacao).

Buracos: local sem atributo herda o municipio; renda/raca ausentes herdam o municipio.
Secoes do exterior (ZZ) ficam fora -- nao ha Censo para elas.

Saida: sintetico/base_2022.parquet.

Uso:  .venv/Scripts/python -m sintetico.base
"""
from __future__ import annotations

import sys
import unicodedata

import numpy as np
import pandas as pd

from .caminhos import SAIDA, UF_REGIAO

HIERARQUIA = {"metropole": 5, "capital regional": 4, "centro sub-regional": 3,
              "centro de zona": 2, "centro local": 1}


def main() -> int:
    alvo = pd.read_parquet(SAIDA / "alvo_2022_t2.parquet")
    alvo["cd_municipio_tse"] = alvo["cd_municipio"].astype(int)
    alvo = alvo.drop(columns=["cd_municipio"])
    n0 = len(alvo)
    alvo = alvo[alvo["uf"] != "ZZ"].copy()
    print(f"alvo: {n0} secoes, {n0 - len(alvo)} do exterior descartadas")

    perfil = pd.read_parquet(SAIDA / "perfil_secao_2022.parquet")
    base = alvo.merge(perfil, on=["uf", "cd_municipio_tse", "zona", "secao"], how="left")
    print(f"sem perfil TSE: {base['pct_fem'].isna().sum()}")

    locais = pd.read_parquet(SAIDA / "locais_atributos_2022.parquet")
    locais = locais.drop(columns=["pop_entorno", "origem"])
    base = base.merge(locais, on=["uf", "cd_municipio_tse", "zona", "nr_local"], how="left")
    print(f"sem atributo de local: {base['renda_mediana'].isna().sum()}")

    mun_attr = pd.read_parquet(SAIDA / "municipio_atributos_2022.parquet")
    mun_attr = mun_attr.rename(columns={c: f"mun_{c}" for c in
                                        ["pct_branca", "pct_preta", "pct_parda",
                                         "renda_mediana", "pct_rural"]})
    mun_attr["mun_pop"] = mun_attr["pop_entorno"]
    mun_attr = mun_attr.drop(columns=["pop_entorno"]).dropna(subset=["cd_municipio_tse"])
    mun_attr["cd_municipio_tse"] = mun_attr["cd_municipio_tse"].astype(int)
    base = base.merge(mun_attr.drop(columns=["cd_mun"]), on="cd_municipio_tse", how="left")

    municip = pd.read_parquet(SAIDA / "municipios_2022.parquet")
    liga = pd.read_parquet(SAIDA / "municipio_atributos_2022.parquet",
                           columns=["cd_mun", "cd_municipio_tse"]).dropna()
    liga["cd_municipio_tse"] = liga["cd_municipio_tse"].astype(int)
    municip = municip.merge(liga, on="cd_mun", how="inner")
    base = base.merge(municip.drop(columns=["cd_mun"]), on="cd_municipio_tse", how="left")
    print(f"sem religiao municipal: {base['pct_evangelica'].isna().sum()}")

    # buracos de local herdam o municipio
    for c in ["pct_branca", "pct_preta", "pct_parda", "renda_mediana", "pct_rural"]:
        base[c] = base[c].fillna(base[f"mun_{c}"])
        base = base.drop(columns=[f"mun_{c}"])

    base["regiao"] = base["uf"].map(UF_REGIAO)
    hier_norm = (base["hierarquia"].astype(str).str.lower()
                 .map(lambda s: "".join(c for c in unicodedata.normalize("NFD", s)
                                        if not unicodedata.combining(c))))
    base["hierarquia_num"] = hier_norm.map(HIERARQUIA)
    base["log_renda"] = np.log(base["renda_mediana"].clip(lower=100))
    base["log_pop_mun"] = np.log(base["mun_pop"].clip(lower=100))

    completa = base.dropna(subset=["sh_lula", "pct_fem", "pct_sup", "renda_mediana",
                                   "pct_branca", "pct_evangelica", "vab_agro",
                                   "pct_ocup_agro", "pct_rural"])
    print(f"base final: {len(completa)} de {len(base)} secoes "
          f"({100 * len(completa) / len(base):.2f}%), "
          f"{completa['aptos'].sum():,} aptos")

    completa.to_parquet(SAIDA / "base_2022.parquet", index=False)
    print(f"gravado {SAIDA / 'base_2022.parquet'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
