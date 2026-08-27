"""Analise entre ciclos: deriva dos coeficientes 2010-2022, poder preditivo
cross-year (comportamento do ciclo anterior + demografia do ciclo seguinte) e o
"vento" nacional de cada transicao -- o deslocamento uniforme de log-chance da
direita necessario para casar o resultado nacional. E o objeto que a incumbencia
habita: com 3 transicoes ele nao vira estimativa causal, mas vira regua historica.

Requer os 4 modelos ajustados na MESMA padronizacao (a de 2022; ver modelo.py).

Saida: sintetico/comparativo.json.

Uso:  .venv/Scripts/python -m sintetico.comparativo
"""
from __future__ import annotations

import json
import sys

import numpy as np
import pandas as pd

from .caminhos import SAIDA
from .modelo import monta_xy

ANOS = [2010, 2014, 2018, 2022]
CONTEXTO = {
    (2010, 2014): "esquerda incumbente (Dilma tenta reeleição)",
    (2014, 2018): "ciclo petista encerrado no impeachment; esquerda sem incumbente, Lula preso",
    (2018, 2022): "direita incumbente (Bolsonaro tenta reeleição)",
}


def dev_explicada(ano: int) -> dict:
    pred = pd.read_parquet(SAIDA / f"pred_{ano}.parquet")
    aptos = pred["aptos"].to_numpy(float)
    cont = np.c_[pred["sh_lula"], pred["sh_bolsonaro"], pred["sh_nenhum"]] * aptos[:, None]
    p = np.c_[pred["p_lula"], pred["p_bolsonaro"], pred["p_nenhum"]]
    sh = cont / aptos[:, None]
    ll = (cont * np.log(np.clip(p, 1e-12, None))).sum()
    p0 = cont.sum(0) / cont.sum()
    ll0 = (cont * np.log(p0)).sum()
    llsat = (cont[sh > 0] * np.log(sh[sh > 0])).sum()
    par = sh[:, 0] + sh[:, 1]
    ok = par > 0
    vs_o = sh[ok, 0] / par[ok]
    vs_p = p[ok, 0] / (p[ok, 0] + p[ok, 1])
    w = aptos[ok]
    r2 = 1 - np.average((vs_o - vs_p) ** 2, weights=w) / \
        np.average((vs_o - np.average(vs_o, weights=w)) ** 2, weights=w)
    return {"dev_expl": float((ll - ll0) / (llsat - ll0)),
            "r2_validos": float(r2),
            "mae_validos": float(np.average(np.abs(vs_o - vs_p), weights=w))}


def prediz_nacional(M: dict, Xz: np.ndarray, aptos: np.ndarray, shift_dir: float = 0.0):
    eta = Xz @ np.array(M["coef"]).T + np.array(M["intercept"])
    eta[:, 1] += shift_dir
    eta -= eta.max(1, keepdims=True)
    p = np.exp(eta)
    p /= p.sum(1, keepdims=True)
    tot = (p * aptos[:, None]).sum(0)
    return tot / tot.sum()


def vento(M: dict, Xz, aptos, alvo_esq_validos: float) -> float:
    lo, hi = -1.5, 1.5
    for _ in range(60):
        mid = (lo + hi) / 2
        sh = prediz_nacional(M, Xz, aptos, mid)
        ev = sh[0] / (sh[0] + sh[1])
        if ev > alvo_esq_validos:      # esquerda alta demais -> empurrar direita
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def main() -> int:
    modelos, bases, Xzs = {}, {}, {}
    with open(SAIDA / "modelo_2022.json", encoding="utf-8") as fh:
        m22 = json.load(fh)
    for ano in ANOS:
        with open(SAIDA / f"modelo_{ano}.json", encoding="utf-8") as fh:
            modelos[ano] = json.load(fh)
        b = pd.read_parquet(SAIDA / f"base_{ano}.parquet")
        bases[ano] = b
        Xz, cont, cols, _, _ = monta_xy(b, m22["mu"], m22["sd"])
        Xzs[ano] = (Xz, cont.sum(1), cont)

    # deriva dos coeficientes (contraste esq-dir por covariavel, unidade fixa)
    cols = m22["cols"]
    deriva = {}
    for i, c in enumerate(cols):
        deriva[c] = {str(a): float(np.array(modelos[a]["coef"])[0][i]
                                   - np.array(modelos[a]["coef"])[1][i]) for a in ANOS}

    fit = {}
    for ano in ANOS:
        cont = Xzs[ano][2]
        esq_val = cont[:, 0].sum() / (cont[:, 0].sum() + cont[:, 1].sum())
        fit[str(ano)] = {**dev_explicada(ano), "esq_validos_real": float(esq_val),
                         "nenhum_real": float(cont[:, 2].sum() / cont.sum())}
        print(f"{ano}: dev {fit[str(ano)]['dev_expl']:.3f} | R2 validos "
              f"{fit[str(ano)]['r2_validos']:.3f} | esquerda {100 * esq_val:.2f}%")

    # transicoes: comportamento de A aplicado a demografia de B
    trans = {}
    for a, b in [(2010, 2014), (2014, 2018), (2018, 2022)]:
        Xz_b, aptos_b, cont_b = Xzs[b]
        sh = prediz_nacional(modelos[a], Xz_b, aptos_b)
        prev = sh[0] / (sh[0] + sh[1])
        real = fit[str(b)]["esq_validos_real"]
        v = vento(modelos[a], Xz_b, aptos_b, real)
        # e a previsao ingenua (repetir o nacional de A) para comparacao
        real_a = fit[str(a)]["esq_validos_real"]
        trans[f"{a}->{b}"] = {
            "contexto": CONTEXTO[(a, b)],
            "prev_demografia": float(prev), "real": float(real),
            "erro_pp": float(100 * (prev - real)),
            "erro_ingenuo_pp": float(100 * (real_a - real)),
            "vento_logodds_direita": float(v),
        }
        print(f"{a}->{b}: demografia preve {100 * prev:.2f}%, real {100 * real:.2f}% "
              f"(erro {100 * (prev - real):+.2f}pp; ingenuo {100 * (real_a - real):+.2f}pp; "
              f"vento {v:+.3f})")

    with open(SAIDA / "comparativo.json", "w", encoding="utf-8") as fh:
        json.dump({"deriva": deriva, "fit": fit, "transicoes": trans}, fh,
                  ensure_ascii=False, indent=1)
    print("gravado comparativo.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
