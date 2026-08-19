"""Compila o baseline presidencial POR SECAO a partir dos dados abertos.

Saida: um parquet por ano com uma linha por secao eleitoral e as colunas de voto que o
modelo da noite usa como ancora. O eixo esquerda-direita sai do 2o turno, que e a medida
mais limpa que existe (duas vias, sem ruido de fragmentacao).

O arquivo BR e o unico que traz PRESIDENTE por secao -- os arquivos por UF cobrem so os
cargos estaduais. Streaming direto do zip: nada e extraido para disco.

Uso:  .venv/Scripts/python -m pipeline.baseline_presidente [2022|2018]
"""
from __future__ import annotations

import csv
import io
import sys
import time
import zipfile
from pathlib import Path

import pandas as pd

BRUTO = Path(r"D:\Claude\eleicoes-dados\raw\dadosabertos")
SAIDA = Path(r"D:\Claude\eleicoes-dados\baseline")

# quem e "esquerda" e "direita" em cada ciclo, pelo numero na urna
EIXO = {2022: {"esq": "13", "dir": "22"},   # Lula x Bolsonaro
        2018: {"esq": "13", "dir": "17"}}   # Haddad x Bolsonaro
BRANCO, NULO = "95", "96"
COLS = ["t1_esq", "t1_dir", "t1_outros", "t1_branco", "t1_nulo",
        "t2_esq", "t2_dir", "t2_branco", "t2_nulo"]


def compila(ano: int) -> Path:
    codes = EIXO[ano]
    z = zipfile.ZipFile(BRUTO / str(ano) / f"votacao_secao_{ano}_BR.zip")
    nome = f"votacao_secao_{ano}_BR.csv"
    acc: dict[tuple, list[int]] = {}
    t0, n = time.time(), 0

    with z.open(nome) as fh:
        rd = csv.DictReader(io.TextIOWrapper(fh, encoding="latin-1"), delimiter=";")
        for r in rd:
            # 2018 grava "Presidente", 2022 grava "PRESIDENTE" -- comparar sem caixa
            if r["DS_CARGO"].upper() != "PRESIDENTE":
                continue
            chave = (r["SG_UF"], r["CD_MUNICIPIO"], int(r["NR_ZONA"]), int(r["NR_SECAO"]))
            linha = acc.get(chave)
            if linha is None:
                linha = acc[chave] = [0] * len(COLS)
            v, nr, t = int(r["QT_VOTOS"]), r["NR_VOTAVEL"], r["NR_TURNO"]
            if t == "1":
                if nr == codes["esq"]:   linha[0] += v
                elif nr == codes["dir"]: linha[1] += v
                elif nr == BRANCO:       linha[3] += v
                elif nr == NULO:         linha[4] += v
                else:                    linha[2] += v
            elif t == "2":
                if nr == codes["esq"]:   linha[5] += v
                elif nr == codes["dir"]: linha[6] += v
                elif nr == BRANCO:       linha[7] += v
                elif nr == NULO:         linha[8] += v
            n += 1
            if n % 2_000_000 == 0:
                print(f"  {n:>12,} linhas  {len(acc):>9,} secoes  {time.time()-t0:5.0f}s", flush=True)

    df = pd.DataFrame(
        [(*k, *v) for k, v in acc.items()],
        columns=["uf", "cd_municipio", "zona", "secao", *COLS],
    )
    # eixo: quanto a secao deu a direita no 2o turno, em votos aos dois concorrentes.
    # E a ancora geografica do modelo -- estavel, sem fragmentacao, comparavel entre ciclos.
    dois = df["t2_esq"] + df["t2_dir"]
    df["eixo_dir_t2"] = (df["t2_dir"] / dois.where(dois > 0)).astype("float32")
    df["validos_t1"] = df["t1_esq"] + df["t1_dir"] + df["t1_outros"]
    df["comparecimento_t1"] = df["validos_t1"] + df["t1_branco"] + df["t1_nulo"]

    SAIDA.mkdir(parents=True, exist_ok=True)
    destino = SAIDA / f"presidente_secao_{ano}.parquet"
    df.to_parquet(destino, index=False, compression="zstd")

    print(f"\n{ano}: {len(df):,} secoes  ->  {destino}  ({destino.stat().st_size/1e6:.1f} MB)")
    print(f"  sem 2o turno (eixo nulo): {df['eixo_dir_t2'].isna().sum():,}")
    dois_br = int(df["t2_esq"].sum() + df["t2_dir"].sum())
    if dois_br:
        print(f"  eixo medio ponderado: {df['t2_dir'].sum()/dois_br:.4f}  (tem que bater com o % oficial do 2o turno)")
    return destino


if __name__ == "__main__":
    for ano in (int(sys.argv[1]),) if len(sys.argv) > 1 else (2022, 2018):
        compila(ano)
