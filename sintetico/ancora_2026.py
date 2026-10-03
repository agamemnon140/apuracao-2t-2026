"""Ancora por urna: o ponto de partida unico de alvo, needle e desvio.

Para cada urna do ano-alvo (2026, ou 2022 no modo de calibracao):

  z_ed   = log((esq+.5)/(dir+.5))                  2o turno do ano-base, na mesma secao
  z_part = log((esq+dir+.5)/(aptos-esq-dir+.5))    votos nos dois vs "nenhum" (abst+branco+nulo)
  drift_ed   = logit(q_alvo) - logit(q_base),  q = p_lula/(p_lula+p_bolsonaro) do sintetico
  drift_part = logit(1-p_nenhum_alvo) - logit(1-p_nenhum_base)
  a_ed = z_ed + drift_ed ;  a_part = z_part + drift_part

Ou seja: o resultado real do 2o turno anterior naquela secao, andado pela demografia.
Urna sem par no ano-base herda a media ponderada do LOCAL de votacao, depois do
municipio, depois da UF (coluna `nivel_ancora`). Secoes agregadas sao somadas na
principal: a urna e a unidade em que o voto chega.

Leva junto as 25 covariaveis do sintetico padronizadas (x_*), usadas pelo needle para
prever o desvio de urnas ainda nao apuradas a partir das ja apuradas.

Modos:
  (padrao) 2026: base = 2022 T2; drift = pred_2026 - pred_2022; universo = universo_2026
  --calib  2022: base = 2018 T2; drift = pred_2022 - pred_2018; universo = urnas de 2022
           (carimbos), para calibrar o needle no replay sem olhar a resposta.

Saidas: sintetico/ancora_2026.parquet | sintetico/ancora_2022_calib.parquet

Uso:  .venv/Scripts/python -m sintetico.ancora_2026 [--calib]
"""
from __future__ import annotations

import json
import sys

import numpy as np
import pandas as pd

from .caminhos import BASELINE, SAIDA
from .modelo import monta_xy

CHAVE = ["uf", "cd_mun", "zona", "secao"]
NIVEIS = [["uf", "cd_mun", "zona", "nr_local"], ["uf", "cd_mun"], ["uf"]]
ROTULO = {0: "local", 1: "municipio", 2: "uf"}


def logit(p):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


def sig(x):
    return 1.0 / (1.0 + np.exp(-np.asarray(x, dtype=float)))


def urnas_2026() -> pd.DataFrame:
    u = pd.read_parquet(SAIDA / "universo_2026.parquet")
    u["secao"] = np.where(u["secao_principal"] > 0, u["secao_principal"], u["secao"])
    return (u.groupby(CHAVE, as_index=False)
            .agg(nr_local=("nr_local", "first"), aptos=("aptos", "sum"),
                 aptos_est=("aptos_est", "sum"), n_agregadas=("secao", "size")))


def urnas_2022() -> pd.DataFrame:
    c = pd.read_parquet(BASELINE / "carimbos_presidente_2022_t1.parquet",
                        columns=["uf", "cd_municipio", "zona", "secao", "aptos"])
    c["cd_mun"] = c["cd_municipio"].astype(int)
    loc = pd.read_parquet(SAIDA / "alvo_2022_t2.parquet",
                          columns=["uf", "cd_municipio", "zona", "secao", "nr_local"])
    loc["cd_mun"] = loc["cd_municipio"].astype(int)
    c = c.merge(loc[CHAVE + ["nr_local"]], on=CHAVE, how="left")
    c["nr_local"] = c["nr_local"].fillna(-1).astype(np.int64)
    c["aptos_est"] = c["aptos"]
    c["n_agregadas"] = 1
    return c[CHAVE + ["nr_local", "aptos", "aptos_est", "n_agregadas"]]


def resultado_base(ano: int) -> pd.DataFrame:
    a = pd.read_parquet(SAIDA / f"alvo_{ano}_t2.parquet")
    a["cd_mun"] = a["cd_municipio"].astype(int)
    esq, dir_, apt = a["lula"].astype(float), a["bolsonaro"].astype(float), a["aptos"].astype(float)
    return pd.DataFrame({**{k: a[k] for k in CHAVE},
                         "z_ed": np.log((esq + .5) / (dir_ + .5)),
                         "z_part": np.log((esq + dir_ + .5) / ((apt - esq - dir_).clip(lower=0) + .5)),
                         "peso_base": esq + dir_,
                         "base_esq": a["lula"], "base_dir": a["bolsonaro"], "base_aptos": a["aptos"]})


