"""Monta o alvo do sintetico: 3 shares sobre aptos por secao, 2o turno.

  sh_esq + sh_dir + sh_nenhum = 1, onde "nenhum" = brancos + nulos + abstencao.

2018/2022 reusam o parquet do baseline da apuracao (presidente_secao_{ano});
2010/2014 extraem direto de votacao_secao_{ano}_BR.zip. O detalhe_votacao_secao
do ano traz aptos/abstencao e o numero do local de votacao (ponte para o Voronoi).

As colunas de saida mantem os nomes historicos lula/bolsonaro/sh_lula/... para nao
quebrar o restante do pipeline: leia como esquerda (13) e direita (45/17/22).

Uso:  .venv/Scripts/python -m sintetico.alvo [2010|2014|2018|2022]
"""
from __future__ import annotations

import csv
import io
import sys
import zipfile

import pandas as pd

from .caminhos import BASELINE, BRUTO_TSE, SAIDA

DIREITA = {2010: "45", 2014: "45", 2018: "17", 2022: "22"}   # esquerda e sempre 13


def mapa_agregadas(ano: int) -> dict:
    """(uf, mun, zona, secao) -> secao principal, no 2o turno. Secoes agregadas
    tem os votos reportados na principal; sem isso o merge com a votacao falha."""
    z = zipfile.ZipFile(BRUTO_TSE / str(ano) / f"eleitorado_local_votacao_{ano}.zip")
    mapa = {}
    with z.open(f"eleitorado_local_votacao_{ano}.csv") as fh:
        rd = csv.DictReader(io.TextIOWrapper(fh, encoding="latin-1"), delimiter=";")
        for r in rd:
            if r["NR_TURNO"] != "2":
                continue
            princ = int(r.get("NR_SECAO_PRINCIPAL", -1))
            if princ > 0:
                mapa[(r["SG_UF"], r["CD_MUNICIPIO"].lstrip("0"), int(r["NR_ZONA"]),
                      int(r["NR_SECAO"]))] = princ
    return mapa


def detalhe_t2(ano: int) -> pd.DataFrame:
    z = zipfile.ZipFile(BRUTO_TSE / str(ano) / f"detalhe_votacao_secao_{ano}.zip")
    linhas = []
    with z.open(f"detalhe_votacao_secao_{ano}_BR.csv") as fh:
        rd = csv.DictReader(io.TextIOWrapper(fh, encoding="latin-1"), delimiter=";")
        for r in rd:
            if r["NR_TURNO"] != "2" or r["DS_CARGO"].upper() != "PRESIDENTE":
                continue
            if r["ANO_ELEICAO"] != str(ano):
                continue
            linhas.append((r["SG_UF"], r["CD_MUNICIPIO"].lstrip("0"), int(r["NR_ZONA"]),
                           int(r["NR_SECAO"]), int(r["NR_LOCAL_VOTACAO"]),
                           int(r["QT_APTOS"]), int(r["QT_COMPARECIMENTO"]),
                           int(r["QT_ABSTENCOES"]), int(r["QT_VOTOS_BRANCOS"]),
                           int(r["QT_VOTOS_NULOS"]),
                           r.get("ST_SECAO_INSTALADA", "Sim")))
    return pd.DataFrame(linhas, columns=["uf", "cd_municipio", "zona", "secao",
                                         "nr_local", "aptos", "comparecimento",
                                         "abstencoes", "brancos", "nulos", "instalada"])


def votos_t2(ano: int) -> pd.DataFrame:
    if ano in (2018, 2022):
        v = pd.read_parquet(BASELINE / f"presidente_secao_{ano}.parquet",
                            columns=["uf", "cd_municipio", "zona", "secao", "t2_esq", "t2_dir"])
        v["cd_municipio"] = v["cd_municipio"].str.lstrip("0")
        return v
    dir_ = DIREITA[ano]
    z = zipfile.ZipFile(BRUTO_TSE / str(ano) / f"votacao_secao_{ano}_BR.zip")
    acc: dict = {}
    with z.open(f"votacao_secao_{ano}_BR.csv") as fh:
        rd = csv.DictReader(io.TextIOWrapper(fh, encoding="latin-1"), delimiter=";")
        for r in rd:
            if r["NR_TURNO"] != "2" or r["DS_CARGO"].upper() != "PRESIDENTE":
                continue
            if r["ANO_ELEICAO"] != str(ano):
                continue
            chave = (r["SG_UF"], r["CD_MUNICIPIO"].lstrip("0"), int(r["NR_ZONA"]), int(r["NR_SECAO"]))
            a = acc.setdefault(chave, [0, 0])
            nr, v = r["NR_VOTAVEL"], int(r["QT_VOTOS"])
            if nr == "13":
                a[0] += v
            elif nr == dir_:
                a[1] += v
    return pd.DataFrame([(k[0], k[1], k[2], k[3], v[0], v[1]) for k, v in acc.items()],
                        columns=["uf", "cd_municipio", "zona", "secao", "t2_esq", "t2_dir"])


