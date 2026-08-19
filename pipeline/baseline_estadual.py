"""Compila o voto POR SECAO de um cargo estadual (governador ou senador).

Diferente do presidente, que so existe no arquivo BR, os cargos estaduais estao nos
arquivos por UF. Saida em formato longo (uma linha por secao x candidato), que e o que o
modelo estadual consome: la cada candidato tem sua propria relacao com a geografia.

Brancos (95) e nulos (96) sao guardados a parte, como total da secao -- entram no
denominador de comparecimento, nunca em voto valido.

Uso:  .venv/Scripts/python -m pipeline.baseline_estadual [2022] [GOVERNADOR] [turno]
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
UFS = ["AC", "AL", "AM", "AP", "BA", "CE", "DF", "ES", "GO", "MA", "MG", "MS", "MT", "PA",
       "PB", "PE", "PI", "PR", "RJ", "RN", "RO", "RR", "RS", "SC", "SE", "SP", "TO"]
NAO_CANDIDATO = {"95", "96"}   # branco, nulo


def compila(ano: int, cargo: str = "GOVERNADOR", turno: str = "1") -> Path:
    linhas, t0 = [], time.time()
    for i, uf in enumerate(UFS, 1):
        arq = BRUTO / str(ano) / f"votacao_secao_{ano}_{uf}.zip"
        if not arq.exists():
            print(f"  {uf}: sem arquivo", flush=True)
            continue
        z = zipfile.ZipFile(arq)
        nome = next(n for n in z.namelist() if n.lower().endswith(".csv"))
        antes = len(linhas)
        with z.open(nome) as fh:
            rd = csv.DictReader(io.TextIOWrapper(fh, encoding="latin-1"), delimiter=";")
            for r in rd:
                if r["DS_CARGO"].upper() != cargo or r["NR_TURNO"] != turno:
                    continue
                # ARMADILHA: o conjunto "2022" carrega eleicoes suplementares posteriores.
                # Roraima tem 6.906 linhas de governador da suplementar de 21/06/2026
                # (CD_ELEICAO 6278) misturadas com as 7.378 da eleicao de 2022 (546).
                # Sem este filtro, o estado entra no modelo com duas eleicoes sobrepostas.
                if not r["DT_ELEICAO"].endswith(str(ano)):
                    continue
                linhas.append((uf, r["CD_MUNICIPIO"], int(r["NR_ZONA"]), int(r["NR_SECAO"]),
                               r["NR_VOTAVEL"], r["NM_VOTAVEL"], int(r["QT_VOTOS"])))
        print(f"  [{i:>2}/27] {uf}  +{len(linhas)-antes:>8,} linhas  ({time.time()-t0:5.0f}s)", flush=True)

    df = pd.DataFrame(linhas, columns=["uf", "cd_municipio", "zona", "secao",
                                       "nr_votavel", "nm_votavel", "votos"])
    df["candidato"] = ~df["nr_votavel"].isin(NAO_CANDIDATO)

    SAIDA.mkdir(parents=True, exist_ok=True)
    destino = SAIDA / f"{cargo.lower()}_secao_{ano}_t{turno}.parquet"
    df.to_parquet(destino, index=False, compression="zstd")

    print(f"\n{ano} {cargo} t{turno}: {len(df):,} linhas -> {destino} "
          f"({destino.stat().st_size/1e6:.1f} MB)")
    porc = df[df["candidato"]].groupby("uf")["nr_votavel"].nunique()
    print(f"  candidatos por UF: min {porc.min()}  mediana {int(porc.median())}  max {porc.max()}")
    return destino


if __name__ == "__main__":
    ano = int(sys.argv[1]) if len(sys.argv) > 1 else 2022
    cargo = sys.argv[2] if len(sys.argv) > 2 else "GOVERNADOR"
    turno = sys.argv[3] if len(sys.argv) > 3 else "1"
    compila(ano, cargo, turno)
