"""Vinculo geografico: cada setor censitario e atribuido ao local de votacao mais
proximo do MESMO municipio (particao de Voronoi sobre os centroides), e cada local
herda a demografia agregada dos setores da sua celula (ponderada por populacao).

Pontes:
- TSE->IBGE de municipio por nome normalizado (UF + nome sem acento); sobras via
  difflib. Reportado no log.
- Local sem coordenada (7,3% em 2022) ou com coordenada a mais de 30 km do setor
  mais proximo do municipio: cai no agregado municipal (fallback).

Saidas: sintetico/locais_atributos_2022.parquet (uma linha por local) e
        sintetico/municipio_atributos_2022.parquet (fallback + crosswalk).

Uso:  .venv/Scripts/python -m sintetico.geo
"""
from __future__ import annotations

import csv
import difflib
import io
import sys
import unicodedata
import zipfile

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

from .caminhos import BRUTO_TSE, SAIDA


def norm_nome(s) -> str:
    s = unicodedata.normalize("NFD", str(s) if s is not None else "").encode("ascii", "ignore").decode()
    return " ".join(s.upper().replace("-", " ").replace("'", "").split())


def carrega_locais() -> pd.DataFrame:
    z = zipfile.ZipFile(BRUTO_TSE / "2022" / "eleitorado_local_votacao_2022.zip")
    vistos = {}
    with z.open("eleitorado_local_votacao_2022.csv") as fh:
        rd = csv.DictReader(io.TextIOWrapper(fh, encoding="latin-1"), delimiter=";")
        for r in rd:
            if r["NR_TURNO"] != "2":
                continue
            k = (r["SG_UF"], int(r["CD_MUNICIPIO"]), int(r["NR_ZONA"]), int(r["NR_LOCAL_VOTACAO"]))
            if k in vistos:
                continue
            lat, lon = float(r["NR_LATITUDE"]), float(r["NR_LONGITUDE"])
            if lat == -1 or lon == -1 or lat < -35 or lat > 6 or lon < -75 or lon > -32:
                lat = lon = np.nan
            vistos[k] = (lat, lon, r["NM_MUNICIPIO"])
    df = pd.DataFrame([(k[0], k[1], k[2], k[3], *v) for k, v in vistos.items()],
                      columns=["uf", "cd_municipio_tse", "zona", "nr_local",
                               "lat", "lon", "nm_municipio"])
    return df


def crosswalk(locais: pd.DataFrame, setores: pd.DataFrame) -> pd.DataFrame:
    uf_por_cod = {"11": "RO", "12": "AC", "13": "AM", "14": "RR", "15": "PA", "16": "AP",
                  "17": "TO", "21": "MA", "22": "PI", "23": "CE", "24": "RN", "25": "PB",
                  "26": "PE", "27": "AL", "28": "SE", "29": "BA", "31": "MG", "32": "ES",
                  "33": "RJ", "35": "SP", "41": "PR", "42": "SC", "43": "RS", "50": "MS",
                  "51": "MT", "52": "GO", "53": "DF"}
    ibge = setores[["cd_mun", "nm_mun", "cd_uf"]].drop_duplicates("cd_mun").copy()
    ibge["uf"] = ibge["cd_uf"].astype(str).map(uf_por_cod)
    ibge["nome_n"] = ibge["nm_mun"].map(norm_nome)

    tse = locais[["uf", "cd_municipio_tse", "nm_municipio"]].drop_duplicates("cd_municipio_tse").copy()
    tse["nome_n"] = tse["nm_municipio"].map(norm_nome)

    # nomes TSE que nao sao grafia do IBGE (renomeacoes historicas)
    apelidos = {("RN", "ASSU"): "ACU", ("RN", "BOA SAUDE"): "JANUARIO CICCO"}
    tse["nome_n"] = tse.apply(lambda r: apelidos.get((r["uf"], r["nome_n"]), r["nome_n"]), axis=1)

    liga = tse.merge(ibge[["uf", "nome_n", "cd_mun"]], on=["uf", "nome_n"], how="left")
    pend = liga["cd_mun"].isna()
    if pend.any():
        for i in liga.index[pend]:
            uf, nome = liga.at[i, "uf"], liga.at[i, "nome_n"]
            cands = ibge[ibge["uf"] == uf]
            prox = difflib.get_close_matches(nome, cands["nome_n"].tolist(), n=1, cutoff=0.75)
            if prox:
                liga.at[i, "cd_mun"] = cands.loc[cands["nome_n"] == prox[0], "cd_mun"].iloc[0]
                print(f"  fuzzy: {uf} {nome} -> {prox[0]}")
    print(f"crosswalk: {len(liga)} municipios TSE, sem par: {liga['cd_mun'].isna().sum()}")
    return liga[["cd_municipio_tse", "cd_mun"]].dropna()


