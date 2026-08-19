"""O needle diz 60% -- acontece 60% das vezes?

Constroi a probabilidade da forma que o plano exige (simulacao a partir de erros reais,
nunca logistica chutada) e testa a calibracao SEM auto-engano:

  1. Em cada corrida (27 governos + 27 senados de 2022) e em cada estagio de apuracao,
     o modelo projeta a margem entre os dois primeiros.
  2. A distribuicao de erro dessa margem vem das OUTRAS corridas do mesmo cargo no mesmo
     estagio (leave-one-out) -- a corrida nunca ve o proprio erro.
  3. P(lider projetado vence) = fracao dos erros emprestados que nao viram a margem.
  4. Calibracao: em todas as previsoes juntas, quando o needle diz X%, o lider vence X% das vezes?

Amostra: ~54 corridas x 10 estagios. Correlacao entre estagios da mesma corrida reduz a
amostra efetiva -- o teste por corrida-unica no final controla isso.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from pipeline.modelo_estadual import BASE, monta, projeta
from probe.simula_17h15 import monta_generico

MARCOS = [1, 2, 3, 5, 10, 20, 30, 50, 70, 90]


def corridas():
    """(cargo, uf, sec, comp) para governador e senador."""
    out = []
    gov_car = pd.read_parquet(BASE / "carimbos_governador_2022_t1.parquet")
    sen_car = pd.read_parquet(BASE / "carimbos_senador_2022_t1.parquet")
    for cargo, arq, car in (("GOV", "governador_secao_2022_t1.parquet", gov_car),
                            ("SEN", "senador_secao_2022_t1.parquet", sen_car)):
        votos = pd.read_parquet(BASE / arq)
        votos = votos[votos["candidato"]].rename(columns={"nm_votavel": "quem"})
        for uf in sorted(votos["uf"].unique()):
            sec, comp = monta_generico(votos, car, uf, "quem")
            out.append((cargo, uf, sec, comp))
    return out


def main() -> None:
    prev = []          # uma linha por (corrida, estagio): margem projetada, erro real, vencedor
    for cargo, uf, sec, comp in corridas():
        final = sec[comp].sum() / sec[comp].sum().sum()
        campeao = final.idxmax()
        for p in MARCOS:
            n = max(5, int(len(sec) * p / 100))
            pr = projeta(sec, comp, n)
            if pr.empty:
                continue
            po = pr.sort_values(ascending=False)
            lider, vice = po.index[0], po.index[1]
            m_hat = float(po.iloc[0] - po.iloc[1])                    # margem projetada
            m_fin = float(final[lider] - final[vice])                 # a mesma dupla, no final
            prev.append({"cargo": cargo, "uf": uf, "p": p, "m_hat": 100 * m_hat,
                         "erro": 100 * (m_hat - m_fin), "venceu": lider == campeao})
        print(f"  {cargo} {uf} ok", flush=True)

    d = pd.DataFrame(prev)

    # probabilidade leave-one-out: os erros das outras corridas do mesmo cargo/estagio
    probs = []
    for (cargo, p), g in d.groupby(["cargo", "p"]):
        for i, r in g.iterrows():
            e = g.loc[g["uf"] != r["uf"], "erro"].to_numpy()
            venc = (r["m_hat"] - e > 0).sum()
            probs.append({"i": i, "prob": (venc + 0.5) / (len(e) + 1)})
    d = d.join(pd.DataFrame(probs).set_index("i"))

    print(f"\nprevisoes: {len(d)}   (54 corridas x {len(MARCOS)} estagios)")
    print(f"Brier score: {((d['prob'] - d['venceu']) ** 2).mean():.4f}  "
          f"(chute de 50% daria 0.25; oraculo daria 0)")

    print("\nCALIBRACAO — needle diz X%, lider vence quantas vezes?")
    d["faixa"] = pd.cut(d["prob"], [0, .5, .6, .7, .8, .9, .95, .99, 1.001],
                        labels=["<50", "50-60", "60-70", "70-80", "80-90",
                                "90-95", "95-99", ">99"])
    tab = d.groupby("faixa", observed=True).agg(
        previsto=("prob", "mean"), observado=("venceu", "mean"), n=("venceu", "size"))
    tab[["previsto", "observado"]] = (100 * tab[["previsto", "observado"]]).round(1)
    print(tab.to_string())

    print("\nPOR ESTAGIO (media da prob x taxa real de acerto do lider projetado)")
    est = d.groupby("p").agg(prob_media=("prob", "mean"), acerto=("venceu", "mean"),
                             n=("venceu", "size"))
    est[["prob_media", "acerto"]] = (100 * est[["prob_media", "acerto"]]).round(1)
    print(est.to_string())

    # controle de correlacao entre estagios: um sorteio de UM estagio por corrida
    rng = np.random.default_rng(2026)
    um = d.groupby(["cargo", "uf"], group_keys=False).apply(
        lambda g: g.iloc[rng.integers(len(g))], include_groups=False)
    print(f"\ncontrole (1 estagio sorteado por corrida, n={len(um)}): "
          f"prob media {100*um['prob'].mean():.1f}%  acerto real {100*um['venceu'].mean():.1f}%")


if __name__ == "__main__":
    main()
