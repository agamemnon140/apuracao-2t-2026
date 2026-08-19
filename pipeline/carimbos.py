"""Extrai, por secao, QUANDO ela entrou na apuracao -- e o peso dela.

Fonte: `detalhe_votacao_secao_{ano}.zip`, arquivo BRASIL. A coluna
`DT_PRIM_TOT_PARCIAL_HOR_TSE` e a **primeira** totalizacao parcial (nao a ultima), com
precisao de segundo e cobertura de 100%. E a ordem real de chegada da noite -- o que o
plano original planejava reconstruir com 472 mil requisicoes ao servidor do TSE.

Uso:  .venv/Scripts/python -m pipeline.carimbos [2022|2018] [CARGO]
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


def extrai(ano: int, cargo: str = "PRESIDENTE", turno: str = "1") -> Path:
    z = zipfile.ZipFile(BRUTO / str(ano) / f"detalhe_votacao_secao_{ano}.zip")
    nome = next(n for n in z.namelist() if "BRASIL" in n and n.lower().endswith(".csv"))
    linhas, t0, n = [], time.time(), 0
    with z.open(nome) as fh:
        rd = csv.DictReader(io.TextIOWrapper(fh, encoding="latin-1"), delimiter=";")
        for r in rd:
            n += 1
            if r["DS_CARGO"].upper() != cargo or r["NR_TURNO"] != turno:
                continue
            linhas.append((
                r["SG_UF"], r["CD_MUNICIPIO"], int(r["NR_ZONA"]), int(r["NR_SECAO"]),
                int(r["QT_APTOS"] or 0), int(r["QT_COMPARECIMENTO"] or 0),
                int(r["QT_ABSTENCOES"] or 0),
                (r.get("DT_PRIM_TOT_PARCIAL_HOR_TSE") or "").strip(),
                (r.get("DT_RECEBIMENTO_BU_HOR_TSE") or "").strip(),
            ))
            if len(linhas) % 200_000 == 0:
                print(f"  {n:>12,} linhas lidas  {len(linhas):>9,} secoes  {time.time()-t0:5.0f}s", flush=True)

    df = pd.DataFrame(linhas, columns=["uf", "cd_municipio", "zona", "secao", "aptos",
                                       "comparecimento", "abstencoes", "prim_tot", "bu_recebido"])
    for c in ("prim_tot", "bu_recebido"):
        df[c] = pd.to_datetime(df[c], format="%d/%m/%Y %H:%M:%S", errors="coerce")

    SAIDA.mkdir(parents=True, exist_ok=True)
    destino = SAIDA / f"carimbos_{cargo.lower()}_{ano}_t{turno}.parquet"
    df.to_parquet(destino, index=False, compression="zstd")
    print(f"\n{ano} {cargo} {turno}o turno: {len(df):,} secoes -> {destino}")
    print(f"  sem carimbo: {df['prim_tot'].isna().sum():,}")
    print(f"  primeira: {df['prim_tot'].min()}   ultima: {df['prim_tot'].max()}")
    print(f"  eleitorado apto somado: {df['aptos'].sum():,}")
    return destino


if __name__ == "__main__":
    ano = int(sys.argv[1]) if len(sys.argv) > 1 else 2022
    cargo = sys.argv[2] if len(sys.argv) > 2 else "PRESIDENTE"
    extrai(ano, cargo)
