"""Replay analogo do needle A: ancora = 1o turno de 2022 por urna (terceiros na proporcao
local), verdade = 2o turno de 2022, feed municipal na ordem de chegada de 04/10/2026 (proxy:
a ordem real de 2022 esta so no D:). Mede o erro por estagio do que o needle A faz hoje:
projetar o 2o turno a partir do 1o do mesmo ano -- transferencia de terceiros (~8% em 2022,
~8% em 2026) e mudanca de abstencao.

Universo: urnas de 2026 que tem par em 2022 (aptos22, pr22t1 e pr22t2 nos JSONs do repo).
Grava baseline/calib_presidente_t1.json (sigma = |erro| x 1,25, piso 0,5, envoltoria) com --grava.

Uso:  .venv/Scripts/python -m probe.replay_t2_2022 [--grava]
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


def lo(a, b):
    return np.log((a + .5) / (b + .5))


def main() -> int:
    grava = "--grava" in sys.argv
    t0 = time.time()
    base = pd.read_parquet(SAIDA / "ancora_t1_2026.parquet").drop(columns=["aptos22"], errors="ignore")
    v = pd.read_parquet(SAIDA / "votos_2022.parquet")
    a = base.merge(v, on=CHAVE, how="inner")
    a = a[a["t21_esq"].notna() & a["t22_esq"].notna() & (a["aptos22"] > 0)].reset_index(drop=True)
    # ancora: 1o turno de 2022 na urna, no mesmo formato do needle A
    val21 = a["t21_esq"] + a["t21_dir"] + a["t21_out"]
    a["aptos"] = a["aptos22"].astype(float)
    a["a_ed"] = lo(a["t21_esq"], a["t21_dir"])
    a["a_part"] = lo(val21, (a["aptos"] - val21).clip(lower=0))
    a["a_out"] = lo(a["t21_out"], a["t21_esq"] + a["t21_dir"])
    a["a_bn"] = lo(a["t21_br"] + a["t21_nu"], val21)
    anc_cols = CHAVE + ["nr_local", "aptos", "a_ed", "a_part", "a_out", "a_bn", "ordem_hist"] + \
        [c for c in a.columns if c.startswith("x_")]
    nd = Needle(a[anc_cols].copy(), turno=2)

    c = pd.read_parquet(BASELINE / "carimbos_presidente_2026_t1.parquet",
                        columns=["uf", "cd_municipio", "zona", "secao", "prim_tot"])
    c["cd_mun"] = c["cd_municipio"].astype(int)
    v2 = a[CHAVE + ["aptos", "t22_esq", "t22_dir", "t22_br", "t22_nu"]].merge(
        c[CHAVE + ["prim_tot"]].drop_duplicates(CHAVE), on=CHAVE, how="left")
    v2["prim_tot"] = pd.to_datetime(v2["prim_tot"])
    v2 = v2.dropna(subset=["prim_tot"]).sort_values("prim_tot").reset_index(drop=True)
    ts = v2.groupby(["uf", "cd_mun"]).size().rename("ts")
    E, D = a["t22_esq"].sum(), a["t22_dir"].sum()
    real = 100 * (E - D) / (E + D)
    anc_e = float((nd.esp0["esq"]).sum() / nd.esp0["dois"].sum())
    print(f"urnas: {len(a):,} (com carimbo {len(v2):,})  ancora (1T 2022 a dois) Lula {100 * anc_e:.2f}%  "
          f"verdade (2T 2022) Lula {100 * E / (E + D):.2f}%  margem {real:+.2f}  [{time.time() - t0:.0f}s]")

    linhas = []
    n = len(v2)
    for pct in MARCOS:
        k = int(round(n * pct / 100))
        parte = v2.iloc[:k]
        g = parte.groupby(["uf", "cd_mun"]).agg(esq=("t22_esq", "sum"), dir=("t22_dir", "sum"), br=("t22_br", "sum"),
                                                nu=("t22_nu", "sum"), ea=("aptos", "sum"), st=("secao", "size")).reset_index()
        g["out"] = 0.0
        g["bn"] = g["br"] + g["nu"]
        g = g.merge(ts.reset_index(), on=["uf", "cd_mun"], how="left")
        r = nd.estima(None, g, Params())
        b = r["br"]
        tela = 100 * (g["esq"].sum() - g["dir"].sum()) / (g["esq"].sum() + g["dir"].sum())
        erro = b["margem"] - real
        linhas.append({"pct": pct, "tela": tela, "needle": b["margem"], "erro": erro, "erro_tela": tela - real})
        print(f"{pct:5.1f}%  tela {tela:+6.2f}  needle A' {b['margem']:+6.2f}  erro {erro:+6.2f}  "
              f"(tela erra {tela - real:+6.2f})  [{time.time() - t0:.0f}s]", flush=True)

    df = pd.DataFrame(linhas)
    sig = np.array((df["erro"].abs() * 1.25).clip(lower=0.5).to_numpy(), dtype=float, copy=True)
    for i in range(len(sig) - 2, -1, -1):
        sig[i] = max(sig[i], sig[i + 1])
    pct = [0.0] + df["pct"].tolist() + [100.0]
    sigma_br = [max(6.0, sig[0] * 2)] + sig.tolist() + [0.1]
    calib = {"nota": ("sigma do needle A MEDIDO no replay analogo de 2022 (ancora = 1T 2022 por urna, verdade = 2T 2022, "
                      "feed municipal na ordem de chegada de 04/10/2026 como proxy): |erro| x 1,25, piso 0,5, envoltoria."),
             "rotulo": "medido no replay análogo de 2022 (1º→2º turno, feed municipal)",
             "medido_em": pd.Timestamp.now().isoformat(timespec="seconds"),
             "pct": pct, "sigma_br": [round(float(x), 3) for x in sigma_br],
             "sigma_uf": [round(float(3 * x), 3) for x in sigma_br],
             "replay": df.round(3).to_dict(orient="records")}
    print(json.dumps({k: calib[k] for k in ("pct", "sigma_br")}))
    if grava:
        (BASELINE / "calib_presidente_t1.json").write_text(json.dumps(calib, ensure_ascii=False, indent=1), "utf-8")
        print(f"gravado {BASELINE / 'calib_presidente_t1.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
