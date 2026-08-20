"""Voto NOMINAL por candidato e secao, para cargo proporcional (federal ou estadual).

Complementa o baseline_partido: la, nominal+legenda somados por partido (e o que o quociente
usa como total); aqui, so o nominal por candidato (NR_VOTAVEL de 3+ digitos), que decide a
ORDEM dentro do partido e os pisos individuais (10% do QE para vaga de quociente, 20% para
sobra). Legenda (2 digitos) fica de fora por construcao.

Uso:  .venv/Scripts/python -m pipeline.baseline_candidato [2022] [FEDERAL|ESTADUAL]
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


CARGOS = {"FEDERAL": ("DEPUTADO FEDERAL",),
          "ESTADUAL": ("DEPUTADO ESTADUAL", "DEPUTADO DISTRITAL")}


def compila(ano: int, qual: str = "FEDERAL") -> Path:
    alvos = CARGOS[qual]
    acc: dict[tuple, int] = {}
    t0 = time.time()
    for i, uf in enumerate(UFS, 1):
        z = zipfile.ZipFile(BRUTO / str(ano) / f"votacao_secao_{ano}_{uf}.zip")
        nome = next(n for n in z.namelist() if n.lower().endswith(".csv"))
        with z.open(nome) as fh:
            rd = csv.DictReader(io.TextIOWrapper(fh, encoding="latin-1"), delimiter=";")
            for r in rd:
                if r["DS_CARGO"].upper() not in alvos or r["NR_TURNO"] != "1":
                    continue
                if not r["DT_ELEICAO"].endswith(str(ano)):
                    continue
                nr = r["NR_VOTAVEL"]
                if len(nr) < 3:                     # legenda, branco, nulo
                    continue
                chave = (uf, r["CD_MUNICIPIO"], int(r["NR_ZONA"]), int(r["NR_SECAO"]), nr)
                acc[chave] = acc.get(chave, 0) + int(r["QT_VOTOS"])
        print(f"  [{i:>2}/27] {uf}  acumulado {len(acc):>11,}  ({time.time()-t0:5.0f}s)", flush=True)

    df = pd.DataFrame([(*k, v) for k, v in acc.items()],
                      columns=["uf", "cd_municipio", "zona", "secao", "nr", "votos"])
    destino = SAIDA / f"dep{qual.lower()}_candidato_secao_{ano}_t1.parquet"
    df.to_parquet(destino, index=False, compression="zstd")
    print(f"\n{ano}: {len(df):,} linhas -> {destino} ({destino.stat().st_size/1e6:.1f} MB)")
    return destino


if __name__ == "__main__":
    compila(int(sys.argv[1]) if len(sys.argv) > 1 else 2022,
            sys.argv[2] if len(sys.argv) > 2 else "FEDERAL")