def pred_com_coef(ano_coef: int, ano_demo: int) -> pd.DataFrame:
    """Probabilidades por secao com os coeficientes de `ano_coef` sobre a demografia de
    `ano_demo`. Todos os modelos usam a padronizacao de 2022, entao isso e direto."""
    M = json.loads((SAIDA / f"modelo_{ano_coef}.json").read_text("utf-8"))
    base = (pd.read_parquet(SAIDA / f"base_{ano_demo}.parquet").drop(columns=["cd_mun"])
            .rename(columns={"cd_municipio_tse": "cd_mun"}))
    Xz, _, cols, _, _ = monta_xy(base, M["mu"], M["sd"])
    eta = Xz @ np.array(M["coef"]).T + np.array(M["intercept"])
    eta -= eta.max(1, keepdims=True)
    p = np.exp(eta); p /= p.sum(1, keepdims=True)
    out = base[CHAVE].copy()
    out["p_lula"], out["p_bolsonaro"], out["p_nenhum"] = p[:, 0], p[:, 1], p[:, 2]
    return out


def resultado_t1(ano: int) -> pd.DataFrame:
    """1o turno do ano-base por secao: terceiros e brancos+nulos (sem deriva demografica,
    o sintetico nao os modela). Servem de ancora para as dimensoes 'out' e 'bn' do needle."""
    b = pd.read_parquet(BASELINE / f"presidente_secao_{ano}.parquet")
    b["cd_mun"] = b["cd_municipio"].astype(int)
    dois = (b["t1_esq"] + b["t1_dir"]).astype(float)
    val = dois + b["t1_outros"]
    return pd.DataFrame({**{k: b[k] for k in CHAVE},
                         "a_out": np.log((b["t1_outros"] + .5) / (dois + .5)),
                         "a_bn": np.log((b["t1_branco"] + b["t1_nulo"] + .5) / (val + .5)),
                         "_w_t1": val})


def ordem_historica(ano: int) -> pd.DataFrame:
    """Percentil de chegada da secao DENTRO do municipio na noite de `ano` (0 = primeira).
    Prior fraco de quem o feed municipal ja contou: a ordem se repete so em parte."""
    c = pd.read_parquet(BASELINE / f"carimbos_presidente_{ano}_t1.parquet",
                        columns=["uf", "cd_municipio", "zona", "secao", "prim_tot"])
    c["cd_mun"] = c["cd_municipio"].astype(int)
    c = c.dropna(subset=["prim_tot"])
    c["ordem_hist"] = c.groupby("cd_mun")["prim_tot"].rank(pct=True, method="average")
    return c[CHAVE + ["ordem_hist"]]


def deriva(ano_base: int, ano_alvo: int) -> pd.DataFrame:
    """Deriva SO demografica: mesmos coeficientes (os do ano-base), demografia muda.
    2026: pred_2026 ja e coef 2022 sobre a demografia 2026. Calibracao: coef 2018 sobre
    a demografia 2022 -- nunca pred_2022, que foi ajustado nos votos de 2022 (vazamento)."""
    def le(ano):
        p = pd.read_parquet(SAIDA / f"pred_{ano}.parquet")
        return p.rename(columns={"cd_municipio_tse": "cd_mun"})[CHAVE + ["p_lula", "p_bolsonaro", "p_nenhum"]]
    alvo = le(ano_alvo) if ano_alvo == 2026 else pred_com_coef(ano_base, ano_alvo)
    m = alvo.merge(le(ano_base), on=CHAVE, suffixes=("_a", "_b"))

    def q(l, b):
        return logit(l / (l + b))
    return pd.DataFrame({**{k: m[k] for k in CHAVE},
                         "drift_ed": q(m["p_lula_a"], m["p_bolsonaro_a"]) - q(m["p_lula_b"], m["p_bolsonaro_b"]),
                         "drift_part": logit(1 - m["p_nenhum_a"]) - logit(1 - m["p_nenhum_b"])})


def covariaveis() -> pd.DataFrame:
    M = json.loads((SAIDA / "modelo_2022.json").read_text("utf-8"))
    base = (pd.read_parquet(SAIDA / "base_2022.parquet").drop(columns=["cd_mun"])
            .rename(columns={"cd_municipio_tse": "cd_mun"}))
    Xz, _, cols, _, _ = monta_xy(base, M["mu"], M["sd"])
    assert cols == M["cols"], "colunas do modelo mudaram"
    X = pd.DataFrame(Xz.astype(np.float32), columns=[f"x_{c}" for c in cols])
    return pd.concat([base[CHAVE].reset_index(drop=True), X], axis=1)


