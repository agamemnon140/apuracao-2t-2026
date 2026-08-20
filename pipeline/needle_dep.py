"""Needle por deputado: P(eleito) via Monte Carlo sobre o quociente.

Duas fontes de incerteza, calibradas nos proprios dados por estagio de apuracao:

  1. share da AGREMIACAO no estado -- erro do modelo estadual, escala k_p * sqrt(s(1-s)),
     com k_p medido comparando projecao x final nas 27 UFs (leave-one-out por UF);
  2. ordem NOMINAL dentro da agremiacao -- o share apurado de cada candidato dentro do
     partido e tratado como amostra de tamanho efetivo ESS_p (medido por estagio: quanta
     deriva ainda existe entre o parcial e o final). Sorteio Dirichlet(w * ESS_p).

Cada sorteio vira uma eleicao completa: totais -> quociente -> sobras -> eleitos.
P(eleito) = frequencia. O degrau do quociente vira probabilidade continua sozinho.

Alem do needle, calcula por candidato:
  target -- votos que faltam para a linha de corte da propria agremiacao (ou folga);
  vento  -- a geografia que AINDA NAO apurou ajuda ou atrapalha? share final projetado
            dentro do partido (decomposto por municipio) menos o share ja apurado.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from pipeline.modelo_estadual import BASE, projeta
from pipeline.quociente import CADEIRAS, agremiacao, aloca
from probe.simula_17h15 import monta_generico

CADEIRAS_EST = {uf: (3 * f if f <= 12 else 36 + (f - 12)) for uf, f in CADEIRAS.items()}
CHAVE = ["uf", "cd_municipio", "zona", "secao"]


def carrega(cargo: str):
    """cargo: 'federal' | 'estadual'."""
    partido = pd.read_parquet(BASE / f"dep{cargo}_partido_secao_2022_t1.parquet")
    partido["agr"] = partido["partido"].map(agremiacao)
    cand = pd.read_parquet(BASE / f"dep{cargo}_candidato_secao_2022_t1.parquet")
    oficial = pd.read_parquet(BASE / f"dep{cargo}_candidatos_2022.parquet")
    car = pd.read_parquet(BASE / "carimbos_governador_2022_t1.parquet")
    votos_l = partido.rename(columns={"agr": "quem"})[CHAVE + ["quem", "votos"]]
    cadeiras = CADEIRAS if cargo == "federal" else CADEIRAS_EST
    return votos_l, cand, oficial, car, cadeiras


def estado(votos_l, cand, car, uf, p):
    """Projecao de ponto + insumos do MC para uma UF num estagio."""
    sec, comp = monta_generico(votos_l, car, uf, "quem")
    n = max(5, int(len(sec) * p / 100))
    pr = projeta(sec, comp, n)                       # share projetado por agremiacao
    validos = float(sec[comp].sum().sum())

    chave_ap = sec[CHAVE].iloc[:n]
    ap = cand[cand["uf"] == uf].merge(chave_ap, on=CHAVE)
    nom_ap = ap.groupby("nr")["votos"].sum().astype(float)
    va_ap = sec[comp].iloc[:n].sum()

    fim = cand[cand["uf"] == uf].groupby("nr")["votos"].sum().astype(float)
    return sec, comp, n, pr, validos, nom_ap, va_ap, fim


def calibra(cargo: str, marcos, ufs=None):
    """k_p (erro de share da agremiacao) e ESS_p (deriva da ordem nominal), por estagio."""
    votos_l, cand, _of, car, _cd = carrega(cargo)
    ufs = ufs or sorted(votos_l["uf"].unique())
    out = {}
    for p in marcos:
        zs, es, ws = [], [], []
        for uf in ufs:
            sec, comp, n, pr, validos, nom_ap, va_ap, fim = estado(votos_l, cand, car, uf, p)
            final = sec[comp].sum() / sec[comp].sum().sum()
            for a in pr.index:
                s = float(pr[a])
                if s > 0.005:
                    zs.append((float(pr[a]) - float(final.get(a, 0))) / np.sqrt(s * (1 - s)))
            # deriva nominal: share dentro do partido, apurado x final
            agr_nr = nom_ap.index.str[:2].map(agremiacao)
            den_ap = nom_ap.groupby(agr_nr).transform("sum")
            w = (nom_ap / den_ap).dropna()
            agr_f = fim.index.str[:2].map(agremiacao)
            f = (fim / fim.groupby(agr_f).transform("sum")).reindex(w.index).fillna(0)
            m = w > 0.02
            es.append(((f[m] - w[m]) ** 2).to_numpy())
            ws.append((w[m] * (1 - w[m])).to_numpy())
        k = float(np.std(zs))
        var_err = float(np.concatenate(es).mean())
        ess = float(np.concatenate(ws).mean() / max(var_err, 1e-9))
        out[p] = {"k": k, "ess": ess}
        print(f"  estagio {p:>5}%: k={k:.3f}  ESS={ess:,.0f}", flush=True)
    return out


def needle_uf(cargo, uf, p, calib, ndraws=300, seed=2026, dados=None):
    votos_l, cand, oficial, car, cadeiras = dados if dados is not None else carrega(cargo)
    sec, comp, n, pr, validos, nom_ap, va_ap, fim = estado(votos_l, cand, car, uf, p)
    k, ess = calib[p]["k"], calib[p]["ess"]
    rng = np.random.default_rng(seed)

    agrs = list(pr.index)
    s = pr.to_numpy(float)
    # candidatos por agremiacao (apurados)
    por_agr = {}
    for nr, v in nom_ap.items():
        por_agr.setdefault(agremiacao(nr[:2]), {})[nr] = v
    f_nom = {a: min(1.0, sum(d.values()) / float(va_ap[a])) if a in va_ap and va_ap[a] > 0
             else 0.9 for a, d in por_agr.items()}

    conta = {}
    seats_draws = []                       # (sorteio, agremiacao, cadeiras) p/ bancada com IC
    for _dr in range(ndraws):
        eps = rng.normal(0, k * np.sqrt(np.clip(s * (1 - s), 1e-9, None)))
        sd = np.clip(s + eps, 0, None)
        sd = sd / sd.sum()
        votos_agr = {a: float(sd[i] * validos) for i, a in enumerate(agrs)}
        nominais = {}
        for a, d in por_agr.items():
            if a not in votos_agr:
                continue
            nrs = list(d)
            wv = np.array([d[x] for x in nrs], float)
            alpha = np.clip(wv / wv.sum() * ess, 1e-3, None)
            shares = rng.dirichlet(alpha)
            tot = votos_agr[a] * f_nom.get(a, 0.9)
            for x, sh in zip(nrs, shares):
                nominais[x] = tot * sh
        el = aloca(votos_agr, nominais, uf, vagas=cadeiras[uf])
        por = {}
        for e in el:
            conta[e] = conta.get(e, 0) + 1
            a_ = agremiacao(e[:2])
            por[a_] = por.get(a_, 0) + 1
        seats_draws += [(_dr, a_, c_) for a_, c_ in por.items()]

    # projecao de ponto (para target/corte) e referencia final
    votos_pt = {a: float(pr[a] * validos) for a in agrs}
    nom_pt = {}
    for a, d in por_agr.items():
        if a not in votos_pt:
            continue
        ss = sum(d.values())
        for x, v in d.items():
            nom_pt[x] = votos_pt[a] * (v / ss) * f_nom.get(a, 0.9)
    eleitos_pt = set(aloca(votos_pt, nom_pt, uf, vagas=cadeiras[uf]))
    va_fim = votos_l[votos_l["uf"] == uf].groupby("quem")["votos"].sum().astype(float).to_dict()
    ref = set(aloca(va_fim, fim.to_dict(), uf, vagas=cadeiras[uf]))

    # nr se repete entre UFs -- filtrar antes de indexar, senao .get devolve Series
    nomes = oficial[oficial["uf"] == uf].drop_duplicates("nr").set_index("nr")[["nome", "partido"]]
    va_estado_ap = float(sec["validos"].iloc[:n].sum())   # validos ja contados no estado
    fr_estado = va_estado_ap / validos                    # fracao do estado ja apurada
    linhas = []
    for a, d in por_agr.items():
        eleitos_a = sorted((x for x in eleitos_pt if agremiacao(x[:2]) == a),
                           key=lambda x: -nom_pt.get(x, 0))
        corte = nom_pt[eleitos_a[-1]] if eleitos_a else None
        for x, v in sorted(d.items(), key=lambda kv: -kv[1]):
            pv = nom_pt.get(x, 0.0)
            # ritmo: fracao apurada do candidato / fracao apurada do estado.
            # 100% = sem vento; <100% = o grosso dele ainda esta por vir (vento a favor)
            ritmo = (float(v) / pv) / fr_estado if pv > 0 and fr_estado > 0 else None
            linhas.append({
                "uf": uf, "agr": a, "nr": x,
                "nome": nomes["nome"].get(x, x), "partido": nomes["partido"].get(x, x[:2]),
                "p_eleito": conta.get(x, 0) / ndraws,
                "votos_proj": pv, "votos_apurados": float(v),
                "ritmo": (round(100 * ritmo, 1) if ritmo is not None else None),
                "corte_agr": corte,
                "eleito_agora": x in eleitos_pt,
                "target": (corte - pv) if (corte is not None and x not in eleitos_pt) else
                          (pv - corte if corte is not None else None),
                "eleito_final": x in ref,
            })
    qe_proj = sum(votos_pt.values()) / cadeiras[uf]
    meta = {"qe_proj": qe_proj, "cadeiras": cadeiras[uf], "pct_secoes": 100 * n / len(sec),
            "seats_draws": pd.DataFrame(seats_draws, columns=["draw", "agr", "seats"])}
    return pd.DataFrame(linhas), meta


def vento_uf(cargo, uf, p, dados=None, tau=200.0):
    """O que AINDA NAO apurou beneficia quem?

    Para cada candidato: share final esperado dentro da agremiacao, decomposto por
    municipio (onde ja ha apuracao local, usa-se o share local; onde nao ha, o share
    estadual encolhido por `tau` votos), menos o share ja apurado. Positivo = os votos
    que faltam estao nos redutos dele; negativo = o grosso dele ja passou.

    Devolve tambem pct_apurado: fracao dos votos esperados do candidato ja contada.
    """
    votos_l, cand, _of, car, _cd = dados if dados is not None else carrega(cargo)
    sec, comp, n, pr, validos, nom_ap, va_ap, fim = estado(votos_l, cand, car, uf, p)

    ap_keys = sec[CHAVE].iloc[:n]
    cu = cand[cand["uf"] == uf]
    c_ap = cu.merge(ap_keys, on=CHAVE)
    c_ap["agr"] = c_ap["nr"].str[:2].map(agremiacao)

    # votos da agremiacao por municipio: apurado, e esperado no que falta
    pu = votos_l[votos_l["uf"] == uf].rename(columns={"quem": "agr"})
    p_ap = pu.merge(ap_keys, on=CHAVE).groupby(["cd_municipio", "agr"])["votos"].sum()
    taxa = float(sec["validos"].iloc[:n].sum() / sec["aptos"].iloc[:n].sum())
    resto_aptos = sec.iloc[n:].groupby("cd_municipio")["aptos"].sum()
    # share da agremiacao por municipio (apurado local encolhido para o estadual)
    tot_mun_ap = p_ap.groupby("cd_municipio").sum()
    linhas = []
    share_uf = pr.to_dict()
    for (m, a), v in p_ap.items():
        s_loc = (v + 400 * share_uf.get(a, 0)) / (tot_mun_ap[m] + 400)
        linhas.append((m, a, s_loc))
    s_loc = pd.Series({(m, a): s for m, a, s in linhas})
    resto_agr = {}
    for m, aptos_r in resto_aptos.items():
        base = aptos_r * taxa
        for a in pr.index:
            resto_agr[(m, a)] = base * float(s_loc.get((m, a), share_uf.get(a, 0)))

    # share do candidato dentro da agremiacao, por municipio (encolhido por tau)
    cm = c_ap.groupby(["cd_municipio", "agr", "nr"])["votos"].sum().reset_index()
    agr_mun = cm.groupby(["cd_municipio", "agr"])["votos"].transform("sum")
    tot_cand = c_ap.groupby("nr")["votos"].sum()
    tot_agr = c_ap.groupby("agr")["votos"].sum()
    s_est = (tot_cand / tot_cand.index.str[:2].map(agremiacao).map(tot_agr)).to_dict()
    cm["s_cm"] = (cm["votos"] + tau * cm["nr"].map(s_est).fillna(0)) / (agr_mun + tau)

    # votos esperados no resto: municipio COM apuracao local usa s_cm; sem, usa s_est
    cm["resto"] = [resto_agr.get((m, a), 0.0) * s
                   for m, a, s in zip(cm["cd_municipio"], cm["agr"], cm["s_cm"])]
    resto_c = cm.groupby("nr")["resto"].sum()
    mun_com = set(cm["cd_municipio"])
    resto_sem = {a: sum(v for (m, aa), v in resto_agr.items()
                        if aa == a and m not in mun_com) for a in pr.index}

    top3 = (cm.sort_values("votos", ascending=False).groupby("nr")
            .apply(lambda g: [(m_, int(v_)) for m_, v_ in
                              zip(g["cd_municipio"].head(3), g["votos"].head(3))],
                   include_groups=False).to_dict())
    out = []
    for nr, v_ap in tot_cand.items():
        a = agremiacao(nr[:2])
        esp = float(v_ap + resto_c.get(nr, 0) + resto_sem.get(a, 0) * s_est.get(nr, 0))
        agr_esp = float(tot_agr[a]) + sum(v for (m, aa), v in resto_agr.items() if aa == a)
        w_ap = float(v_ap / tot_agr[a]) if tot_agr[a] > 0 else 0
        w_esp = esp / agr_esp if agr_esp > 0 else w_ap
        out.append({"nr": nr, "vento": 100 * (w_esp - w_ap),
                    "pct_apurado": 100 * v_ap / esp if esp > 0 else 100,
                    "top3": top3.get(nr, [])})
    return pd.DataFrame(out)
