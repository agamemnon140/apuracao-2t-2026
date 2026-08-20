"""A noite de 2022 congelada as 17h15 -- 10 minutos de apuracao. O que ja dava para dizer?

Melhores correlacoes disponiveis em cada cargo:
  presidente  -> ancora por secao no 2o turno de 2018 + pooling por UF (pipeline.modelo)
  governador  -> eixo 2018 + efeito de municipio aprendido ao vivo (pipeline.modelo_estadual)
  senador     -> mesma maquina do governador (2022 elegeu 1 vaga por estado)
  dep federal -> share de PARTIDO por estado, mesma maquina, partido como "candidato"

Cada corrida ve SO as secoes com primeira totalizacao ate as 17:15:00 daquela noite.
"""
from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd

from pipeline.modelo import monta as monta_pres, projeta as proj_pres
from pipeline.modelo_estadual import BASE, CHAVE, monta as monta_gov, projeta as proj_uf
from pipeline.modelo_estadual import eixo_2018

import sys
try:                                   # so vale quando rodado como script
    _min = int(sys.argv[1]) if len(sys.argv) > 1 else 15
except ValueError:
    _min = 15
CORTE = dt.datetime(2022, 10, 2, 17, 0, 0) + dt.timedelta(minutes=_min)


def monta_generico(votos_long: pd.DataFrame, carimbos: pd.DataFrame, uf: str, col: str):
    """Mesma preparacao do modelo estadual, para qualquer tabela longa secao x competidor."""
    v = votos_long[votos_long["uf"] == uf]
    car = carimbos[carimbos["uf"] == uf]
    wide = v.pivot_table(index=CHAVE, columns=col, values="votos",
                         aggfunc="sum", fill_value=0).reset_index()
    sec = car[CHAVE + ["aptos", "prim_tot"]].merge(wide, on=CHAVE, how="inner")
    sec = sec.merge(eixo_2018(), on=CHAVE, how="left")
    for nivel in (["cd_municipio"], []):
        if sec["z"].isna().any():
            if nivel:
                med = (sec.dropna(subset=["z"]).groupby(nivel)
                       .apply(lambda g: np.average(g["z"], weights=g["peso18"]), include_groups=False)
                       .rename("fb").reset_index())
                sec = sec.merge(med, on=nivel, how="left")
                sec["z"] = sec["z"].fillna(sec["fb"]); sec = sec.drop(columns="fb")
            else:
                sec["z"] = sec["z"].fillna(sec["z"].mean())
    comp = [c for c in wide.columns if c not in CHAVE]
    sec["validos"] = sec[comp].sum(axis=1)
    sec = sec[sec["validos"] > 0].sort_values("prim_tot").reset_index(drop=True)
    return sec, comp


def uma_uf(sec, comp, rotulo_nomes=None):
    n = int(sec["prim_tot"].searchsorted(CORTE))
    final = sec[comp].sum() / sec[comp].sum().sum()
    o = final.sort_values(ascending=False)
    if n < 5:
        return {"n": n, "pct": 100 * n / len(sec), "status": "sem dados",
                "campeao_real": o.index[0], "acertou": None, "err": None}
    pr = proj_uf(sec, comp, n)
    po = pr.sort_values(ascending=False)
    return {"n": n, "pct": 100 * n / len(sec), "status": "ok",
            "campeao_real": o.index[0], "proj": po.index[0],
            "acertou": po.index[0] == o.index[0],
            "err": 100 * abs(pr[o.index[0]] - final[o.index[0]]),
            "dupla_ok": set(po.index[:2]) == set(o.index[:2])}


def main() -> None:
    # ---------- presidente ----------
    df = monta_pres()
    n = int(df["prim_tot"].searchsorted(CORTE))
    r = proj_pres(df, n)
    final = 100 * float((df["v"] * df["m"]).sum() / df["v"].sum())
    print("=" * 74)
    print(f"BRASIL, 02/10/2022 as {CORTE:%H:%M} — {n:,} secoes totalizadas "
          f"({100*n/len(df):.2f}% do pais)")
    print("=" * 74)
    print(f"\nPRESIDENTE  (margem esq-dir, final real {final:+.2f})")
    print(f"  tela crua : {r['naive']:+7.2f}   (erro {r['naive']-final:+.2f})")
    print(f"  modelo    : {r['modelo']:+7.2f}   (erro {r['modelo']-final:+.2f})  -> vencedor "
          f"{'CERTO' if np.sign(r['modelo'])==np.sign(final) else 'ERRADO'}")

    carg_gov = pd.read_parquet(BASE / "carimbos_governador_2022_t1.parquet")

    # ---------- governador e senador ----------
    for cargo, arq, carimbo in (("GOVERNADOR", "governador_secao_2022_t1.parquet", None),
                                ("SENADOR", "senador_secao_2022_t1.parquet",
                                 "carimbos_senador_2022_t1.parquet")):
        votos = pd.read_parquet(BASE / arq)
        votos = votos[votos["candidato"]].rename(columns={"nm_votavel": "quem"})
        car = pd.read_parquet(BASE / carimbo) if carimbo else carg_gov
        print(f"\n{cargo}  (27 corridas)")
        ok = tot = 0; sem = []; erros = []; errados = []
        for uf in sorted(votos["uf"].unique()):
            sec, comp = monta_generico(votos, car, uf, "quem")
            r = uma_uf(sec, comp)
            if r["status"] == "sem dados":
                sem.append(f"{uf}({r['n']})")
                continue
            tot += 1
            if r["acertou"]:
                ok += 1
            else:
                errados.append(uf)
            erros.append(r["err"])
        print(f"  com dados: {tot}/27   lider certo: {ok}/{tot}"
              + (f"   errados: {', '.join(errados)}" if errados else ""))
        if erros:
            print(f"  erro no share do campeao: mediana {np.median(erros):.2f}  "
                  f"pior {max(erros):.2f}")
        if sem:
            print(f"  sem dados: {', '.join(sem)}")

    # ---------- deputado federal (share de partido) ----------
    dep = pd.read_parquet(BASE / "depfederal_partido_secao_2022_t1.parquet")
    dep = dep.rename(columns={"partido": "quem"})
    print(f"\nDEPUTADO FEDERAL  (share de partido por estado — quociente vem depois)")
    ok = tot = 0; maes = []; sem = []
    for uf in sorted(dep["uf"].unique()):
        sec, comp = monta_generico(dep, carg_gov, uf, "quem")
        nn = int(sec["prim_tot"].searchsorted(CORTE))
        final = sec[comp].sum() / sec[comp].sum().sum()
        if nn < 5:
            sem.append(uf); continue
        pr = proj_uf(sec, comp, nn)
        tot += 1
        if pr.idxmax() == final.idxmax():
            ok += 1
        maes.append(100 * float((pr - final).abs().mean()))
    print(f"  com dados: {tot}/27   maior partido do estado certo: {ok}/{tot}")
    print(f"  erro medio absoluto no share por partido: mediana {np.median(maes):.2f} "
          f"pontos, pior {max(maes):.2f}")
    if sem:
        print(f"  sem dados: {', '.join(sem)}")


if __name__ == "__main__":
    main()
