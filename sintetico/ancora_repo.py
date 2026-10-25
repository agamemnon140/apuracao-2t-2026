"""Ancoras por urna reconstruidas do proprio repo (docs/dados), sem os parquets do D:.

Duas ancoras com a MESMA ordem de linhas (os indices das observacoes do crawler sao
compartilhados pelos dois needles):

  ancora_2026.parquet     needle B: 2o turno de 2022 andado pela demografia = proj26
                          (a projecao da ancora original, gravada por web/gera_estatico)
  ancora_t1_2026.parquet  needle A: 1o turno de 2026 na mesma urna (pr26t1), terceiros
                          divididos na proporcao local (a_ed = log(Lula/Flavio)); o
                          intercepto do needle aprende a transferencia real na noite

Covariaveis: as 8 do perfil TSE (pf: % fem, 16-24, 25-39, 40-59, 60+, fund, medio, sup),
padronizadas, no lugar das 25 do sintetico (que estao so no D:). Urna sem 1o turno (nova,
anulada) herda local -> municipio -> UF. ordem_hist entra se baseline/carimbos_presidente_2026_t1
existir (pipeline.carimbos 2026 PRESIDENTE 1); senao o needle usa 0,5 (uniforme).

Tambem grava sintetico/abst_base.json: abstencao esperada (1o turno 2026 e 2o turno 2022)
por UF e municipio, para o painel de abstencao.

Uso:  .venv/Scripts/python -m sintetico.ancora_repo
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

from .caminhos import BASELINE, SAIDA, UFS

RAIZ = Path(__file__).resolve().parents[1]
DD = RAIZ / "docs" / "dados"
PF = ["fem", "i16_24", "i25_39", "i40_59", "i60", "fund", "medio", "sup"]
CHAVE = ["uf", "cd_mun", "zona", "secao"]


def sig(x):
    return 1.0 / (1.0 + np.exp(-np.asarray(x, dtype=float)))


def lo(a, b):
    return np.log((a + .5) / (b + .5))


def le_municipios() -> tuple[dict, dict]:
    """cd -> (uf, nome) e cd -> dados agregados do municipio (uf/{UF}.json)."""
    nomes, mun = {}, {}
    for uf in UFS + ["ZZ"]:
        p = DD / "uf" / f"{uf}.json"
        if not p.exists():
            continue
        u = json.loads(p.read_text("utf-8"))
        for cd, m in u["mun"].items():
            nomes[int(cd)] = (uf, m.get("nome", ""))
            mun[int(cd)] = m
    return nomes, mun


def le_urnas(nomes: dict) -> pd.DataFrame:
    # pr26t1 vem na ordem do RESULTADO real (meta.pr.r26.t1: 22, 13, 70, ...), nao na da config
    meta = json.loads((DD / "meta.json").read_text("utf-8"))
    ordem26 = [c[0] for c in meta["pr"]["r26"]["t1"]]
    i13, i22 = ordem26.index("13"), ordem26.index("22")
    n26 = len(ordem26)
    outros = [i for i in range(n26) if i not in (i13, i22)]
    ordem22 = [c[0] for c in meta["pr"]["2022"]["t2"]]
    assert ordem22[:2] == ["13", "22"], ordem22
    ordem21 = [c[0] for c in meta["pr"]["2022"]["t1"]]
    assert ordem21[:2] == ["13", "22"] and len(ordem21) == 11, ordem21
    rows = []
    dirs = sorted((d for d in (DD / "sec").iterdir() if d.name.isdigit()), key=lambda d: int(d.name))
    for d in dirs:
        cd = int(d.name)
        uf, _ = nomes.get(cd, ("??", ""))
        for f in sorted(d.glob("*.json"), key=lambda f: int(f.stem)):
            z = int(f.stem)
            s = json.loads(f.read_text("utf-8"))
            c = s["cols"]
            ip, c22, c26, ipf, c21 = (c.index("proj26"), c.index("pr22t2"), c.index("pr26t1"), c.index("pf"),
                                      c.index("pr22t1"))
            for r in s["rows"]:
                pj = r[ip] or [0, 0, 0, 0, 0]
                p22 = r[c22] if r[c22] else [None] * 5
                q = r[c21]
                p21 = [q[0], q[1], sum(q[2:11]), q[11], q[12], q[13]] if q else [None] * 6
                p26 = r[c26]
                t1 = ([p26[i13], p26[i22], sum(p26[i] for i in outros), p26[n26], p26[n26 + 1], p26[n26 + 2]]
                      if p26 else [None] * 6)
                pf = [None if x is None else float(x) for x in r[ipf]] if r[ipf] else [None] * 8
                rows.append((uf, cd, z, int(r[0]), int(r[1]), int(r[2] or 0), int(r[3] or 1), r[4], int(r[5] or 0),
                             *pj, *p22, *t1, *pf, *p21))
    cols = (["uf", "cd_mun", "zona", "secao", "nr_local", "aptos22", "n_agregadas", "nivel_ancora", "aptos",
             "b_esq", "b_dir", "b_out", "b_bn", "b_abst",
             "t22_esq", "t22_dir", "t22_br", "t22_nu", "t22_abst",
             "t1_esq", "t1_dir", "t1_out", "t1_br", "t1_nu", "t1_abst"] + [f"pf_{k}" for k in PF]
            + ["t21_esq", "t21_dir", "t21_out", "t21_br", "t21_nu", "t21_abst"])
    df = pd.DataFrame(rows, columns=cols)
    for c in cols[8:]:
        df[c] = pd.to_numeric(df[c], errors="coerce").astype(float)
    return df


def cascata(df: pd.DataFrame, cols: list[str], w: str) -> np.ndarray:
    """Preenche NaN de cols com a media ponderada local -> municipio -> UF -> nacional."""
    nivel = np.where(df[cols[0]].notna(), "secao", "nacional").astype(object)
    for rot, nv in [("local", ["uf", "cd_mun", "zona", "nr_local"]), ("municipio", ["uf", "cd_mun"]), ("uf", ["uf"])]:
        falta = df[cols[0]].isna()
        if not falta.any():
            break
        ok = df[~falta]
        ww = ok[w].clip(lower=1e-9)
        keys = [ok[k] for k in nv]
        med = ok[cols].mul(ww, axis=0).groupby(keys).sum().div(ww.groupby(keys).sum(), axis=0)
        vals = df.loc[falta, nv].merge(med, left_on=nv, right_index=True, how="left")[cols]
        vals.index = df.index[falta]
        achou = vals[cols[0]].notna().to_numpy()
        df.loc[vals.index[achou], cols] = vals.loc[achou].to_numpy()
        nivel[np.flatnonzero(falta.to_numpy())[achou]] = rot
    for c in cols:
        if df[c].isna().any():
            ok = df[c].notna()
            df[c] = df[c].fillna(np.average(df.loc[ok, c], weights=df.loc[ok, w].clip(lower=1e-9)))
    return nivel


def monta(df: pd.DataFrame, pref: str) -> pd.DataFrame:
    """Ancora (a_ed, a_part, a_out, a_bn) a partir das contagens pref_* de cada urna."""
    e, d, o = df[f"{pref}_esq"], df[f"{pref}_dir"], df[f"{pref}_out"]
    bn = (df[f"{pref}_bn"] if f"{pref}_bn" in df else df[f"{pref}_br"] + df[f"{pref}_nu"])
    val = e + d + o
    a = df[CHAVE + ["nr_local", "aptos", "aptos22", "n_agregadas", "nivel_ancora"]].copy()
    a["a_ed"] = lo(e, d)
    a["a_part"] = lo(val, (df["aptos"] - val).clip(lower=0))
    a["a_out"] = lo(o, e + d)
    a["a_bn"] = lo(bn, val)
    a["_w"] = val
    a["_peso"] = df["aptos"]
    return a


B22 = Path("C:/Users/Henrique/Documents/eleicoes-2026/dados-secao/sintetico/base_2022.parquet")
EXTRA = ["log_renda", "pct_branca", "pct_preta", "pct_rural", "log_pop_mun", "hierarquia_num", "em_rm",
         "pct_evangelica", "pct_sem_religiao", "vab_agro", "vab_industria", "vab_adm",
         "pct_ocup_agro", "pct_ocup_bens", "pct_ocup_comercio"]


def covariaveis_2022(df: pd.DataFrame) -> pd.DataFrame:
    """As covariaveis do sintetico que nao sao perfil (renda, raca, rural, porte, regiao, religiao,
    atividade), lidas da base de 2022 que existe nesta maquina, casadas por secao (a maioria das urnas
    de 2026 tem par) e herdadas local -> municipio -> UF nas demais. Padronizadas; NaN -> 0."""
    b = pd.read_parquet(B22, columns=["uf", "cd_municipio_tse", "zona", "secao", "regiao"] + EXTRA)
    b = b.rename(columns={"cd_municipio_tse": "cd_mun"})
    for reg in ["N", "NE", "CO", "S"]:
        b[f"reg_{reg}"] = (b["regiao"] == reg).astype(float)
    cols = EXTRA + [f"reg_{r}" for r in ["N", "NE", "CO", "S"]]
    for k in ["cd_mun", "zona", "secao"]:
        b[k] = b[k].astype(int)
    b["uf"] = b["uf"].str.upper()
    m = df[CHAVE + ["nr_local", "aptos"]].merge(b[CHAVE + cols].drop_duplicates(CHAVE), on=CHAVE, how="left")
    for c in cols:
        m[c] = m[c].astype(float)
    casadas = m[cols[0]].notna().mean()
    nivel = cascata(m, cols, "aptos")
    print(f"sintetico 2022: {100 * casadas:.1f}% das urnas casadas por secao; niveis: "
          + ", ".join(f"{k} {v:,}" for k, v in pd.Series(nivel).value_counts().items()))
    out = {}
    for c in cols:
        v = m[c]
        out[f"x_{c}"] = ((v - v.mean()) / (v.std() or 1.0)).fillna(0.0).astype(np.float32)
    return pd.DataFrame(out)


def main() -> int:
    t0 = time.time()
    nomes, mun = le_municipios()
    df = le_urnas(nomes)
    print(f"urnas lidas: {len(df):,}  aptos 2026: {df['aptos'].sum():,.0f}  [{time.time() - t0:.0f}s]", flush=True)
    print(f"sem 1o turno 2026: {df['t1_esq'].isna().sum():,}  sem 2022 t2: {df['t22_esq'].isna().sum():,}  "
          f"sem perfil: {df['pf_fem'].isna().sum():,}")

    # 2022 por urna (1o e 2o turno; replay analogo do needle A)
    df[CHAVE + ["aptos22", "t21_esq", "t21_dir", "t21_out", "t21_br", "t21_nu", "t21_abst",
                "t22_esq", "t22_dir", "t22_br", "t22_nu", "t22_abst"]].to_parquet(SAIDA / "votos_2022.parquet", index=False)

    # voto do 1o turno por urna (para o replay de 04/10 e para o painel)
    df[CHAVE + ["aptos", "t1_esq", "t1_dir", "t1_out", "t1_br", "t1_nu", "t1_abst"]].to_parquet(
        SAIDA / "votos_t1_2026.parquet", index=False)

    # covariaveis: perfil padronizado (NaN -> 0 = media)
    X = {}
    for k in PF:
        v = df[f"pf_{k}"]
        X[f"x_pf_{k}"] = ((v - v.mean()) / (v.std() or 1.0)).fillna(0.0).astype(np.float32)
    X = pd.DataFrame(X)
    if "--cov" in sys.argv:
        X = pd.concat([X, covariaveis_2022(df)], axis=1)
        print(f"covariaveis: {X.shape[1]} (8 do perfil 2026 + {X.shape[1] - 8} do sintetico de 2022)")

    ordem = None
    car = BASELINE / "carimbos_presidente_2026_t1.parquet"
    if car.exists():
        c = pd.read_parquet(car, columns=["uf", "cd_municipio", "zona", "secao", "prim_tot"])
        c["cd_mun"] = c["cd_municipio"].astype(int)
        c = c.dropna(subset=["prim_tot"])
        c["ordem_hist"] = c.groupby("cd_mun")["prim_tot"].rank(pct=True, method="average")
        ordem = c[CHAVE + ["ordem_hist"]].drop_duplicates(CHAVE)
        print(f"ordem de chegada de 04/10/2026: {len(ordem):,} secoes com carimbo")

    for nome, pref in [("ancora_2026.parquet", "b"), ("ancora_t1_2026.parquet", "t1")]:
        a = monta(df, pref)
        if pref == "t1":
            a["nivel_ancora"] = cascata(a, ["a_ed", "a_part", "a_out", "a_bn"], "_peso")
        else:
            cascata(a, ["a_ed", "a_part", "a_out", "a_bn"], "_peso")
        a = pd.concat([a.reset_index(drop=True), X.reset_index(drop=True)], axis=1)
        if ordem is not None:
            a = a.merge(ordem, on=CHAVE, how="left")
            a["ordem_hist"] = a["ordem_hist"].fillna(0.5)
        a["aptos_est"] = a["aptos"]
        a = a.drop(columns=["_w", "_peso"])
        assert len(a) == len(df)
        val = a["aptos"].to_numpy(float) * sig(a["a_part"])
        dois = val * (1 - sig(a["a_out"]))
        sh = float((dois * sig(a["a_ed"])).sum() / dois.sum())
        comp = float(val.sum() / a["aptos"].sum())
        if pref == "b":
            bruto = df["b_esq"].sum() / (df["b_esq"].sum() + df["b_dir"].sum())
        else:
            bruto = df["t1_esq"].sum() / (df["t1_esq"].sum() + df["t1_dir"].sum())
        print(f"{nome}: esquerda a dois {100 * sh:.2f}% (contagem bruta {100 * bruto:.2f}%)  "
              f"validos/aptos {100 * comp:.2f}%  NaN a_ed={a['a_ed'].isna().sum()} a_part={a['a_part'].isna().sum()}")
        a.to_parquet(SAIDA / nome, index=False)
        print(f"  gravado {SAIDA / nome} ({(SAIDA / nome).stat().st_size / 1e6:.0f} MB)", flush=True)

    # abstencao esperada por UF e municipio (painel)
    br = json.loads((DD / "br.json").read_text("utf-8"))
    out = {"uf": {}, "mun": {}}
    for uf, u in br["ufs"].items():
        p26, p22 = u["pr26t1"], u["pr22t2"]
        out["uf"][uf] = {"aptos26": u["aptos26"], "abst_t1": round(100 * p26[-1] / u["aptos26"], 2),
                         "abst_t2_2022": round(100 * p22[-1] / sum(p22), 2) if sum(p22) else None}
    for cd, m in mun.items():
        p26, p22 = m.get("pr26t1"), m.get("pr22t2")
        uf, nm = nomes[cd]
        out["mun"][str(cd)] = {"uf": uf, "nome": nm, "aptos26": m.get("aptos26"),
                               "abst_t1": round(100 * p26[-1] / m["aptos26"], 2) if p26 and m.get("aptos26") else None,
                               "abst_t2_2022": round(100 * p22[-1] / sum(p22), 2) if p22 and sum(p22) else None}
    (SAIDA / "abst_base.json").write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), "utf-8")
    print(f"abst_base.json: {len(out['uf'])} UFs, {len(out['mun']):,} municipios  [{time.time() - t0:.0f}s]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
