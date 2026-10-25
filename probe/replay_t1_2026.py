"""Replay da noite de 04/10/2026 (1o turno) com o feed MUNICIPAL, na ordem real de chegada,
para medir o erro do needle B (ancora = 2o turno de 2022 + demografia) por estagio -- a
unica calibracao de sigma possivel nesta maquina antes do 2o turno.

Para cada marco (% de secoes totalizadas), o feed e o que o TSE teria mostrado por municipio
naquele instante: soma dos votos das secoes com DT_PRIM_TOT_PARCIAL <= t (carimbos de 2026),
st = secoes contadas, ts = total do municipio. Sem boletins (o pior caso da noite).

Verdade: o resultado final do 1o turno (dois-a-dois Lula 48,99%). Erro = margem projetada
dois-a-dois - margem real. Grava baseline/calib_presidente.json com
sigma = RMS do erro x 1,25, piso 0,5 ponto (mesma receita do METODO.md), se --grava.

Uso:  .venv/Scripts/python -m probe.replay_t1_2026 [--grava]
"""
from __future__ import annotations

import json
import sys
import time

import numpy as np
import pandas as pd

from pipeline.needle_hier import Needle, Params
from sintetico.caminhos import BASELINE, SAIDA

CHAVE = ["uf", "cd_mun", "zona", "secao"]
MARCOS = [0.5, 1, 2, 3, 5, 10, 20, 30, 50, 70, 90]


def main() -> int:
    grava = "--grava" in sys.argv
    t0 = time.time()
    anc = pd.read_parquet(SAIDA / "ancora_2026.parquet")
    nd = Needle(anc, turno=2)
    v = pd.read_parquet(SAIDA / "votos_t1_2026.parquet")
    c = pd.read_parquet(BASELINE / "carimbos_presidente_2026_t1.parquet",
                        columns=["uf", "cd_municipio", "zona", "secao", "prim_tot"])
    c["cd_mun"] = c["cd_municipio"].astype(int)
    v = v.merge(c[CHAVE + ["prim_tot"]].drop_duplicates(CHAVE), on=CHAVE, how="left")
    v = v.dropna(subset=["t1_esq"])
    v["prim_tot"] = pd.to_datetime(v["prim_tot"])
    tem = v["prim_tot"].notna()
    print(f"urnas com voto do 1o turno: {len(v):,}; com carimbo: {tem.sum():,}  [{time.time() - t0:.0f}s]")
    v = v[tem].sort_values("prim_tot").reset_index(drop=True)
    ts = v.groupby(["uf", "cd_mun"]).size().rename("ts")
    E, D = v["t1_esq"].sum(), v["t1_dir"].sum()
    real = 100 * (E - D) / (E + D)
    print(f"verdade (dois-a-dois): Lula {100 * E / (E + D):.2f}%  margem {real:+.2f}")

    linhas = []
    n = len(v)
    for pct in MARCOS:
        k = int(round(n * pct / 100))
        parte = v.iloc[:k]
        t = parte["prim_tot"].iloc[-1]
        g = parte.groupby(["uf", "cd_mun"]).agg(esq=("t1_esq", "sum"), dir=("t1_dir", "sum"), out=("t1_out", "sum"),
                                                br=("t1_br", "sum"), nu=("t1_nu", "sum"), ea=("aptos", "sum"),
                                                st=("secao", "size")).reset_index()
        g["bn"] = g["br"] + g["nu"]
        g = g.merge(ts.reset_index(), on=["uf", "cd_mun"], how="left")
        r = nd.estima(None, g, Params())
        b = r["br"]
        tela = 100 * (g["esq"].sum() - g["dir"].sum()) / (g["esq"].sum() + g["dir"].sum())
        erro = b["margem"] - real
        linhas.append({"pct": pct, "hora": t.strftime("%H:%M"), "tela": tela, "needle": b["margem"], "erro": erro,
                       "erro_tela": tela - real})
        print(f"{pct:5.1f}%  {t:%H:%M}  tela {tela:+6.2f}  needle B {b['margem']:+6.2f}  erro {erro:+6.2f}  "
              f"(tela erra {tela - real:+6.2f})  [{time.time() - t0:.0f}s]", flush=True)

    df = pd.DataFrame(linhas)
    # sigma por estagio: |erro| x 1,25 com piso 0,5; monotono nao crescente a partir do pior anterior
    sig = (df["erro"].abs() * 1.25).clip(lower=0.5).to_numpy()
    for i in range(len(sig) - 2, -1, -1):
        sig[i] = max(sig[i], sig[i + 1])
    pct = [0.0] + df["pct"].tolist() + [100.0]
    sigma_br = [max(6.0, sig[0] * 2)] + sig.tolist() + [0.1]
    calib = {"nota": ("sigma MEDIDO no replay do 1o turno de 2026 (ordem real de chegada, feed municipal, sem "
                      "boletins), ancora 2022+demografia: |erro| x 1,25, piso 0,5, envoltoria monotona. "
                      "Uma noite so; needle A usa o mesmo com fator."),
             "medido_em": pd.Timestamp.now().isoformat(timespec="seconds"),
             "pct": pct, "sigma_br": [round(float(x), 3) for x in sigma_br],
             "sigma_uf": [round(float(3 * x), 3) for x in sigma_br],
             "replay": df.round(3).to_dict(orient="records")}
    print(json.dumps({k: calib[k] for k in ("pct", "sigma_br")}))
    if grava:
        (BASELINE / "calib_presidente.json").write_text(json.dumps(calib, ensure_ascii=False, indent=1), "utf-8")
        print(f"gravado {BASELINE / 'calib_presidente.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