def cascata(df: pd.DataFrame, cols: list[str], peso: str) -> np.ndarray:
    """Preenche NaN de `cols` (no lugar) com a media ponderada do grupo, nivel a nivel
    (local -> municipio -> UF). Devolve o rotulo do nivel usado em cada linha."""
    nivel = np.where(df[cols[0]].notna(), "secao", "nacional").astype(object)
    for i, nv in enumerate(NIVEIS):
        falta = df[cols[0]].isna().to_numpy()
        if not falta.any():
            break
        ok = df.loc[~falta]
        w = ok[peso].clip(lower=1e-9)
        chave_ok = [ok[k] for k in nv]
        med = ok[cols].mul(w, axis=0).groupby(chave_ok).sum().div(w.groupby(chave_ok).sum(), axis=0)
        alvo = df.loc[falta, nv]
        vals = alvo.merge(med, left_on=nv, right_index=True, how="left")[cols]
        vals.index = df.index[falta]
        achou = vals[cols[0]].notna().to_numpy()
        df.loc[vals.index[achou], cols] = vals.loc[achou].to_numpy()
        nivel[np.flatnonzero(falta)[achou]] = ROTULO[i]
    return nivel


def monta_ancora(calib: bool = False) -> pd.DataFrame:
    ano_base, ano_alvo = (2018, 2022) if calib else (2022, 2026)
    u = urnas_2022() if calib else urnas_2026()
    u = u.merge(resultado_base(ano_base), on=CHAVE, how="left")
    u = u.merge(deriva(ano_base, ano_alvo), on=CHAVE, how="left")
    u = u.merge(covariaveis(), on=CHAVE, how="left")
    u = u.merge(ordem_historica(ano_base), on=CHAVE, how="left")
    u["ordem_hist"] = u["ordem_hist"].fillna(0.5)
    u = u.merge(resultado_t1(ano_base), on=CHAVE, how="left")
    u["_w_t1"] = u["_w_t1"].fillna(0.0)
    cascata(u, ["a_out", "a_bn"], "_w_t1")
    for c in ["a_out", "a_bn"]:
        ok = u[c].notna()
        u[c] = u[c].fillna(np.average(u.loc[ok, c], weights=u.loc[ok, "_w_t1"].clip(lower=1e-9)))
    u = u.drop(columns=["_w_t1"])
    u["peso_base"] = u["peso_base"].fillna(0)
    u["_w"] = u["peso_base"].where(u["z_ed"].notna(), 0.0)

    u["nivel_ancora"] = cascata(u, ["z_ed"], "_w")
    cascata(u, ["z_part"], "aptos")
    cascata(u, ["drift_ed", "drift_part"], "aptos")
    u[["drift_ed", "drift_part"]] = u[["drift_ed", "drift_part"]].fillna(0.0)   # ZZ: sem sintetico
    xc = [c for c in u.columns if c.startswith("x_")]
    u[xc] = u[xc].astype(np.float64)
    cascata(u, xc, "aptos")
    u[xc] = u[xc].fillna(0.0).astype(np.float32)                                # ZZ: media nacional
    for c in ["z_ed", "z_part"]:
        if u[c].isna().any():
            ok = u[c].notna()
            u[c] = u[c].fillna(np.average(u.loc[ok, c], weights=u.loc[ok, "aptos"]))

    u["a_ed"] = u["z_ed"] + u["drift_ed"]
    u["a_part"] = u["z_part"] + u["drift_part"]
    return u.drop(columns=["_w"])


def resumo(u: pd.DataFrame) -> None:
    apt = u["aptos"].to_numpy(float)

    def share(ed, part):
        v = apt * sig(part)
        return float((v * sig(ed)).sum() / v.sum())
    print(f"urnas: {len(u):,}  aptos: {apt.sum():,.0f}")
    print(f"esquerda nos validos a dois: ancora sem deriva {100 * share(u['z_ed'], u['z_part']):.2f}%  "
          f"com deriva {100 * share(u['a_ed'], u['a_part']):.2f}%")
    print(f"votos nos dois / aptos: sem deriva {100 * float((apt * sig(u['z_part'])).sum() / apt.sum()):.2f}%  "
          f"com deriva {100 * float((apt * sig(u['a_part'])).sum() / apt.sum()):.2f}%")
    so = u[u["nivel_ancora"] == "secao"]
    real = so["base_esq"].sum() / (so["base_esq"].sum() + so["base_dir"].sum())
    ba = so["base_aptos"].to_numpy(float)
    rec = float((ba * sig(so["z_part"]) * sig(so["z_ed"])).sum() / (ba * sig(so["z_part"])).sum())
    print(f"conferencia nas urnas pareadas: votos reais do ano-base {100 * real:.2f}%  "
          f"ancora sem deriva reconstruida {100 * rec:.2f}%")
    t = pd.crosstab(u["uf"], u["nivel_ancora"], values=u["aptos"], aggfunc="sum", normalize="index")
    print("% dos aptos por nivel de ancora:")
    print((100 * t).round(1).fillna(0).T.to_string())


def main() -> int:
    calib = "--calib" in sys.argv
    u = monta_ancora(calib)
    resumo(u)
    nome = "ancora_2022_calib.parquet" if calib else "ancora_2026.parquet"
    u.to_parquet(SAIDA / nome, index=False)
    print(f"gravado {nome} ({(SAIDA / nome).stat().st_size / 1e6:.0f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
