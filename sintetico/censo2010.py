"""Compila o lado IBGE do Censo 2010 por setor: populacao, situacao, cor/raca e
renda media do responsavel (V005 do Basico; 2010 nao publica mediana por setor).

Os CSVs de 2010 sao latin-1, ';' e decimal VIRGULA (diferente de 2022).
SP vem partido em dois zips (Capital / Exceto_Capital).

Saida: sintetico/setores_2010.parquet -- mesmo contrato de setores_2022.parquet
(renda_media no lugar de renda_mediana; cd_mun 7 digitos).

Uso:  .venv/Scripts/python -m sintetico.censo2010
"""
from __future__ import annotations

import io
import sys
import zipfile

import pandas as pd

from .caminhos import BRUTO_IBGE, SAIDA

PARTES = ["AC", "AL", "AM", "AP", "BA", "CE", "DF", "ES", "GO", "MA", "MG", "MS",
          "MT", "PA", "PB", "PE", "PI", "PR", "RJ", "RN", "RO", "RR", "RS", "SC",
          "SE", "TO", "SP_Capital", "SP_Exceto_Capital"]


def le_csv(z: zipfile.ZipFile, marca: str, usecols) -> pd.DataFrame:
    nome = [n for n in z.namelist()
            if f"csv/{marca.lower()}" in n.lower() and n.lower().endswith(".csv")]
    if not nome:
        raise FileNotFoundError(marca)
    with z.open(nome[0]) as fh:
        df = pd.read_csv(io.TextIOWrapper(fh, encoding="latin-1"), sep=";",
                         usecols=usecols, dtype=str)
    return df


def num(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s.str.replace(",", ".", regex=False), errors="coerce")


def main() -> int:
    partes = []
    for p in PARTES:
        z = zipfile.ZipFile(BRUTO_IBGE / "censo2010" / f"agregados_{p}.zip")
        bas = le_csv(z, "Basico", ["Cod_setor", "Cod_municipio", "Nome_do_municipio",
                                   "Cod_UF", "Situacao_setor", "V001", "V002", "V005"])
        pes = le_csv(z, "Pessoa03", ["Cod_setor", "V001", "V002", "V003", "V004",
                                     "V005", "V006"])
        pes.columns = ["Cod_setor", "p_total", "p_branca", "p_preta", "p_amarela",
                       "p_parda", "p_indigena"]
        df = bas.merge(pes, on="Cod_setor", how="left")
        partes.append(df)
        print(f"{p}: {len(df)} setores", flush=True)

    df = pd.concat(partes, ignore_index=True)
    for c in ["p_total", "p_branca", "p_preta", "p_amarela", "p_parda", "p_indigena"]:
        df[c] = num(df[c]).fillna(0)
    df["raca_val"] = df[["p_branca", "p_preta", "p_amarela", "p_parda", "p_indigena"]].sum(axis=1)
    den = df["raca_val"].where(df["raca_val"] > 0)
    out = pd.DataFrame({
        "cd_setor": df["Cod_setor"],
        "cd_mun": df["Cod_municipio"],
        "nm_mun": df["Nome_do_municipio"],
        "cd_uf": pd.to_numeric(df["Cod_UF"], errors="coerce").astype("Int64"),
        "pop": num(df["V002"]).fillna(0).astype(int),
        "pct_branca": df["p_branca"] / den,
        "pct_preta": df["p_preta"] / den,
        "pct_parda": df["p_parda"] / den,
        "pct_indigena": df["p_indigena"] / den,
        "raca_val": df["raca_val"],
        "responsaveis": num(df["V001"]).fillna(0),
        "renda_media": num(df["V005"]),
        "rural": (pd.to_numeric(df["Situacao_setor"], errors="coerce") >= 4).astype(int),
    })
    print(f"setores 2010: {len(out)} | pop: {out['pop'].sum():,} | "
          f"sem renda: {100 * out['renda_media'].isna().mean():.1f}% | "
          f"pop rural: {100 * out.loc[out['rural'] == 1, 'pop'].sum() / out['pop'].sum():.1f}%")
    out.to_parquet(SAIDA / "setores_2010.parquet", index=False)
    print(f"gravado {SAIDA / 'setores_2010.parquet'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
