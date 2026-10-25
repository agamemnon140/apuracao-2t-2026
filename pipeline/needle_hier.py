"""Needle hierarquico: projeta o resultado final de baixo para cima, urna a urna.

Toda urna parte da ANCORA (sintetico/ancora_2026.py): o 2o turno anterior naquela secao,
andado pela demografia. Na noite, cada urna apurada revela um DESVIO em relacao a sua
ancora; o needle aprende esses desvios e os transporta para as urnas que ainda nao
chegaram, pelas semelhancas que importam:

  desvio previsto(j) = X_j . beta            (demografia: 25 covariaveis do sintetico, ridge)
                     + u[UF]                 (estado, encolhido para 0)
                     + m[municipio]          (encolhido para 0)
                     + l[local de votacao]   (encolhido para 0)

Sem nenhum voto apurado, todos os desvios sao 0 e o needle = ancora (a projecao
demografica). Quatro dimensoes, todas em log-odds:

  ed    esq vs dir                       peso: votos nos dois
  part  validos vs aptos                 peso: aptos
  out   terceiros vs os dois (1o turno)  peso: validos
  bn    brancos+nulos vs validos         peso: comparecimento

Duas fontes de observacao, no mesmo estimador:
  - urnas individuais (boletim de urna raspado): desvio exato daquela urna;
  - totais municipais do feed (-u): o que o municipio ja apurou ALEM das urnas raspadas
    vira uma pseudo-observacao.

Quais urnas nao raspadas o feed ja contou? Nao se sabe; estima-se p_cont(j): mistura de
"as primeiras na ordem de chegada da eleicao anterior" (peso lam_ordem) com "qualquer uma"
(uniforme). A ancora da pseudo-observacao e a media das urnas ponderada por p_cont, e o
que falta projetar em cada urna e (1 - p_cont). Sem isso, a apuracao enviesada dentro de
cada cidade (centro primeiro, periferia depois) contamina o efeito municipal.

Uso: from pipeline.needle_hier import Needle; nd = Needle(ancora); r = nd.estima(obs, feed)
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

DIMS = ["ed", "part", "out", "bn"]


def sig(x):
    return 1.0 / (1.0 + np.exp(-x))


def logit(p):
    p = np.clip(p, 1e-9, 1 - 1e-9)
    return np.log(p / (1 - p))


@dataclass
class Params:
    # calibrados no replay do 1o turno de 2022 (probe/calibra_hier.py, grade em
    # sintetico/calib_hier_grade_t1.csv): melhor erro medio com crawl parcial (rho 0,6)
    L: float = 0.005         # ridge das covariaveis, fracao do peso total esperado
    K0: float = 5e3          # prior do intercepto (desvio nacional) em votos-equivalentes
    K_UF: float = 2e5
    K_MUN: float = 300.0
    K_LOC: float = 1500.0
    lam_ordem: float = 1.0   # confianca na ordem de chegada historica (0 = uniforme)
    iters: int = 2           # passadas de backfitting (beta <-> efeitos)
    usa_cov: bool = True


class Needle:
    def __init__(self, anc: pd.DataFrame, turno: int = 1):
        self.anc = anc.reset_index(drop=True)
        self.turno = turno
        self.dims = DIMS if turno == 1 else ["ed", "part", "bn"]
        a = self.anc
        self.n = len(a)
        self.aptos = a["aptos"].to_numpy(float)
        self.A = {d: a[f"a_{d}"].to_numpy(float) for d in DIMS}
        xc = [c for c in a.columns if c.startswith("x_")]
        # o nivel da propria ancora tambem e covariavel: o swing depende de onde se parte
        # (e o 'beta' do needle v1). Centrado e escalado como as demais.
        anc_cols = []
        for d in ["ed", "part"]:
            v = self.A[d]
            anc_cols.append((v - np.average(v, weights=self.aptos)) / (v.std() or 1.0))
        self.X = np.c_[np.ones(self.n), a[xc].to_numpy(float), np.column_stack(anc_cols)]
        self.uf_cod, self.ufs = pd.factorize(a["uf"])
        self.mun_cod, self.muns = pd.factorize(a["uf"] + ":" + a["cd_mun"].astype(str))
        self.loc_cod, _ = pd.factorize(a["cd_mun"].astype(str) + ":" + a["zona"].astype(str)
                                       + ":" + a["nr_local"].astype(str))
        self.n_uf, self.n_mun, self.n_loc = len(self.ufs), len(self.muns), int(self.loc_cod.max()) + 1
        self.mun_idx = {k: i for i, k in enumerate(self.muns)}
        self.urnas_mun = np.bincount(self.mun_cod, minlength=self.n_mun)
        ufm = np.zeros(self.n_mun, int)
        ufm[self.mun_cod] = self.uf_cod
        self.uf_de_mun = ufm
        self.mun_uf = np.array([k.split(":")[0] for k in self.muns])
        self.mun_cd = np.array([int(k.split(":")[1]) for k in self.muns])
        oh = a["ordem_hist"].to_numpy(float) if "ordem_hist" in a else np.full(self.n, 0.5)
        self.ordem = np.lexsort((oh, self.mun_cod))          # por municipio, depois chegada
        self.esp0 = self._proj({d: np.zeros(self.n) for d in DIMS})
        self.W_tot = {"ed": self.esp0["dois"].sum(), "part": self.aptos.sum(),
                      "out": self.esp0["val"].sum(), "bn": self.esp0["comp"].sum()}

    # ---- de desvios para votos
    def _proj(self, dev: dict) -> dict:
        """a_part vem do 2o turno anterior, que nao tem terceiros: sigma(a_part)*aptos ja e o
        TOTAL de validos esperado (comparecimento de 1o e 2o turno andam juntos). Os terceiros
        (a_out, fatia dos validos) vivem DENTRO dele."""
        val = self.aptos * sig(self.A["part"] + dev["part"])
        po = (np.clip(sig(self.A["out"] + dev["out"]), 0.0, 0.85) if "out" in self.dims
              else np.zeros(self.n))
        out = val * po
        dois = val - out
        esq = dois * sig(self.A["ed"] + dev["ed"])
        bn = val * np.exp(np.clip(self.A["bn"] + dev["bn"], None, 0.0))
        return {"val": val, "out": out, "dois": dois, "esq": esq, "dir": dois - esq, "bn": bn,
                "comp": val + bn}

    @staticmethod
    def _y(esq, dir_, out, bn, apt):
        val = esq + dir_ + out
        return {"ed": (np.log((esq + .5) / (dir_ + .5)), esq + dir_),
                "part": (np.log((val + .5) / (np.clip(apt - val, 0, None) + .5)), apt),
                "out": (np.log((out + .5) / (esq + dir_ + .5)), val),
                "bn": (np.log((bn + .5) / (val + .5)), val + bn)}

    def _bc(self, v):
        return np.bincount(self.mun_cod, v, minlength=self.n_mun)

    def p_contada(self, crawl: np.ndarray, k_m: np.ndarray, lam: float) -> np.ndarray:
        """P(urna nao raspada ja esta no total do feed), somando k_m por municipio."""
        nc = ~crawl
        n_nc = self._bc(nc.astype(float))
        k = np.clip(k_m, 0, n_nc)
        o = self.ordem
        nc_o = nc[o]
        mo = self.mun_cod[o]
        cum = np.cumsum(nc_o)
        ini = np.zeros(self.n_mun)
        # posicao (0..) da urna entre as nao raspadas do seu municipio, na ordem historica
        prim = np.searchsorted(mo, np.arange(self.n_mun))
        base = np.where(prim > 0, cum[np.clip(prim - 1, 0, None)], 0)
        base = np.where(prim > 0, base, 0)
        pos = cum - 1 - base[mo]
        dura = (pos < k[mo]).astype(float)
        unif = k[mo] / np.maximum(n_nc[mo], 1)
        p = np.zeros(self.n)
        p[o] = np.where(nc_o, lam * dura + (1 - lam) * unif, 0.0)
        return p

    # ---- estimacao
    def estima(self, obs: dict | None, feed: pd.DataFrame | None, p: Params | None = None) -> dict:
        """obs: {"idx": posicoes na ancora, "esq","dir","out","bn": contagens} (urnas raspadas).
        feed: por municipio: uf, cd_mun, esq, dir, out, bn, ea (aptos apurados), st, ts."""
        p = p or Params()
        n = self.n
        crawl = np.zeros(n, bool)
        rows = {"d": {d: [] for d in self.dims}, "w": {d: [] for d in self.dims},
                "X": [], "uf": [], "mun": [], "loc": []}
        tot = {k: np.zeros(self.n_mun) for k in ["esq", "dir", "out", "bn", "apt", "n"]}

        if obs is not None and len(obs["idx"]):
            idx = np.asarray(obs["idx"])
            crawl[idx] = True
            e, d_, o, b = (np.asarray(obs[k], float) for k in ["esq", "dir", "out", "bn"])
            ys = self._y(e, d_, o, b, self.aptos[idx])
            for dm in self.dims:
                y, w = ys[dm]
                rows["d"][dm].append(y - self.A[dm][idx]); rows["w"][dm].append(w)
            rows["X"].append(self.X[idx]); rows["uf"].append(self.uf_cod[idx])
            rows["mun"].append(self.mun_cod[idx]); rows["loc"].append(self.loc_cod[idx])
            mc = self.mun_cod[idx]
            for k, v in [("esq", e), ("dir", d_), ("out", o), ("bn", b), ("apt", self.aptos[idx]),
                         ("n", np.ones(len(idx)))]:
                tot[k] += np.bincount(mc, v, minlength=self.n_mun)

        # resto do feed por municipio (o que o feed ja tem alem das urnas raspadas)
        R = {k: np.zeros(self.n_mun) for k in ["esq", "dir", "out", "bn", "apt"]}
        st = np.full(self.n_mun, np.nan)
        ts = np.full(self.n_mun, np.nan)
        if feed is not None and len(feed):
            f = feed
            k_ = f["uf"].str.upper() + ":" + f["cd_mun"].astype(int).astype(str)
            m = k_.map(self.mun_idx)
            ok = m.notna().to_numpy()
            m = m[ok].astype(int).to_numpy()
            for k, col in [("esq", "esq"), ("dir", "dir"), ("out", "out"), ("bn", "bn"), ("apt", "ea")]:
                if col in f:
                    R[k][m] = np.clip(f[col].to_numpy(float)[ok] - tot[k][m], 0, None)
            if "st" in f:
                st[m] = f["st"].to_numpy(float)[ok]
                ts[m] = f["ts"].to_numpy(float)[ok]
        rv = R["esq"] + R["dir"] + R["out"]
        # quantas urnas nao raspadas o feed ja contou, por municipio
        tem_st = np.isfinite(st) & np.isfinite(ts) & (ts > 0)
        n_nc = self.urnas_mun - tot["n"]
        k_m = np.zeros(self.n_mun)
        k_m[tem_st] = np.clip(st[tem_st] - tot["n"][tem_st], 0, None) * (self.urnas_mun[tem_st] / ts[tem_st])
        sem = ~tem_st & (rv > 0)
        if sem.any():
            val_nc = self._bc(self.esp0["val"] * ~crawl)
            k_m[sem] = n_nc[sem] * np.clip(rv[sem] / np.maximum(val_nc[sem], 1), 0, 1)
        pc = self.p_contada(crawl, k_m, p.lam_ordem)

        tem = rv > 0
        if tem.any():
            mm = np.flatnonzero(tem)
            wv = self.esp0["val"] * pc
            sw = self._bc(wv)
            Xm = np.stack([self._bc(self.X[:, c] * wv) for c in range(self.X.shape[1])], 1) \
                / np.maximum(sw, 1e-9)[:, None]
            dois = np.maximum(self._bc(self.esp0["dois"] * pc), 1e-9)
            ag = {"ed": logit(self._bc(self.esp0["esq"] * pc) / dois),
                  "part": logit(sw / np.maximum(self._bc(self.aptos * pc), 1e-9)),
                  "out": np.log(np.maximum(self._bc(self.esp0["out"] * pc), 1e-9) / dois),
                  "bn": np.log(np.maximum(self._bc(self.esp0["bn"] * pc), 1e-9) / np.maximum(sw, 1e-9))}
            aptR = R["apt"][mm]
            ys = self._y(R["esq"][mm], R["dir"][mm], R["out"][mm], R["bn"][mm], aptR)
            for dm in self.dims:
                y, w = ys[dm]
                d = y - ag[dm][mm]
                if dm == "part":
                    okp = aptR > 0
                    d, w = np.where(okp, d, 0.0), np.where(okp, w, 0.0)
                rows["d"][dm].append(d); rows["w"][dm].append(w)
            rows["X"].append(Xm[mm]); rows["uf"].append(self.uf_de_mun[mm])
            rows["mun"].append(mm); rows["loc"].append(np.full(len(mm), -1))

        dev = {d: np.zeros(n) for d in DIMS}
        coef = {}
        if rows["X"]:
            Xo = np.concatenate(rows["X"]); ufo = np.concatenate(rows["uf"])
            muno = np.concatenate(rows["mun"]); loco = np.concatenate(rows["loc"])
            for dm in self.dims:
                dev[dm], coef[dm] = self._ajusta(np.concatenate(rows["d"][dm]),
                                                 np.concatenate(rows["w"][dm]),
                                                 Xo, ufo, muno, loco, dm, p)
        return self._agrega(dev, crawl, pc, R, st, ts, tem_st, tot, coef)

    def _ajusta(self, d, w, Xo, ufo, muno, loco, dm, p: Params):
        k = Xo.shape[1]
        u = np.zeros(self.n_uf); m = np.zeros(self.n_mun); l_ = np.zeros(self.n_loc)
        pen = np.diag([p.K0] + [p.L * self.W_tot[dm]] * (k - 1))
        if not p.usa_cov:
            pen[1:, 1:] = np.eye(k - 1) * 1e18
        lo = loco >= 0
        loc_c = np.clip(loco, 0, None)
        beta = np.zeros(k)
        for _ in range(p.iters):
            r = d - u[ufo] - m[muno] - np.where(lo, l_[loc_c], 0.0)
            Xw = Xo * w[:, None]
            beta = np.linalg.solve(Xw.T @ Xo + pen, Xw.T @ r)
            r = d - Xo @ beta
            u = np.bincount(ufo, w * r, self.n_uf) / (np.bincount(ufo, w, self.n_uf) + p.K_UF)
            r = r - u[ufo]
            m = np.bincount(muno, w * r, self.n_mun) / (np.bincount(muno, w, self.n_mun) + p.K_MUN)
            r = r - m[muno]
            l_ = (np.bincount(loco[lo], (w * r)[lo], self.n_loc)
                  / (np.bincount(loco[lo], w[lo], self.n_loc) + p.K_LOC))
        dev = self.X @ beta + u[self.uf_cod] + m[self.mun_cod] + l_[self.loc_cod]
        return dev, {"beta0": float(beta[0]), "u": u, "m": m}

    def _agrega(self, dev, crawl, pc, R, st, ts, tem_st, tot, coef) -> dict:
        pr = self._proj(dev)
        falta = (~crawl) * (1.0 - pc)                    # fracao ainda nao apurada de cada urna
        mun = {}
        for c in ["esq", "dir", "out", "bn"]:
            mun[c] = tot[c] + R[c] + self._bc(pr[c] * falta)
        mun["val"] = mun["esq"] + mun["dir"] + mun["out"]
        mun["comp"] = mun["val"] + mun["bn"]
        mun["apur_esq"] = tot["esq"] + R["esq"]
        mun["apur_dir"] = tot["dir"] + R["dir"]
        mun["apur_val"] = mun["apur_esq"] + mun["apur_dir"] + tot["out"] + R["out"]
        mun["apur_bn"] = tot["bn"] + R["bn"]
        mun["st"] = np.where(tem_st, st, tot["n"])
        mun["ts"] = np.where(tem_st, ts, self.urnas_mun)
        mun["n_bu"] = tot["n"]
        dfm = pd.DataFrame(mun)
        dfm["uf"] = self.mun_uf
        dfm["cd_mun"] = self.mun_cd

        def resumo(g):
            s = {c: float(g[c].sum()) for c in ["esq", "dir", "out", "bn", "val", "comp", "apur_val",
                                                "apur_esq", "apur_dir", "apur_bn", "st", "ts", "n_bu"]}
            v = max(s["val"], 1.0)
            s["sh_esq"], s["sh_dir"], s["sh_out"] = s["esq"] / v, s["dir"] / v, s["out"] / v
            s["margem"] = 100 * (s["esq"] - s["dir"]) / v
            s["dois_esq"] = s["esq"] / max(s["esq"] + s["dir"], 1.0)
            s["tela_margem"] = (100 * (s["apur_esq"] - s["apur_dir"]) / s["apur_val"]
                                if s["apur_val"] > 0 else None)
            s["pct_secoes"] = 100 * s["st"] / max(s["ts"], 1.0)
            return s

        br = resumo(dfm)
        uf = {u: resumo(g) for u, g in dfm.groupby("uf")}
        br["delta_equiv"] = self.delta_equiv(br["dois_esq"])
        return {"br": br, "uf": uf, "mun": dfm, "dev": dev, "falta": falta,
                "coef": {k: {"beta0": v["beta0"], "u": v["u"], "m": v["m"]} for k, v in coef.items()}}

    def delta_equiv(self, alvo_dois: float) -> float:
        """Swing uniforme (log-odds) que leva a ancora inteira ao dois-a-dois projetado."""
        a, v = self.A["ed"], self.esp0["dois"]
        lo, hi = -4.0, 4.0
        for _ in range(60):
            mid = (lo + hi) / 2
            if (v * sig(a + mid)).sum() / v.sum() < alvo_dois:
                lo = mid
            else:
                hi = mid
        return (lo + hi) / 2
