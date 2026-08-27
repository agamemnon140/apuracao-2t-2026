"""Ajusta o sintetico: logit multinomial ponderado dos 3 shares (Lula, Bolsonaro,
nenhum) sobre os eixos demograficos, por secao.

Cada secao vira 3 observacoes (uma por desfecho) com peso = contagem de eleitores,
o que equivale a maxima verossimilhanca multinomial agrupada. Covariaveis sao
padronizadas (z-score ponderado por aptos); coeficiente = efeito de +1 desvio-padrao.

Importancia por eixo = drop-one: quanto da deviance explicada some ao remover o eixo.

Saidas: sintetico/modelo_2022.json (coeficientes, padronizacao, metricas, drop-one,
        erro por UF) e predicoes em sintetico/pred_2022.parquet.

Uso:  .venv/Scripts/python -m sintetico.modelo
"""
from __future__ import annotations

import json
import sys
import time

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression

from .caminhos import SAIDA

EIXOS = {
    "sexo": ["pct_fem"],
    "idade": ["pct_1624", "pct_2539", "pct_60m"],
    "escolaridade": ["pct_fund", "pct_sup"],
    "renda": ["log_renda"],
    "raca": ["pct_branca", "pct_preta"],
    "urbano_rural": ["pct_rural"],
    "porte": ["log_pop_mun", "hierarquia_num", "em_rm"],
    "regiao": ["reg_N", "reg_NE", "reg_CO", "reg_S"],
    "religiao": ["pct_evangelica", "pct_sem_religiao"],
    "industria_vab": ["vab_agro", "vab_industria", "vab_adm"],
    "industria_ocup": ["pct_ocup_agro", "pct_ocup_bens", "pct_ocup_comercio"],
}
CLASSES = ["lula", "bolsonaro", "nenhum"]


def monta_xy(base: pd.DataFrame, mu=None, sd=None):
    """Se mu/sd vierem (padrao de outro ano), padroniza NELE -- e assim que os
    coeficientes de anos diferentes ficam na mesma unidade (+1 dp de 2022)."""
    base = base.copy()
    for reg in ["N", "NE", "CO", "S"]:
        base[f"reg_{reg}"] = (base["regiao"] == reg).astype(float)
    cols = [c for eixo in EIXOS.values() for c in eixo]
    X = base[cols].astype(float)
    X = X.fillna(X.median(numeric_only=True))

    w_aptos = base["aptos"].to_numpy(float)
    if mu is None:
        mu = (X.to_numpy() * w_aptos[:, None]).sum(0) / w_aptos.sum()
        sd = np.sqrt(((X.to_numpy() - mu) ** 2 * w_aptos[:, None]).sum(0) / w_aptos.sum())
        sd[sd == 0] = 1.0
    else:
        mu, sd = np.asarray(mu), np.asarray(sd)
    Xz = (X.to_numpy() - mu) / sd

    contagens = np.c_[base["lula"], base["bolsonaro"],
                      base["aptos"] - base["lula"] - base["bolsonaro"]].astype(float)
    contagens = np.clip(contagens, 0, None)
    return Xz, contagens, cols, mu, sd


def ajusta(Xz: np.ndarray, contagens: np.ndarray, max_iter: int = 2000):
    n, k = Xz.shape
    X3 = np.repeat(Xz, 3, axis=0)
    y3 = np.tile(np.arange(3), n)
    w3 = contagens.ravel()
    ok = w3 > 0
    m = LogisticRegression(penalty=None, solver="lbfgs", max_iter=max_iter, tol=1e-7)
    m.fit(X3[ok], y3[ok], sample_weight=w3[ok])
    return m


def metricas(m, Xz, contagens):
    p = m.predict_proba(Xz)                      # ordem das classes = 0,1,2
    w = contagens.sum(1)
    ll = float((contagens * np.log(np.clip(p, 1e-12, None))).sum())
    p0 = contagens.sum(0) / contagens.sum()
    ll0 = float((contagens * np.log(p0)).sum())
    return p, ll, ll0, 1.0 - ll / ll0


