"""Compila o voto POR SECAO e POR PARTIDO de um cargo proporcional (dep. federal/estadual).

No proporcional o que se projeta primeiro e o share de cada PARTIDO no estado (quociente
eleitoral trabalha sobre isso). Voto nominal + legenda somados por partido: os dois primeiros
digitos do NR_VOTAVEL identificam o partido, tanto no voto nominal (4-5 digitos) quanto no de
legenda (2 digitos). Brancos (95) e nulos (96) ficam de fora do valido.

Uso:  .venv/Scripts/python -m pipeline.baseline_partido [2022] [FEDERAL|ESTADUAL]
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
CARGO = {"FEDERAL": "DEPUTADO FEDERAL", "ESTADUAL": ("DEPUTADO ESTADUAL", "DEPUTADO DISTRITAL")}


def compila(ano: int, qual: str = "FEDERAL") -> Path:
    alvo = CARGO[qual]
    alvos = alvo if isinstance(alvo, tuple) else (alvo,)
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
                if nr in ("95", "96"):
                    continue
                chave = (uf, r["CD_MUNICIPIO"], int(r["NR_ZONA"]), int(r["NR_SECAO"]), nr[:2])
                acc[chave] = acc.get(chave, 0) + int(r["QT_VOTOS"])
        print(f"  [{i:>2}/27] {uf}  acumulado {len(acc):>10,}  ({time.time()-t0:5.0f}s)", flush=True)

    df = pd.DataFrame([(*k, v) for k, v in acc.items()],
                      columns=["uf", "cd_municipio", "zona", "secao", "partido", "votos"])
    SAIDA.mkdir(parents=True, exist_ok=True)
    destino = SAIDA / f"dep{qual.lower()}_partido_secao_{ano}_t1.parquet"
    df.to_parquet(destino, index=False, compression="zstd")
    print(f"\n{ano} DEP {qual}: {len(df):,} linhas -> {destino} ({destino.stat().st_size/1e6:.1f} MB)")
    return destino


if __name__ == "__main__":
    compila(int(sys.argv[1]) if len(sys.argv) > 1 else 2022,
            sys.argv[2] if len(sys.argv) > 2 else "FEDERAL")
