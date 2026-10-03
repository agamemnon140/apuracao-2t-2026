"""Universo de 2026: toda secao, local de votacao e municipio que vai a urna em 04/10/2026.

Fonte: eleitorado_local_votacao_2026 (dados abertos TSE, 1o turno). Inclui o exterior (ZZ),
que so vota para presidente. Secoes agregadas continuam listadas, com `secao_principal`
apontando para a urna onde os votos serao somados.

Saidas (SAIDA = eleicoes-dados/sintetico):
  universo_2026.parquet    uf, cd_mun, nm_municipio, zona, secao, nr_local, nm_local, bairro,
                           lat, lon, aptos (federal), aptos_est, secao_principal (-1 = propria)
  locais_2026.parquet      uf, cd_mun, zona, nr_local, nm_local, bairro, lat, lon, aptos, n_secoes
  municipios_2026.parquet  uf, cd_mun, nm_municipio, cd_ibge, aptos, n_zonas, n_locais, n_secoes

Uso:  .venv/Scripts/python -m sintetico.universo_2026
"""
from __future__ import annotations

import sys
import zipfile

import numpy as np
import pandas as pd

from .caminhos import BRUTO_TSE, SAIDA

COLS = {"SG_UF": "uf", "CD_MUNICIPIO": "cd_mun", "NM_MUNICIPIO": "nm_municipio",
        "NR_ZONA": "zona", "NR_SECAO": "secao", "NR_LOCAL_VOTACAO": "nr_local",
        "NM_LOCAL_VOTACAO": "nm_local", "NM_BAIRRO": "bairro",
        "NR_LATITUDE": "lat", "NR_LONGITUDE": "lon",
        "QT_ELEITOR_ELEICAO_FEDERAL": "aptos", "QT_ELEITOR_ELEICAO_ESTADUAL": "aptos_est",
        "NR_SECAO_PRINCIPAL": "secao_principal", "NR_TURNO": "turno"}


def le_universo(ano: int = 2026) -> pd.DataFrame:
    z = zipfile.ZipFile(BRUTO_TSE / str(ano) / f"eleitorado_local_votacao_{ano}.zip")
    csvs = [n for n in z.namelist() if n.lower().endswith(".csv")]
    nome = next((n for n in csvs if n.endswith("_BRASIL.csv")), csvs[0])
    with z.open(nome) as fh:
        df = pd.read_csv(fh, sep=";", encoding="latin-1", usecols=lambda c: c in COLS, dtype=str)
    df = df.rename(columns=COLS)
    if "aptos" not in df:                        # 2022 nao separa federal/estadual
        with z.open(nome) as fh:
            q = pd.read_csv(fh, sep=";", encoding="latin-1", usecols=["QT_ELEITOR"], dtype=str)
        df["aptos"] = df["aptos_est"] = q["QT_ELEITOR"].to_numpy()
    df = df[df["turno"] == "1"].drop(columns="turno")
    for c in ["cd_mun", "zona", "secao", "nr_local", "aptos", "aptos_est", "secao_principal"]:
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(-1).astype(np.int64)
    for c in ["lat", "lon"]:
        df[c] = pd.to_numeric(df[c].str.replace(",", "."), errors="coerce")
    fora = ((df["lat"] == -1) | (df["lon"] == -1) | (df["lat"] < -35) | (df["lat"] > 6)
            | (df["lon"] < -75) | (df["lon"] > -32))
    df.loc[fora & (df["uf"] != "ZZ"), ["lat", "lon"]] = np.nan
    df.loc[df["uf"] == "ZZ", ["lat", "lon"]] = np.nan
    df = df.drop_duplicates(["uf", "cd_mun", "zona", "secao"])
    return df.sort_values(["uf", "cd_mun", "zona", "secao"]).reset_index(drop=True)


def main() -> int:
    u = le_universo()
    u.to_parquet(SAIDA / "universo_2026.parquet", index=False)

    loc = (u.groupby(["uf", "cd_mun", "zona", "nr_local"], as_index=False)
           .agg(nm_local=("nm_local", "first"), bairro=("bairro", "first"),
                lat=("lat", "first"), lon=("lon", "first"),
                aptos=("aptos", "sum"), n_secoes=("secao", "size")))
    loc.to_parquet(SAIDA / "locais_2026.parquet", index=False)

    ibge = pd.read_parquet(SAIDA / "municipio_atributos_2022.parquet",
                           columns=["cd_mun", "cd_municipio_tse"]).dropna()
    ibge = dict(zip(ibge["cd_municipio_tse"].astype(int), ibge["cd_mun"]))
    mun = (u.groupby(["uf", "cd_mun"], as_index=False)
           .agg(nm_municipio=("nm_municipio", "first"), aptos=("aptos", "sum"),
                n_zonas=("zona", "nunique"), n_secoes=("secao", "size")))
    mun["n_locais"] = mun["cd_mun"].map(loc.groupby("cd_mun").size())
    mun["cd_ibge"] = mun["cd_mun"].map(ibge)
    mun.to_parquet(SAIDA / "municipios_2026.parquet", index=False)

    # comparacao com 2022: quantas secoes 2026 tem par exato (uf, mun, zona, secao)
    a22 = pd.read_parquet(SAIDA / "alvo_2022_t2.parquet", columns=["uf", "cd_municipio", "zona", "secao"])
    a22["cd_mun"] = a22["cd_municipio"].astype(int)
    par = u.merge(a22[["uf", "cd_mun", "zona", "secao"]].assign(par=1),
                  on=["uf", "cd_mun", "zona", "secao"], how="left")["par"].notna()
    loc22 = pd.read_parquet(SAIDA / "alvo_2022_t2.parquet", columns=["uf", "cd_municipio", "zona", "nr_local"])
    loc22 = set(zip(loc22["cd_municipio"].astype(int), loc22["zona"], loc22["nr_local"]))
    par_loc = pd.Series([k in loc22 for k in zip(u["cd_mun"], u["zona"], u["nr_local"])])

    print(f"secoes 2026: {len(u):,}  aptos federal {u['aptos'].sum():,}  estadual {u['aptos_est'].sum():,}")
    print(f"locais: {len(loc):,}  municipios: {len(mun):,} ({mun['cd_ibge'].isna().sum()} sem IBGE, "
          f"ZZ={int((mun['uf'] == 'ZZ').sum())})")
    print(f"agregadas: {(u['secao_principal'] > 0).sum():,}  sem coordenada (fora ZZ): "
          f"{u.loc[u['uf'] != 'ZZ', 'lat'].isna().sum():,}")
    print(f"com par 2022 (secao): {par.mean():.1%} das secoes, "
          f"{u.loc[par.values, 'aptos'].sum() / u['aptos'].sum():.1%} dos aptos; "
          f"local existente em 2022: {par_loc.mean():.1%}")
    t = u.assign(par=par.values).groupby("uf").agg(sec=("secao", "size"), par=("par", "mean"))
    print(t.assign(par=lambda d: (100 * d["par"]).round(1)).T.to_string())
    return 0


if __name__ == "__main__":
    sys.exit(main())