def main() -> int:
    ano = int(sys.argv[1]) if len(sys.argv) > 1 else 2022
    det = detalhe_t2(ano)
    votos = votos_t2(ano)

    base = det.merge(votos, on=["uf", "cd_municipio", "zona", "secao"], how="left")
    print(f"{ano}: secoes no detalhe (t2): {len(base)}")

    # secao agregada sem linha de voto propria: soma as contagens na principal
    sem = base["t2_esq"].isna()
    if sem.any():
        mapa = mapa_agregadas(ano)
        chave_n = list(zip(base["uf"], base["cd_municipio"].str.lstrip("0"),
                           base["zona"], base["secao"]))
        base["secao_ef"] = [mapa.get(k, s) for k, s in zip(chave_n, base["secao"])]
        move = sem & (base["secao_ef"] != base["secao"])
        if move.any():
            extra = base[move].groupby(["uf", "cd_municipio", "zona", "secao_ef"])[
                ["aptos", "comparecimento", "abstencoes", "brancos", "nulos"]].sum()
            idx = base.set_index(["uf", "cd_municipio", "zona", "secao"]).index
            soma = extra.reindex(idx).fillna(0).to_numpy()
            for j, c in enumerate(["aptos", "comparecimento", "abstencoes", "brancos", "nulos"]):
                base[c] = base[c].to_numpy() + soma[:, j]
            base = base[~move]
            print(f"  agregadas somadas na principal: {move.sum()}")
        base = base.drop(columns=["secao_ef"])

    sem_voto = base["t2_esq"].isna()
    # 2018 grava "#NULO#" no campo; so o "Nao" explicito exclui
    nao_inst = base["instalada"].str.strip().str.upper().isin(["NÃO", "NAO", "N"])
    print(f"  nao instaladas: {nao_inst.sum()} | sem linha de voto: {(sem_voto & ~nao_inst).sum()}")
    base = base[~sem_voto & ~nao_inst].copy()

    base["lula"] = base["t2_esq"].astype(int)
    base["bolsonaro"] = base["t2_dir"].astype(int)
    base = base.drop(columns=["t2_esq", "t2_dir", "instalada"])

    zerados = base["aptos"] == 0
    if zerados.any():
        print(f"  aptos=0 descartadas: {zerados.sum()}")
        base = base[~zerados]
    # urna com mais voto no par do que aptos (agregacoes raras) distorce share
    estouro = (base["lula"] + base["bolsonaro"]) > base["aptos"]
    if estouro.any():
        print(f"  votos>aptos descartadas: {estouro.sum()}")
        base = base[~estouro]

    base["sh_lula"] = base["lula"] / base["aptos"]
    base["sh_bolsonaro"] = base["bolsonaro"] / base["aptos"]
    base["sh_nenhum"] = 1.0 - base["sh_lula"] - base["sh_bolsonaro"]

    lula, bolso = base["lula"].sum(), base["bolsonaro"].sum()
    aptos = base["aptos"].sum()
    validos = lula + bolso
    print(f"secoes na base final: {len(base)}")
    print(f"esquerda {100 * lula / validos:.2f}% dos validos")
    print(f"abstencao {100 * base['abstencoes'].sum() / aptos:.2f}% dos aptos")
    print(f"'nenhum' {100 * (aptos - validos) / aptos:.2f}% dos aptos")

    SAIDA.mkdir(parents=True, exist_ok=True)
    destino = SAIDA / f"alvo_{ano}_t2.parquet"
    base.to_parquet(destino, index=False)
    print(f"gravado {destino}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
