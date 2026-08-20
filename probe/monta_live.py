"""Gera docs/dados/live.json — o contrato de dados da tela da noite.

Em 2026, o runner local recalcula este arquivo a cada ciclo e o site so le. Nesta v1 ele e
preenchido com o replay de 2022 congelado a 10% das secoes, no MESMO formato, para a pagina
nascer pronta para a noite real.

Contrato (docs/METODO.md detalha):
  modo            "replay-2022" | "aguardando" | "ao-vivo"
  presidente      margem projetada (esq-dir, validos), prob do lider, tela crua, % secoes
  governos[27]    lider/segundo com share projetado e P(lider vence) via erros leave-one-out
  senado[27]      idem (2022 = 1 vaga; em 2026 serao 2 e o needle vira P(entre os 2))
  camara          bancada nacional por agremiacao com IC (p10/mediana/p90) e mediana por UF
  assembleias     idem, deputado estadual

Uso:  .venv/Scripts/python -m probe.monta_live
"""
from __future__ import annotations

import datetime as dt
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from pipeline.modelo import monta as monta_pres, projeta as proj_pres
from pipeline.modelo_estadual import BASE, monta as monta_gov, projeta as proj_uf
from probe.calibracao import corridas
from pipeline.quociente import FEDERACOES

P = 10.0
SAIDA = Path(__file__).resolve().parents[1] / "docs" / "dados" / "live.json"


def sigla_map() -> dict:
    of = pd.read_parquet(BASE / "depfederal_candidatos_2022.parquet")
    m = of.groupby(of["nr"].str[:2])["partido"].agg(lambda s: s.mode().iloc[0]).to_dict()
    m.update({"13": "PT", "22": "PL", "45": "PSDB", "15": "MDB"})
    return m


def rotulo_agr(a: str, sig: dict) -> str:
    return a[4:].replace("/", "·") if a.startswith("FED-") else sig.get(a, a)


def majoritarias() -> tuple[list, list]:
    """54 corridas com share projetado e P(lider) por erros leave-one-out do mesmo cargo."""
    prev = []
    for cargo, uf, sec, comp in corridas():
        n = max(5, int(len(sec) * P / 100))
        pr = proj_uf(sec, comp, n)
        if pr.empty:
            continue
        po = pr.sort_values(ascending=False)
        final = sec[comp].sum() / sec[comp].sum().sum()
        m_hat = float(po.iloc[0] - po.iloc[1])
        m_fin = float(final[po.index[0]] - final[po.index[1]])
        prev.append({"cargo": cargo, "uf": uf, "lider": po.index[0], "s1": float(po.iloc[0]),
                     "segundo": po.index[1], "s2": float(po.iloc[1]),
                     "m_hat": 100 * m_hat, "erro": 100 * (m_hat - m_fin),
                     "pct": round(100 * n / len(sec), 1)})
    d = pd.DataFrame(prev)
    govs, sens = [], []
    for cargo, dst in (("GOV", govs), ("SEN", sens)):
        g = d[d["cargo"] == cargo]
        for _, r in g.iterrows():
            e = g.loc[g["uf"] != r["uf"], "erro"].to_numpy()
            p_l = float(((r["m_hat"] - e > 0).sum() + 0.5) / (len(e) + 1))
            dst.append({"uf": r["uf"], "pct_secoes": r["pct"],
                        "lider": r["lider"].title()[:24], "share": round(100 * r["s1"], 1),
                        "segundo": r["segundo"].title()[:24], "share2": round(100 * r["s2"], 1),
                        "p_lider": round(p_l, 3)})
    return govs, sens


def bancadas(cargo: str, sig: dict):
    arq = BASE / f"seats_{cargo}_p{P:g}.parquet"
    if not arq.exists():
        return None
    s = pd.read_parquet(arq)
    ndraws = int(s["draw"].max()) + 1
    # nacional: mesmo indice de sorteio soma entre estados (estados independentes)
    nac = (s.pivot_table(index="draw", columns="agr", values="seats", aggfunc="sum")
           .reindex(range(ndraws)).fillna(0))
    linhas = []
    for a in nac.columns:
        v = nac[a].to_numpy()
        linhas.append({"agr": rotulo_agr(a, sig), "p10": int(np.percentile(v, 10)),
                       "med": int(np.median(v)), "p90": int(np.percentile(v, 90))})
    linhas.sort(key=lambda x: -x["med"])
    por_uf = {}
    for uf, g in s.groupby("uf"):
        piv = g.pivot_table(index="draw", columns="agr", values="seats", aggfunc="sum")
        piv = piv.reindex(range(ndraws)).fillna(0)
        por_uf[uf] = sorted(({"agr": rotulo_agr(a, sig), "med": int(piv[a].median())}
                             for a in piv.columns if piv[a].median() >= 1),
                            key=lambda x: -x["med"])
    return {"nacional": [x for x in linhas if x["p90"] >= 1], "por_uf": por_uf}


def main() -> None:
    df = monta_pres()
    n = int(len(df) * P / 100)
    r = proj_pres(df, n)
    # sigma nacional aproximado: erro de margem dos governos no mesmo estagio / sqrt(27)
    _g, _s = None, None
    sig = sigla_map()
    govs, sens = majoritarias()
    err_gov = 3.4 / math.sqrt(27)          # medido no replay (desvio GOV aos 10%)
    p_pres = 0.5 * (1 + math.erf((r["modelo"] / err_gov) / math.sqrt(2)))

    live = {
        "modo": "replay-2022",
        "congelado_em": "10% das seções totalizadas (~18h32 de 02/10/2022)",
        "gerado_em": dt.datetime.now().isoformat(timespec="seconds"),
        "presidente": {"lider": "Lula", "margem": round(r["modelo"], 2),
                       "tela_crua": round(r["naive"], 2),
                       "p_lider": round(min(p_pres, 0.999), 3),
                       "pct_secoes": round(r["pct_secoes"], 1)},
        "governos": govs, "senado": sens,
        "camara": bancadas("federal", sig),
        "assembleias": bancadas("estadual", sig),
    }
    SAIDA.parent.mkdir(parents=True, exist_ok=True)
    SAIDA.write_text(json.dumps(live, ensure_ascii=False, separators=(",", ":")), "utf-8")
    print(f"{SAIDA}  ({SAIDA.stat().st_size/1e3:.0f} KB)")
    print("camara:", "ok" if live["camara"] else "PENDENTE (seats parquet)")
    print("assembleias:", "ok" if live["assembleias"] else "PENDENTE (seats parquet)")


if __name__ == "__main__":
    main()
