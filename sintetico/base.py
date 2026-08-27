"""Monta a base de modelagem de um ano: uma linha por secao com os 3 shares e as
covariaveis.

Juncoes:
  alvo (shares + nr_local)  x  perfil TSE do ano (sexo/idade/escolaridade da secao)
  x  atributos do local (Voronoi sobre setores; anos antigos ja vem interpolados
     entre Censo 2010 e 2022 pelo geo_backfill)
  x  atributos municipais: religiao interpolada 2010->2022 pelo peso do ano;
     ocupacao/VAB/porte/hierarquia CONGELADOS (decisao do usuario).

Uso:  .venv/Scripts/python -m sintetico.base [2010|2014|2018|2022]
"""
from __future__ import annotations

import sys
import unicodedata

import numpy as np
import pandas as pd

from .caminhos import SAIDA, UF_REGIAO

HIERARQUIA = {"metropole": 5, "capital regional": 4, "centro sub-regional": 3,
              "centro de zona": 2, "centro local": 1}
PESO_CENSO = {2010: 0.0, 2014: 0.354, 2018: 0.688, 2022: 1.0}


def main() -> int:
    ano = int(sys.argv[1]) if len(sys.argv) > 1 else 2022
    w = PESO_CENSO[ano]

    alvo = pd.read_parquet(SAIDA / f"alvo_{ano}_t2.parquet")
    alvo["cd_municipio_tse"] = alvo["cd_municipio"].astype(int)
    alvo = alvo.drop(columns=["cd_municipio"])
    n0 = len(alvo)
    alvo = alvo[alvo["uf"] != "ZZ"].copy()
    print(f"{ano}: {n0} secoes no alvo, {n0 - len(alvo)} do exterior descartadas")

    perfil = pd.read_parquet(SAIDA / f"perfil_secao_{ano}.parquet")
    base = alvo.merge(perfil, on=["uf", "cd_municipio_tse", "zona", "secao"], how="left")
    print(f"sem perfil TSE: {base['pct_fem'].isna().sum()}")

    locais = pd.read_parquet(SAIDA / f"locais_atributos_{ano}.parquet")
    locais = locais.drop(columns=[c for c in ["pop_entorno", "origem", "nm_municipio",
                                              "lat", "lon", "nome_n"] if c in locais.columns])
    base = base.merge(locais, on=["uf", "cd_municipio_tse", "zona", "nr_local"], how="left")
    print(f"sem atributo de local: {base['renda_media'].isna().sum()}")

    mun_attr = pd.read_parquet(SAIDA / f"municipio_atributos_{ano}.parquet")
    mun_attr = mun_attr.rename(columns={c: f"mun_{c}" for c in
                                        ["pct_branca", "pct_preta", "pct_parda",
                                         "renda_media", "pct_rural"]})
    mun_attr["mun_pop"] = mun_attr["pop_entorno"]
    mun_attr = mun_attr.drop(columns=["pop_entorno"]).dropna(subset=["cd_municipio_tse"])
    mun_attr["cd_municipio_tse"] = mun_attr["cd_municipio_tse"].astype(int)
    liga = mun_attr[["cd_mun", "cd_municipio_tse"]].copy()
    base = base.merge(mun_attr.drop(columns=["cd_mun"]), on="cd_municipio_tse", how="left")

    # municipais congelados (VAB, ocupacao, hierarquia, RM) + religiao interpolada
    municip = pd.read_parquet(SAIDA / "municipios_2022.parquet")
    rel10 = pd.read_parquet(SAIDA / "religiao_2010.parquet")
    municip = municip.merge(rel10, on="cd_mun", how="left")
    # evangelica/sem religiao do ano = mistura linear entre os censos
    municip["pct_evangelica"] = ((1 - w) * municip["ev10"] + w * municip["pct_evangelica"]) \
        .fillna(municip["pct_evangelica"]).fillna(municip["ev10"])
    municip["pct_sem_religiao"] = ((1 - w) * municip["sr10"] + w * municip["pct_sem_religiao"]) \
        .fillna(municip["pct_sem_religiao"]).fillna(municip["sr10"])
    municip = municip.drop(columns=["ev10", "sr10"])
    municip = municip.merge(liga, on="cd_mun", how="inner")
    base = base.merge(municip.drop(columns=["cd_mun"]), on="cd_municipio_tse", how="left")
    print(f"sem religiao municipal: {base['pct_evangelica'].isna().sum()}")

    # buracos de local herdam o municipio
    for c in ["pct_branca", "pct_preta", "pct_parda", "renda_media", "pct_rural"]:
        base[c] = base[c].fillna(base[f"mun_{c}"])
        base = base.drop(columns=[f"mun_{c}"])

    base["regiao"] = base["uf"].map(UF_REGIAO)
    hier_norm = (base["hierarquia"].fillna("").astype(str).str.lower()
                 .map(lambda s: "".join(c for c in unicodedata.normalize("NFD", s)
                                        if not unicodedata.combining(c))))
    base["hierarquia_num"] = hier_norm.map(HIERARQUIA)
    base["log_renda"] = np.log(pd.to_numeric(base["renda_media"], errors="coerce").clip(lower=100))
    base["log_pop_mun"] = np.log(base["mun_pop"].clip(lower=100))

    completa = base.dropna(subset=["sh_lula", "pct_fem", "pct_sup", "renda_media",
                                   "pct_branca", "pct_evangelica", "vab_agro",
                                   "pct_ocup_agro", "pct_rural"])
    print(f"base final: {len(completa)} de {len(base)} secoes "
          f"({100 * len(completa) / len(base):.2f}%), "
          f"{completa['aptos'].sum():,} aptos")

    completa.to_parquet(SAIDA / f"base_{ano}.parquet", index=False)
    print(f"gravado {SAIDA / f'base_{ano}.parquet'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
