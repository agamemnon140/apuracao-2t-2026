"""Compila as covariaveis municipais: religiao (Censo 2022), ocupacao por atividade
(Censo 2010 -- o 2022 nao divulgou atividade por municipio ate ago/2026), VAB do PIB
Municipal 2021, hierarquia urbana e regiao metropolitana.

Saida: sintetico/municipios_2022.parquet, chave cd_mun (7 digitos IBGE).

Uso:  .venv/Scripts/python -m sintetico.municipais
"""
from __future__ import annotations

import json
import sys
import urllib.request
import zipfile

import pandas as pd

from .caminhos import BRUTO_IBGE, SAIDA


def sidra(url: str) -> list[dict]:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.load(r)


def religiao() -> pd.DataFrame:
    # t9537: pessoas 10+ por religiao; sexo=total (6794), idade=total (95253)
    dados = sidra("https://apisidra.ibge.gov.br/values/t/9537/n6/all/v/140/p/2022"
                  "/c133/95278,95263,95277,2836/c2/6794/c58/95253?formato=json")
    hdr, linhas = dados[0], dados[1:]
    df = pd.DataFrame(linhas)
    df = df.rename(columns={"D1C": "cd_mun", "D4C": "cat", "V": "valor"})
    df["valor"] = pd.to_numeric(df["valor"], errors="coerce")
    largo = df.pivot_table(index="cd_mun", columns="cat", values="valor", aggfunc="first")
    largo = largo.rename(columns={"95278": "rel_total", "95263": "catolica",
                                  "95277": "evangelica", "2836": "sem_religiao"})
    den = largo["rel_total"].where(largo["rel_total"] > 0)
    out = pd.DataFrame({"cd_mun": largo.index.astype(str),
                        "pct_catolica": (largo["catolica"] / den).values,
                        "pct_evangelica": (largo["evangelica"] / den).values,
                        "pct_sem_religiao": (largo["sem_religiao"] / den).values})
    return out


def ocupacao_2010() -> pd.DataFrame:
    cats = {"0": "total", "12640": "agro", "12641": "bens", "12642": "bens",
            "12643": "bens", "12644": "bens", "95377": "bens", "12645": "comercio"}
    dados = sidra("https://apisidra.ibge.gov.br/values/t/1575/n6/all/v/696/p/2010"
                  "/c11805/" + ",".join(cats) + "?formato=json")
    df = pd.DataFrame(dados[1:])
    df = df.rename(columns={"D1C": "cd_mun", "D4C": "cat", "V": "valor"})
    df["grupo"] = df["cat"].map(cats)
    df["valor"] = pd.to_numeric(df["valor"], errors="coerce").fillna(0)
    largo = df.pivot_table(index="cd_mun", columns="grupo", values="valor", aggfunc="sum")
    den = largo["total"].where(largo["total"] > 0)
    out = pd.DataFrame({"cd_mun": largo.index.astype(str),
                        "pct_ocup_agro": (largo["agro"] / den).values,
                        "pct_ocup_bens": (largo["bens"] / den).values,
                        "pct_ocup_comercio": (largo["comercio"] / den).values})
    return out


def pib_2021() -> pd.DataFrame:
    z = zipfile.ZipFile(BRUTO_IBGE / "pib_municipios_2010_2021_xlsx.zip")
    with z.open(z.namelist()[0]) as fh:
        df = pd.read_excel(fh)
    df = df[df["Ano"] == 2021].copy()
    col = {c: c for c in df.columns}
    vab_agro = [c for c in df.columns if c.startswith("Valor adicionado bruto da Agropecu")][0]
    vab_ind = [c for c in df.columns if c.startswith("Valor adicionado bruto da Ind")][0]
    vab_serv = [c for c in df.columns if c.startswith("Valor adicionado bruto dos Servi")][0]
    vab_adm = [c for c in df.columns if c.startswith("Valor adicionado bruto da Administra")][0]
    vab_tot = [c for c in df.columns if c.startswith("Valor adicionado bruto total")][0]
    hier = [c for c in df.columns if c.startswith("Hierarquia Urbana (principais")][0]
    rm = [c for c in df.columns if c.startswith("Regi") and "Metropolitana" in c][0]
    den = df[vab_tot].where(df[vab_tot] > 0)
    out = pd.DataFrame({
        "cd_mun": df["Código do Município"].astype(str),
        "vab_agro": df[vab_agro] / den,
        "vab_industria": df[vab_ind] / den,
        "vab_servicos": df[vab_serv] / den,
        "vab_adm": df[vab_adm] / den,
        "hierarquia": df[hier].astype(str),
        "em_rm": (~df[rm].isna() & (df[rm].astype(str).str.strip() != "")).astype(int),
    })
    return out


def main() -> int:
    rel = religiao()
    print(f"religiao: {len(rel)} municipios, evangelica media "
          f"{100 * rel['pct_evangelica'].mean():.1f}%")
    ocu = ocupacao_2010()
    print(f"ocupacao 2010: {len(ocu)} municipios")
    pib = pib_2021()
    print(f"pib 2021: {len(pib)} municipios")

    df = pib.merge(rel, on="cd_mun", how="outer").merge(ocu, on="cd_mun", how="outer")
    print(f"unidos: {len(df)} | sem religiao: {df['pct_evangelica'].isna().sum()} | "
          f"sem pib: {df['vab_agro'].isna().sum()} | sem ocupacao: {df['pct_ocup_agro'].isna().sum()}")
    destino = SAIDA / "municipios_2022.parquet"
    df.to_parquet(destino, index=False)
    print(f"gravado {destino}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
