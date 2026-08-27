"""Monta o alvo do sintetico: 3 shares sobre aptos por secao, 2o turno 2022.

  sh_lula + sh_bolsonaro + sh_nenhum = 1, onde "nenhum" = brancos + nulos + abstencao.

Fontes ja em disco: presidente_secao_2022.parquet (votos, compilado pelo baseline da
apuracao) e detalhe_votacao_secao_2022.zip (aptos/abstencao/brancos/nulos + numero do
local de votacao, que e a ponte para as coordenadas e o Voronoi).

Secao sem linha de voto no 2o turno (anulada/apurada em separado) e descartada com aviso.

Uso:  .venv/Scripts/python -m sintetico.alvo
"""
from __future__ import annotations

import csv
import io
import sys
import zipfile

import pandas as pd

from .caminhos import BASELINE, BRUTO_TSE, SAIDA


def detalhe_t2() -> pd.DataFrame:
    z = zipfile.ZipFile(BRUTO_TSE / "2022" / "detalhe_votacao_secao_2022.zip")
    linhas = []
    with z.open("detalhe_votacao_secao_2022_BR.csv") as fh:
        rd = csv.DictReader(io.TextIOWrapper(fh, encoding="latin-1"), delimiter=";")
        for r in rd:
            if r["NR_TURNO"] != "2" or r["DS_CARGO"].upper() != "PRESIDENTE":
                continue
            if r["ANO_ELEICAO"] != "2022":
                continue
            linhas.append((r["SG_UF"], r["CD_MUNICIPIO"], int(r["NR_ZONA"]),
                           int(r["NR_SECAO"]), int(r["NR_LOCAL_VOTACAO"]),
                           int(r["QT_APTOS"]), int(r["QT_COMPARECIMENTO"]),
                           int(r["QT_ABSTENCOES"]), int(r["QT_VOTOS_BRANCOS"]),
                           int(r["QT_VOTOS_NULOS"]), r["ST_SECAO_INSTALADA"]))
    return pd.DataFrame(linhas, columns=["uf", "cd_municipio", "zona", "secao",
                                         "nr_local", "aptos", "comparecimento",
                                         "abstencoes", "brancos", "nulos", "instalada"])


def main() -> int:
    det = detalhe_t2()
    votos = pd.read_parquet(BASELINE / "presidente_secao_2022.parquet",
                            columns=["uf", "cd_municipio", "zona", "secao", "t2_esq", "t2_dir"])

    base = det.merge(votos, on=["uf", "cd_municipio", "zona", "secao"], how="left")
    sem_voto = base["t2_esq"].isna()
    nao_inst = base["instalada"] != "Sim"
    print(f"secoes no detalhe (t2): {len(base)}")
    print(f"  nao instaladas: {nao_inst.sum()} | sem linha de voto: {(sem_voto & ~nao_inst).sum()}")
    base = base[~sem_voto & ~nao_inst].copy()

    base["lula"] = base["t2_esq"].astype(int)
    base["bolsonaro"] = base["t2_dir"].astype(int)
    base = base.drop(columns=["t2_esq", "t2_dir", "instalada"])

    # aptos == 0 nao tem share definido (secoes fantasma); fora com aviso
    zerados = base["aptos"] == 0
    if zerados.any():
        print(f"  aptos=0 descartadas: {zerados.sum()}")
        base = base[~zerados]

    base["sh_lula"] = base["lula"] / base["aptos"]
    base["sh_bolsonaro"] = base["bolsonaro"] / base["aptos"]
    base["sh_nenhum"] = 1.0 - base["sh_lula"] - base["sh_bolsonaro"]

    # sanidade dura contra o resultado oficial do 2o turno
    lula, bolso = base["lula"].sum(), base["bolsonaro"].sum()
    aptos = base["aptos"].sum()
    validos = lula + bolso
    print(f"secoes na base final: {len(base)}")
    print(f"Lula {100 * lula / validos:.2f}% dos validos (oficial 50,90)")
    print(f"abstencao {100 * base['abstencoes'].sum() / aptos:.2f}% dos aptos (oficial 20,58)")
    print(f"'nenhum' {100 * (aptos - validos) / aptos:.2f}% dos aptos")

    SAIDA.mkdir(parents=True, exist_ok=True)
    destino = SAIDA / "alvo_2022_t2.parquet"
    base.to_parquet(destino, index=False)
    print(f"gravado {destino}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
