import json
import numpy as np
import pandas as pd

S = "C:/Users/Henrique/AppData/Local/Temp/claude/C--Users-Henrique/12f2fc25-eb46-4286-90f4-10c26e647ab9/scratchpad"
D = "C:/Users/Henrique/Documents/eleicoes-dados-2t"
R = "C:/Users/Henrique/Documents/apuracao-2t-2026"
CH = ["uf", "cd_mun", "zona", "secao"]
v = pd.read_parquet(f"{D}/sintetico/votos_t1_2026.parquet").dropna(subset=["t1_esq"])
c = pd.read_parquet(f"{D}/baseline/carimbos_presidente_2026_t1.parquet", columns=["uf", "cd_municipio", "zona", "secao", "prim_tot"])
c["cd_mun"] = c["cd_municipio"].astype(int)
v = v.merge(c[CH + ["prim_tot"]].drop_duplicates(CH), on=CH, how="left").dropna(subset=["prim_tot"])
v["prim_tot"] = pd.to_datetime(v["prim_tot"])
m = pd.read_parquet(f"{S}/mun_final.parquet")[["uf", "cd", "e", "d", "e1", "d1"]].rename(columns={"cd": "cd_mun"})
m = m[(m.e + m.d > 0) & (m.e1 + m.d1 > 0)]
lg = lambda p: np.log(p / (1 - p))
m["swing"] = lg((m.e + .5) / (m.e + m.d + 1)) - lg((m.e1 + .5) / (m.e1 + m.d1 + 1))
m["esc"] = (m.e + m.d) / (m.e1 + m.d1)
v = v.merge(m[["uf", "cd_mun", "swing", "esc"]], on=["uf", "cd_mun"], how="inner")
p1 = (v.t1_esq + .5) / (v.t1_esq + v.t1_dir + 1)
p2 = 1 / (1 + np.exp(-(lg(p1) + v.swing)))
val2 = (v.t1_esq + v.t1_dir) * v.esc
v["L2"] = val2 * p2
v["F2"] = val2 - v.L2
v = v.sort_values("prim_tot").reset_index(drop=True)
n = len(v)
cum = pd.DataFrame({"pct": 100 * np.arange(1, n + 1) / n, "hora": v.prim_tot,
                    "cf2": 100 * v.L2.cumsum() / (v.L2.cumsum() + v.F2.cumsum()),
                    "real1": 100 * v.t1_esq.cumsum() / (v.t1_esq.cumsum() + v.t1_dir.cumsum())})
idx = np.unique(np.r_[np.arange(0, 2000), np.linspace(0, n - 1, 4000).astype(int)])
cum.iloc[idx].to_csv(f"{S}/curva_contrafactual.csv", index=False)
fin2 = 100 * v.L2.sum() / (v.L2.sum() + v.F2.sum())
fin1 = 100 * v.t1_esq.sum() / (v.t1_esq.sum() + v.t1_dir.sum())
print(f"secoes {n:,}  final sintetico 2T {fin2:.2f}%  final 1T {fin1:.2f}%")
for pct in (0.5, 1, 2, 5, 10, 20, 30, 50, 70, 90):
    k = int(round(n * pct / 100)) - 1
    print(f"{pct:5.1f}% ({v.prim_tot.iloc[k]:%H:%M})  contrafactual 2T {cum.cf2.iloc[k]:6.2f}   1T real {cum.real1.iloc[k]:6.2f}")
h = json.load(open(f"{R}/docs/dados/live/historico.json", encoding="utf-8"))
pts = [(p["t"], p["tse_pct"], p["tse_esq"]) for p in h if p.get("tse_pct") is not None]
json.dump({"pts": pts, "fin2": fin2, "fin1": fin1}, open(f"{S}/pontos_reais_2t.json", "w"))
print("pontos reais 2T:", len(pts), pts[:2], "...", pts[-2:])
