"""Compila o lado IBGE por setor censitario: populacao, situacao urbana/rural,
cor/raca e renda do responsavel (mediana e media).

Saida: sintetico/setores_2022.parquet -- uma linha por setor com CD_MUN (7 digitos IBGE).

Os CSVs usam ';' e virgula decimal; renda 'X' significa valor omitido por sigilo.

Uso:  .venv/Scripts/python -m sintetico.censo
"""
from __future__ import annotations

import sys
import zipfile

import pandas as pd

from .caminhos import BRUTO_IBGE, SAIDA


def le(nome_zip: str, usecols, dtype=None) -> pd.DataFrame:
    z = zipfile.ZipFile(BRUTO_IBGE / nome_zip)
    csv_nome = [n for n in z.namelist() if n.endswith(".csv")][0]
    with z.open(csv_nome) as fh:
        df = pd.read_csv(fh, sep=";", usecols=usecols, dtype=dtype,
                         na_values=["X", "..", "-"], encoding="latin-1")
    df.columns = [c.upper() for c in df.columns]
    return df


def main() -> int:
    basico = le("Agregados_por_setores_basico_BR.zip",
                ["CD_SETOR", "SITUACAO", "CD_MUN", "NM_MUN", "CD_UF", "AREA_KM2", "v0001"],
                dtype={"CD_SETOR": str, "CD_MUN": str})
    basico = basico.rename(columns={"V0001": "pop"})
    basico["pop"] = pd.to_numeric(basico["pop"], errors="coerce").fillna(0).astype(int)

    raca = le("Agregados_por_setores_cor_ou_raca_BR.zip",
              ["CD_SETOR", "V01317", "V01318", "V01319", "V01320", "V01321"],
              dtype={"CD_SETOR": str})
    for c in ["V01317", "V01318", "V01319", "V01320", "V01321"]:
        raca[c] = pd.to_numeric(raca[c], errors="coerce").fillna(0)
    raca["raca_val"] = raca[["V01317", "V01318", "V01319", "V01320", "V01321"]].sum(axis=1)
    den = raca["raca_val"].where(raca["raca_val"] > 0)
    raca["pct_branca"] = raca["V01317"] / den
    raca["pct_preta"] = raca["V01318"] / den
    raca["pct_parda"] = raca["V01320"] / den
    raca["pct_indigena"] = raca["V01321"] / den
    raca = raca[["CD_SETOR", "pct_branca", "pct_preta", "pct_parda", "pct_indigena", "raca_val"]]

    renda = le("Agregados_por_setores_renda_responsavel_BR.zip",
               ["CD_SETOR", "V06001", "V06004", "V06006"], dtype={"CD_SETOR": str})
    renda = renda.rename(columns={"V06001": "responsaveis", "V06004": "renda_media",
                                  "V06006": "renda_mediana"})
    for c in ["responsaveis", "renda_media", "renda_mediana"]:
        renda[c] = pd.to_numeric(renda[c], errors="coerce")

    df = basico.merge(raca, on="CD_SETOR", how="left").merge(renda, on="CD_SETOR", how="left")
    df["rural"] = (df["SITUACAO"].str.strip().str.lower() == "rural").astype(int)
    df = df.rename(columns={"CD_SETOR": "cd_setor", "CD_MUN": "cd_mun", "NM_MUN": "nm_mun",
                            "CD_UF": "cd_uf", "AREA_KM2": "area_km2"})
    df = df.drop(columns=["SITUACAO"])

    print(f"setores: {len(df)} | pop total: {df['pop'].sum():,}")
    print(f"sem renda mediana: {df['renda_mediana'].isna().sum()} "
          f"({100 * df['renda_mediana'].isna().mean():.1f}%)")
    print(f"pct rural (setores): {100 * df['rural'].mean():.1f}% | "
          f"pop rural: {100 * df.loc[df['rural'] == 1, 'pop'].sum() / df['pop'].sum():.1f}%")

    SAIDA.mkdir(parents=True, exist_ok=True)
    destino = SAIDA / "setores_2022.parquet"
    df.to_parquet(destino, index=False)
    print(f"gravado {destino}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
