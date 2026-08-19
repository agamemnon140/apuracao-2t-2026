"""A noite de 2022 congelada, agora para DEPUTADO FEDERAL: as 513 cadeiras por estagio.

Em cada estagio, com as secoes ja totalizadas:
  - total de cada agremiacao projetado pelo modelo estadual (eixo 2018 + efeito municipio),
    tratando agremiacao como "candidato";
  - voto nominal de cada candidato projetado pela MESMA proporcao dentro da agremiacao vista
    no apurado (a ordem interna converge rapido; a incerteza dela fica para o P2);
  - quociente + sobras -> 513 nomes projetados, comparados com os 513 reais.
"""
from __future__ import annotations

import sys

import numpy as np
import pandas as pd

from pipeline.modelo_estadual import BASE, projeta
from pipeline.quociente import CADEIRAS, agremiacao, aloca
from probe.simula_17h15 import monta_generico

MARCOS = [1, 2, 3, 5, 10, 20, 50] if len(sys.argv) < 2 else [float(x) for x in sys.argv[1:]]


def main() -> None:
    partido = pd.read_parquet(BASE / "depfederal_partido_secao_2022_t1.parquet")
    partido["agr"] = partido["partido"].map(agremiacao)
    cand = pd.read_parquet(BASE / "depfederal_candidato_secao_2022_t1.parquet")
    car = pd.read_parquet(BASE / "carimbos_governador_2022_t1.parquet")

    # referencia: o MESMO alocador aplicado aos totais finais (isola erro de projecao do
    # erro de mecanica; contra os eleitos oficiais o alocador faz 498/513, com RJ/SE/AP
    # explicados por cassacao e anulacao judicial posteriores a noite)
    ref = {}
    for uf in sorted(CADEIRAS):
        va = partido[partido["uf"] == uf].groupby("agr")["votos"].sum().astype(float).to_dict()
        nomf = cand[cand["uf"] == uf].groupby("nr")["votos"].sum().astype(float).to_dict()
        ref[uf] = set(aloca(va, nomf, uf))

    votos_l = partido.rename(columns={"agr": "quem"})[
        ["uf", "cd_municipio", "zona", "secao", "quem", "votos"]]

    resumo = []
    for p in MARCOS:
        certos = tot_bancada_err = 0
        for uf in sorted(CADEIRAS):
            sec, comp = monta_generico(votos_l, car, uf, "quem")
            n = max(5, int(len(sec) * p / 100))
            pr = projeta(sec, comp, n)                     # share projetado por agremiacao
            validos_finais = sec[comp].sum().sum()         # escala: tamanho do estado
            votos_agr = {a: float(pr[a] * validos_finais) for a in pr.index}

            # ordem nominal dentro da agremiacao: proporcao vista nas secoes apuradas
            chave = sec[["uf", "cd_municipio", "zona", "secao"]].iloc[:n]
            ap = cand[cand["uf"] == uf].merge(chave, on=["uf", "cd_municipio", "zona", "secao"])
            nom_ap = ap.groupby("nr")["votos"].sum().astype(float)
            share_dentro = {}
            for nr, v in nom_ap.items():
                a = agremiacao(nr[:2])
                share_dentro.setdefault(a, {})[nr] = v
            # fracao de legenda POR agremiacao, medida no proprio apurado
            va_ap = (sec[comp].iloc[:n].sum())
            nominais = {}
            for a, d in share_dentro.items():
                s = sum(d.values())
                if s <= 0 or a not in votos_agr:
                    continue
                f_nom = min(1.0, s / float(va_ap[a])) if a in va_ap and va_ap[a] > 0 else 0.92
                for nr, v in d.items():
                    nominais[nr] = votos_agr[a] * (v / s) * f_nom

            meus = set(aloca(votos_agr, nominais, uf))
            reais = ref[uf]
            certos += len(meus & reais)

            ban_meu = pd.Series([agremiacao(nr[:2]) for nr in meus]).value_counts()
            ban_real = pd.Series([agremiacao(nr[:2]) for nr in reais]).value_counts()
            tot_bancada_err += int((ban_meu.sub(ban_real, fill_value=0)).abs().sum()) // 2
        resumo.append({"p": p, "nomes_certos": certos,
                       "pct": round(100 * certos / 513, 1),
                       "cadeiras_bancada_erradas": tot_bancada_err})
        print(f"  {p:5.1f}% apurado: {certos}/513 nomes certos ({100*certos/513:.1f}%)  "
              f"bancada com {tot_bancada_err} cadeiras fora", flush=True)


if __name__ == "__main__":
    main()
