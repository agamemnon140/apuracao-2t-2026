"""Baixa e compila o voto de VEREADOR de 2020 por secao e partido.

Insumo do teste 'eleicao municipal turbina a previsao da geral?': 2020->2022 e o analogo
exato de 2024->2026. Vereador (e nao prefeito) porque e o voto partidario de base, existe em
todo municipio e nao tem 2o turno.

Uso:  .venv/Scripts/python -m pipeline.baseline_vereador
"""
from __future__ import annotations

import csv
import io
import json
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import cdn  # noqa: E402

BRUTO = Path(r"D:\Claude\eleicoes-dados\raw\dadosabertos\2020")
SAIDA = Path(r"D:\Claude\eleicoes-dados\baseline")


def recursos() -> list[tuple[str, str]]:
    u = "https://dadosabertos.tse.jus.br/api/3/action/package_show?id=resultados-2020"
    j = json.loads(urllib.request.urlopen(urllib.request.Request(u, headers=cdn.H), timeout=120).read())
    return sorted((r["url"].rsplit("/", 1)[-1], r["url"]) for r in j["result"]["resources"]
                  if r["url"].rsplit("/", 1)[-1].startswith("votacao_secao_2020_"))


def main() -> None:
    alvos = [(n, u) for n, u in recursos() if not n.endswith("_BR.zip")]
    print(f"{len(alvos)} arquivos de 2020 no catalogo", flush=True)
    acc: dict[tuple, int] = {}
    t0 = time.time()
    for i, (nome, url) in enumerate(alvos, 1):
        destino = BRUTO / nome
        try:
            cdn.baixa(url, destino)
        except Exception as e:
            print(f"  [{i:>2}] FALHOU {nome}: {type(e).__name__}", flush=True)
            continue
        z = zipfile.ZipFile(destino)
        csvn = next(n for n in z.namelist() if n.lower().endswith(".csv"))
        with z.open(csvn) as fh:
            rd = csv.DictReader(io.TextIOWrapper(fh, encoding="latin-1"), delimiter=";")
            for r in rd:
                if r["DS_CARGO"].upper() != "VEREADOR" or r["NR_TURNO"] != "1":
                    continue
                if not r["DT_ELEICAO"].endswith("2020"):
                    continue
                nr = r["NR_VOTAVEL"]
                if nr in ("95", "96"):
                    continue
                chave = (r["SG_UF"], r["CD_MUNICIPIO"], int(r["NR_ZONA"]),
                         int(r["NR_SECAO"]), nr[:2])
                acc[chave] = acc.get(chave, 0) + int(r["QT_VOTOS"])
        print(f"  [{i:>2}/{len(alvos)}] {nome}  acumulado {len(acc):>11,}  "
              f"({time.time()-t0:5.0f}s)", flush=True)

    df = pd.DataFrame([(*k, v) for k, v in acc.items()],
                      columns=["uf", "cd_municipio", "zona", "secao", "partido", "votos"])
    destino = SAIDA / "vereador_partido_secao_2020_t1.parquet"
    df.to_parquet(destino, index=False, compression="zstd")
    print(f"\n2020 VEREADOR: {len(df):,} linhas -> {destino} "
          f"({destino.stat().st_size/1e6:.1f} MB)", flush=True)


if __name__ == "__main__":
    main()