def pondera(setores: pd.DataFrame) -> dict:
    """Agregados demograficos de um conjunto de setores (ponderacao por populacao)."""
    pop = setores["pop"].sum()
    rv = setores["raca_val"].sum()
    resp = setores["responsaveis"].sum()

    def wmean(col, w):
        s = setores.dropna(subset=[col])
        den = s[w].sum()
        return float((s[col] * s[w]).sum() / den) if den > 0 else np.nan

    return {"pop_entorno": int(pop),
            "pct_branca": wmean("pct_branca", "raca_val") if rv else np.nan,
            "pct_preta": wmean("pct_preta", "raca_val") if rv else np.nan,
            "pct_parda": wmean("pct_parda", "raca_val") if rv else np.nan,
            "renda_mediana": wmean("renda_mediana", "responsaveis") if resp else np.nan,
            "pct_rural": float(setores.loc[setores["rural"] == 1, "pop"].sum() / pop) if pop else np.nan}


def main() -> int:
    setores = pd.read_parquet(SAIDA / "setores_2022.parquet")
    cent = pd.read_parquet(SAIDA / "setor_centroides_2022.parquet")
    setores = setores.merge(cent, on="cd_setor", how="left")
    setores["responsaveis"] = pd.to_numeric(setores["responsaveis"], errors="coerce").fillna(0)

    locais = carrega_locais()
    liga = crosswalk(locais, setores)
    locais = locais.merge(liga, on="cd_municipio_tse", how="left")

    # fallback municipal (e atributo do municipio para a base)
    mun_rows = []
    for cd_mun, grupo in setores.groupby("cd_mun"):
        mun_rows.append({"cd_mun": cd_mun, **pondera(grupo)})
    mun_df = pd.DataFrame(mun_rows)

    out = []
    n_fallback = n_longe = 0
    for cd_mun, grp_loc in locais.groupby("cd_mun"):
        st = setores[setores["cd_mun"] == cd_mun]
        st = st.dropna(subset=["lon", "lat"])
        com_coord = grp_loc.dropna(subset=["lat", "lon"])
        atribuidos = {}
        if len(st) and len(com_coord):
            lat0 = np.cos(np.radians(st["lat"].mean()))
            arv_loc = cKDTree(np.c_[com_coord["lon"] * lat0, com_coord["lat"]])
            _, idx = arv_loc.query(np.c_[st["lon"] * lat0, st["lat"]])
            st = st.assign(_i=idx)
            # coordenada de local a mais de ~30 km do setor mais proximo = geocodificacao ruim
            arv_st = cKDTree(np.c_[st["lon"] * lat0, st["lat"]])
            d_loc, _ = arv_st.query(np.c_[com_coord["lon"] * lat0, com_coord["lat"]])
            ruim = d_loc * 111.0 > 30.0
            for j, (i_loc, linha) in enumerate(com_coord.iterrows()):
                if ruim[j]:
                    n_longe += 1
                    continue
                celula = st[st["_i"] == j]
                if not len(celula):
                    _, viz = arv_st.query([com_coord.iloc[j]["lon"] * lat0, com_coord.iloc[j]["lat"]])
                    celula = st.iloc[[viz]]
                atribuidos[i_loc] = pondera(celula)
        base_mun = mun_df[mun_df["cd_mun"] == cd_mun]
        fb = base_mun.iloc[0].to_dict() if len(base_mun) else {}
        for i_loc, linha in grp_loc.iterrows():
            attrs = atribuidos.get(i_loc)
            if attrs is None:
                n_fallback += 1
                attrs = {k: fb.get(k, np.nan) for k in
                         ["pop_entorno", "pct_branca", "pct_preta", "pct_parda",
                          "renda_mediana", "pct_rural"]}
                attrs["origem"] = "municipio"
            else:
                attrs["origem"] = "voronoi"
            out.append({"uf": linha["uf"], "cd_municipio_tse": linha["cd_municipio_tse"],
                        "zona": linha["zona"], "nr_local": linha["nr_local"],
                        "cd_mun": cd_mun, **attrs})

    df = pd.DataFrame(out)
    print(f"locais atribuidos: {len(df)} | fallback municipal: {n_fallback} "
          f"| coordenada descartada (>30km): {n_longe}")
    print(f"cobertura voronoi: {100 * (df['origem'] == 'voronoi').mean():.1f}% dos locais")

    df.to_parquet(SAIDA / "locais_atributos_2022.parquet", index=False)
    mun_df = mun_df.merge(liga, on="cd_mun", how="left")
    mun_df.to_parquet(SAIDA / "municipio_atributos_2022.parquet", index=False)
    print("gravados locais_atributos_2022.parquet e municipio_atributos_2022.parquet")
    return 0


if __name__ == "__main__":
    sys.exit(main())
