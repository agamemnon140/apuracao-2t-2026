"""O alocador reproduz os 513 eleitos reais de 2022 a partir dos totais finais?

Se sim, a mecanica de quociente/sobras/federacao esta certa e a simulacao da noite pode
confiar nela. Verdade de campo: DS_SIT_TOT_TURNO da consulta_cand (ELEITO POR QP / POR MEDIA).
"""
from __future__ import annotations

import pandas as pd

from pipeline.quociente import CADEIRAS, agremiacao, aloca
from pipeline.modelo_estadual import BASE


def main() -> None:
    partido = pd.read_parquet(BASE / "depfederal_partido_secao_2022_t1.parquet")
    cand = pd.read_parquet(BASE / "depfederal_candidato_secao_2022_t1.parquet")
    oficial = pd.read_parquet(BASE / "depfederal_candidatos_2022.parquet")
    eleitos_of = oficial[oficial["sit"].str.startswith("ELEITO", na=False)]

    tot_ok = tot_dif = 0
    for uf in sorted(CADEIRAS):
        va = partido[partido["uf"] == uf].groupby("partido")["votos"].sum()
        votos_agr: dict[str, float] = {}
        for p, v in va.items():
            votos_agr[agremiacao(p)] = votos_agr.get(agremiacao(p), 0) + float(v)
        nom = cand[cand["uf"] == uf].groupby("nr")["votos"].sum().astype(float).to_dict()

        meus = set(aloca(votos_agr, nom, uf))
        reais = set(eleitos_of.loc[eleitos_of["uf"] == uf, "nr"])
        dif = meus ^ reais
        tot_ok += len(meus & reais); tot_dif += len(dif)
        marca = "ok" if not dif else f"DIFERE {len(dif)//2 if len(dif)%2==0 else len(dif)}"
        extra = ""
        if dif:
            nomes = oficial.set_index(["uf", "nr"])["nome"]
            sobra = [f"+{nomes.get((uf,n),n)}" for n in meus - reais]
            falta = [f"-{nomes.get((uf,n),n)}" for n in reais - meus]
            extra = "  " + " ".join(sobra + falta)
        print(f"  {uf}  {len(reais):>2} oficiais / {len(meus):>2} meus  {marca}{extra}")
    print(f"\nacerto: {tot_ok}/513  divergencias: {tot_dif}")


if __name__ == "__main__":
    main()