def main() -> int:
    ano = int(sys.argv[1]) if len(sys.argv) > 1 else 2022
    base = pd.read_parquet(SAIDA / f"base_{ano}.parquet")
    ref = (None, None)
    if ano != 2022:      # anos antigos herdam a padronizacao de 2022 (comparabilidade)
        with open(SAIDA / "modelo_2022.json", encoding="utf-8") as fh:
            m22 = json.load(fh)
        ref = (m22["mu"], m22["sd"])
    Xz, contagens, cols, mu, sd = monta_xy(base, *ref)
    print(f"{ano}: {len(base)} secoes, {len(cols)} covariaveis")

    t0 = time.time()
    m = ajusta(Xz, contagens)
    p, ll, ll0, r2 = metricas(m, Xz, contagens)
    print(f"modelo cheio: pseudo-R2 = {r2:.4f} [{time.time() - t0:.0f}s]")

    # reconstrucao dos agregados
    aptos = contagens.sum(1)
    def resumo(mask=None):
        s = slice(None) if mask is None else mask
        prev = (p[s] * aptos[s, None]).sum(0)
        real = contagens[s].sum(0)
        return prev / prev.sum(), real / real.sum()
    prev_br, real_br = resumo()
    prev_val = prev_br[0] / (prev_br[0] + prev_br[1])
    real_val = real_br[0] / (real_br[0] + real_br[1])
    print(f"BR: Lula previsto {100 * prev_val:.2f}% dos validos vs real {100 * real_val:.2f}%")

    por_uf = {}
    ufs = base["uf"].to_numpy()
    for uf in sorted(set(ufs)):
        mask = ufs == uf
        pv, rl = resumo(mask)
        por_uf[uf] = {"prev": pv.tolist(), "real": rl.tolist(),
                      "erro_lula_pp": 100 * (pv[0] - rl[0])}

    # drop-one por eixo
    drop = {}
    for eixo, eixo_cols in EIXOS.items():
        idx = [i for i, c in enumerate(cols) if c not in eixo_cols]
        t0 = time.time()
        m_r = ajusta(Xz[:, idx], contagens)
        _, ll_r, _, r2_r = metricas(m_r, Xz[:, idx], contagens)
        drop[eixo] = {"pseudo_r2": r2_r, "perda": r2 - r2_r}
        print(f"drop {eixo:15s}: R2 {r2_r:.4f} (perda {r2 - r2_r:.4f}) "
              f"[{time.time() - t0:.0f}s]", flush=True)

    saida = {
        "classes": CLASSES, "cols": cols,
        "coef": m.coef_.tolist(), "intercept": m.intercept_.tolist(),
        "mu": mu.tolist(), "sd": sd.tolist(),
        "pseudo_r2": r2, "ll": ll, "ll_nulo": ll0,
        "br": {"prev": prev_br.tolist(), "real": real_br.tolist()},
        "por_uf": por_uf, "drop_one": drop,
        "shares_globais": (contagens.sum(0) / contagens.sum()).tolist(),
    }
    with open(SAIDA / f"modelo_{ano}.json", "w", encoding="utf-8") as fh:
        json.dump(saida, fh, ensure_ascii=False, indent=1)

    pred = base[["uf", "cd_municipio_tse", "zona", "secao", "aptos"]].copy()
    for i, c in enumerate(CLASSES):
        pred[f"p_{c}"] = p[:, i]
        pred[f"sh_{c}"] = contagens[:, i] / aptos
    pred.to_parquet(SAIDA / f"pred_{ano}.parquet", index=False)
    print(f"gravados modelo_{ano}.json e pred_{ano}.parquet")
    return 0


if __name__ == "__main__":
    sys.exit(main())
