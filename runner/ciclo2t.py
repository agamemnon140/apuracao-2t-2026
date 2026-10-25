"""O laco da noite do 2o turno (25/10/2026): UM feed, DOIS needles.

  A  "vs 1o turno 2026"              ancora_t1_2026.parquet  (sintetico/ancora_repo.py)
  B  "vs 2o turno 2022 + demografia" ancora_2026.parquet     (idem; = proj26 do repo)

Os dois sao o mesmo estimador (pipeline/needle_hier.Needle) com ancoras diferentes, na
mesma ordem de urnas -- as observacoes do crawler (indices) sao compartilhadas.

Saidas (docs/dados/):
  live/br.json, live/uf/{UF}.json         needle B (contrato do apuracao-2026)
  live_t1/br.json, live_t1/uf/{UF}.json   needle A (mesmo contrato)
  live/historico.json                     um ponto por ciclo (os dois needles + tela crua)
  live/abstencao.json                     comparecimento apurado x esperado (UF, sentinelas)
  live.json                               compatibilidade (painel antigo)

Modos:
  --modo ao-vivo   feed do TSE (runner/coletor.py, so presidente) + boletins (bu_crawler)
  --modo simula    sem rede: finge que uma fracao dos municipios ja fechou com o voto do
                   1o turno de 2026 (docs/dados/uf/*.json). Teste de fumaca da cadeia.

Uso:
  .venv/Scripts/python -m runner.ciclo2t --modo simula --ciclos 2
  .venv/Scripts/python -m runner.ciclo2t --modo ao-vivo --publicar pages --intervalo 60
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import subprocess
import sys
import time
import unicodedata
from pathlib import Path

import numpy as np
import pandas as pd

from pipeline.needle_hier import Needle, Params
from runner.ciclo import le_boletins, monta_saida
from sintetico.caminhos import BASELINE, SAIDA, UFS, VIVO

RAIZ = Path(__file__).resolve().parents[1]
DOCS = RAIZ / "docs" / "dados"
LIVE_DIR = VIVO
PUSH_MIN_SEG = 360
BU_DB = LIVE_DIR / "bu.sqlite"

NEEDLES = {
    "A": {"rotulo": "vs 1º turno 2026", "ancora": "ancora_t1_2026.parquet",
          "alvo": "alvo_t1_2026_t2.json", "sigma_fator": 1.5, "pasta": "live_t1"},
    "B": {"rotulo": "vs 2º turno 2022 + demografia", "ancora": "ancora_2026.parquet",
          "alvo": "alvo_2026_t2.json", "sigma_fator": 1.0, "pasta": "live"},
}
SENTINELAS = [("BA", "Salvador"), ("RS", "Porto Alegre"), ("RS", "Caxias Do Sul"), ("RS", "Pelotas"),
              ("RS", "Canoas"), ("PR", "Curitiba"), ("PR", "Londrina"), ("SC", "Florianopolis"),
              ("SC", "Joinville"), ("SC", "Blumenau")]


def sig(x):
    return 1.0 / (1.0 + np.exp(-np.asarray(x, dtype=float)))


def sem_acento(s: str) -> str:
    return unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().casefold()


# ------------------------------------------------------------------ contexto de um needle
class Ctx:
    def __init__(self, chave: str, cfg: dict, turno: int):
        self.chave, self.rotulo, self.pasta = chave, cfg["rotulo"], cfg["pasta"]
        self.modo, self.turno = "ao-vivo", turno
        anc = pd.read_parquet(SAIDA / cfg["ancora"])
        self.nd = Needle(anc, turno=turno)
        self.calib = json.loads((BASELINE / "calib_presidente.json").read_text("utf-8"))
        self.alvo = json.loads((SAIDA / cfg["alvo"]).read_text("utf-8"))
        self.sigma_fator = float(cfg["sigma_fator"])
        c = json.loads((RAIZ / "config" / "candidatos_2026.json").read_text("utf-8"))["presidente"]
        self.nomes = {"esq": c["cands"][c["esq"]]["nome"].title(), "dir": c["cands"][c["dir"]]["nome"].title(),
                      "nr_esq": c["esq"], "nr_dir": c["dir"]}
        # comparecimento esperado pela ancora, por UF e por municipio (para traduzir efeitos em pontos)
        nd = self.nd
        val = nd.esp0["val"]
        self.comp_uf = {u: float(val[nd.uf_cod == i].sum() / max(nd.aptos[nd.uf_cod == i].sum(), 1))
                        for i, u in enumerate(nd.ufs)}
        vm = np.bincount(nd.mun_cod, val, minlength=nd.n_mun)
        am = np.bincount(nd.mun_cod, nd.aptos, minlength=nd.n_mun)
        self.comp_mun = vm / np.maximum(am, 1)

    def sigma(self, pct: float, chave: str = "sigma_br") -> float:
        return self.sigma_fator * float(np.interp(pct, self.calib["pct"], self.calib[chave]))


# ------------------------------------------------------------------ fontes
class Feed2T:
    """Feed do TSE so para presidente (cargo 0001) + boletins raspados."""

    def __init__(self, ctx: Ctx, sem_feed: bool = False):
        from runner.coletor import Coletor, descobre
        self.ctx, self.sem_feed, self.col = ctx, sem_feed, None
        if sem_feed:
            return
        cfg = descobre()
        if not cfg or str(ctx.turno) not in cfg.get("turnos", {}):
            raise SystemExit("config do 2o turno indisponivel: rode `runner.coletor --descobre`")
        self.col = Coletor(cfg, str(ctx.turno), cargos=("0001",))

    def le(self):
        e_, d_ = self.ctx.nomes["nr_esq"], self.ctx.nomes["nr_dir"]
        if self.sem_feed:
            return None, le_boletins(self.ctx.nd, e_, d_), pd.Timestamp.now()
        r = self.col.ciclo()
        logging.info("coleta: %s", r)
        linhas = []
        for ler in self.col.atual.values():
            if ler["cargo"] != "0001" or ler["nivel"] != "mu" or ler.get("st") is None:
                continue
            c = ler["cand"]
            esq, dir_ = c.get(e_, 0), c.get(d_, 0)
            vv = ler["vv"] or sum(c.values())
            linhas.append({"uf": ler["uf"], "cd_mun": ler["cd_mun"], "esq": esq, "dir": dir_,
                           "out": max(vv - esq - dir_, 0), "bn": (ler["vb"] or 0) + (ler["vn"] or 0),
                           "ea": ler.get("ea") or 0, "st": ler["st"], "ts": ler["ts"]})
        feed = pd.DataFrame(linhas)
        return feed, le_boletins(self.ctx.nd, e_, d_), pd.Timestamp.now()

    def leituras(self) -> list[dict]:
        if self.col is None:
            return []
        return [l for l in self.col.atual.values() if l["cargo"] == "0001"]


class FeedSimulado:
    """Uma fracao dos municipios 'fechada' com o voto do 1o turno de 2026 (sem rede)."""

    def __init__(self, frac: float, seed: int = 7):
        rng = np.random.default_rng(seed)
        rows = []
        for uf in UFS:
            u = json.loads((DOCS / "uf" / f"{uf}.json").read_text("utf-8"))
            for cd, m in u["mun"].items():
                p = m.get("pr26t1")
                if not p or rng.random() > frac:
                    continue
                rows.append({"uf": uf.lower(), "cd_mun": int(cd), "esq": p[0], "dir": p[1], "out": sum(p[2:13]),
                             "bn": p[13] + p[14], "ea": m["aptos26"], "c": m["aptos26"] - p[15],
                             "st": m["ns"], "ts": m["ns"]})
        self.feed = pd.DataFrame(rows)
        self.t0 = time.time()

    def le(self):
        return self.feed, None, pd.Timestamp.now()

    def leituras(self) -> list[dict]:
        return [{"nivel": "mu", "uf": r.uf, "cd_mun": int(r.cd_mun), "ea": int(r.ea), "c": int(r.c),
                 "st": int(r.st), "ts": int(r.ts)} for r in self.feed.itertuples()]


# ------------------------------------------------------------------ saidas
def grava(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")), "utf-8")
    tmp.replace(p)


def escreve_needle(ctx: Ctx, r: dict, saida: dict) -> None:
    d = DOCS / ctx.pasta
    grava(d / "br.json", saida)
    m = r["mun"]
    am = ctx.alvo.get("mun", {})
    cols = ["cd_mun", "st", "ts", "n_bu", "apur_esq", "apur_dir", "apur_val", "proj_esq", "proj_dir",
            "proj_val", "proj_comp", "alvo_esq", "ancora_esq", "alvo_dir", "aptos"]
    aptos_mun = np.bincount(ctx.nd.mun_cod, ctx.nd.aptos, minlength=ctx.nd.n_mun)
    for u, g in m.groupby("uf"):
        linhas = []
        for row in g.itertuples(index=False):
            a = am.get(str(row.cd_mun), {})
            linhas.append([int(row.cd_mun), int(row.st), int(row.ts), int(row.n_bu),
                           int(row.apur_esq), int(row.apur_dir), int(row.apur_val),
                           int(round(row.esq)), int(round(row.dir)), int(round(row.val)), int(round(row.comp)),
                           round(100 * a["alvo_esq"], 2) if a else None,
                           round(100 * a["ancora_esq"], 2) if a else None,
                           round(100 * a["alvo_dir"], 2) if a else None,
                           int(aptos_mun[ctx.nd.mun_idx[f"{u}:{int(row.cd_mun)}"]])])
        grava(d / "uf" / f"{u}.json", {"instante": saida["instante"], "cols": cols, "mun": linhas})


def escreve_compat(saida_b: dict, r_b: dict) -> None:
    """live.json do painel antigo: so presidente, cobertura e modo."""
    arq = DOCS / "live.json"
    live = json.loads(arq.read_text("utf-8")) if arq.exists() else {}
    pr = saida_b["pr"]
    m = r_b["mun"]
    live.update({
        "modo": "ao-vivo", "gerado_em": saida_b["gerado_em"], "instante": saida_b["instante"][:5],
        "congelado_em": "",
        "presidente": {"lider": pr["lider"], "margem": abs(pr["margem"]),
                       "tela_crua": (0.0 if pr["tela_margem"] is None else
                                     round(pr["tela_margem"] * (1 if pr["margem"] >= 0 else -1), 2)),
                       "p_lider": pr["p_lider"], "pct_secoes": saida_b["pct_secoes"],
                       "sigma": pr["sigma"], "sh_esq": pr["sh_esq"], "sh_dir": pr["sh_dir"],
                       "p_esq50": pr["p_esq50"], "p_dir50": pr["p_dir50"]},
        "governos": [], "senado": [], "camara": None, "assembleias": None,
        "cobertura": sorted(({"uf": u, "tot": int(g["st"].sum()), "de": int(g["ts"].sum()),
                              "pct": round(100 * g["st"].sum() / max(g["ts"].sum(), 1), 1)}
                             for u, g in m.groupby("uf") if u != "ZZ"), key=lambda x: -x["pct"]),
    })
    grava(arq, live)


def ponto_historico(saidas: dict, instante: pd.Timestamp, comp_apurado: float | None) -> dict:
    b = saidas["B"]
    p = {"t": instante.strftime("%H:%M:%S"), "hora": instante.isoformat(timespec="seconds"),
         "pct": b["pct_secoes"], "tela": b["pr"]["tela_margem"], "n_bu": b["n_bu"],
         "comp_apurado": None if comp_apurado is None else round(100 * comp_apurado, 2)}
    for k, s in saidas.items():
        pr = s["pr"]
        p[k] = {"sh_esq": pr["sh_esq"], "sh_dir": pr["sh_dir"], "margem": pr["margem"], "sigma": pr["sigma"],
                "p_esq": round(1 - pr["p_lider"], 3) if pr["lider"] == s["nomes"]["dir"] else pr["p_lider"],
                "deq": pr["delta_equiv"], "dalvo_e": pr["delta_alvo_esq"], "dalvo_d": pr["delta_alvo_dir"],
                "comp": pr["comparecimento"]}
    return p


class Abstencao:
    def __init__(self, ctxs: dict[str, Ctx]):
        self.ctxs = ctxs
        self.base = json.loads((SAIDA / "abst_base.json").read_text("utf-8"))
        br = json.loads((DOCS / "br.json").read_text("utf-8"))["br"]
        self.br_t1 = 100 * br["pr26t1"][-1] / br["aptos26"]
        self.br_t2_2022 = 100 * br["pr22t2"][-1] / sum(br["pr22t2"])
        mun = self.base["mun"]
        self.sent = []
        for uf, nome in SENTINELAS:
            alvo = sem_acento(nome)
            for cd, m in mun.items():
                if m["uf"] == uf and sem_acento(m["nome"]) == alvo:
                    self.sent.append(int(cd))
                    break
        top = sorted(((m.get("aptos26") or 0, int(cd)) for cd, m in mun.items()), reverse=True)[:12]
        for _, cd in top:
            if cd not in self.sent:
                self.sent.append(cd)

    def efeito(self, ctx: Ctx, r: dict, uf: str | None = None, cd: int | None = None) -> float | None:
        c = r.get("coef", {}).get("part")
        if not c:
            return None
        nd = ctx.nd
        if cd is None:
            i = list(nd.ufs).index(uf) if uf in list(nd.ufs) else None
            if i is None:
                return None
            p = ctx.comp_uf[uf]
            return round(100 * float(c["u"][i]) * p * (1 - p), 2)
        k = f"{uf}:{cd}"
        if k not in nd.mun_idx:
            return None
        j = nd.mun_idx[k]
        p = float(ctx.comp_mun[j])
        i = list(nd.ufs).index(uf)
        return round(100 * (float(c["u"][i]) + float(c["m"][j])) * p * (1 - p), 2)

    def monta(self, leituras: list[dict], rs: dict[str, dict], instante: pd.Timestamp) -> dict:
        mu = [l for l in leituras if l.get("nivel") == "mu" and l.get("ea")]
        por_uf: dict[str, dict] = {}
        por_mun: dict[int, dict] = {}
        for l in mu:
            uf = l["uf"].upper()
            a = por_uf.setdefault(uf, {"ea": 0, "c": 0, "st": 0, "ts": 0})
            a["ea"] += l["ea"] or 0; a["c"] += l["c"] or 0; a["st"] += l["st"] or 0; a["ts"] += l["ts"] or 0
            por_mun[int(l["cd_mun"])] = l
        ufs = []
        for uf in UFS:
            b = self.base["uf"].get(uf, {})
            a = por_uf.get(uf)
            ap = round(100 * (1 - a["c"] / a["ea"]), 2) if a and a["ea"] else None
            ufs.append({"uf": uf, "pct": round(100 * a["st"] / a["ts"], 1) if a and a["ts"] else 0.0,
                        "abst_apurada": ap, "abst_t1": b.get("abst_t1"), "abst_t2_2022": b.get("abst_t2_2022"),
                        "delta_t1": None if ap is None or b.get("abst_t1") is None else round(ap - b["abst_t1"], 2),
                        "ef_A": self.efeito(self.ctxs["A"], rs["A"], uf),
                        "ef_B": self.efeito(self.ctxs["B"], rs["B"], uf)})

        def linha_mun(cd: int) -> dict | None:
            b = self.base["mun"].get(str(cd))
            if not b:
                return None
            l = por_mun.get(cd)
            ap = round(100 * (1 - l["c"] / l["ea"]), 2) if l and l.get("ea") and l.get("c") is not None else None
            return {"cd": cd, "uf": b["uf"], "nome": b["nome"], "aptos26": b.get("aptos26"),
                    "pct": round(100 * l["st"] / l["ts"], 1) if l and l.get("ts") else 0.0,
                    "abst_apurada": ap, "abst_t1": b.get("abst_t1"), "abst_t2_2022": b.get("abst_t2_2022"),
                    "delta_t1": None if ap is None or b.get("abst_t1") is None else round(ap - b["abst_t1"], 2),
                    "ef_A": self.efeito(self.ctxs["A"], rs["A"], b["uf"], cd),
                    "ef_B": self.efeito(self.ctxs["B"], rs["B"], b["uf"], cd)}

        sentinelas = [x for x in (linha_mun(cd) for cd in self.sent) if x]
        # maiores desvios entre municipios com apuracao relevante
        cand = []
        for cd, l in por_mun.items():
            b = self.base["mun"].get(str(cd))
            if not b or not l.get("ea") or (l.get("ea") or 0) < 20000 or not l.get("ts") or l["st"] < 0.2 * l["ts"]:
                continue
            if b.get("abst_t1") is None:
                continue
            cand.append((abs(100 * (1 - l["c"] / l["ea"]) - b["abst_t1"]), cd))
        desvios = [x for x in (linha_mun(cd) for _, cd in sorted(cand, reverse=True)[:15]) if x]
        tot_ea = sum(a["ea"] for a in por_uf.values()); tot_c = sum(a["c"] for a in por_uf.values())
        return {"instante": instante.strftime("%H:%M:%S"),
                "br": {"abst_apurada": round(100 * (1 - tot_c / tot_ea), 2) if tot_ea else None,
                       "abst_t1": round(self.br_t1, 2), "abst_t2_2022": round(self.br_t2_2022, 2),
                       "ea": tot_ea, "c": tot_c},
                "ufs": ufs, "sentinelas": sentinelas, "desvios": desvios}


class Publicador:
    def __init__(self, modo: str):
        self.modo, self.ultimo = modo, 0.0

    def __call__(self, instante: str) -> str:
        if self.modo != "pages" or time.time() - self.ultimo < PUSH_MIN_SEG:
            return "local"
        alvos = ["docs/dados/live.json", "docs/dados/live", "docs/dados/live_t1"]
        try:
            subprocess.run(["git", "add", *alvos], cwd=RAIZ, check=True, capture_output=True)
            c = subprocess.run(["git", "commit", "-m", f"live {instante} [skip ci]"], cwd=RAIZ,
                               capture_output=True, text=True)
            if c.returncode != 0 and "nothing to commit" in (c.stdout + c.stderr):
                return "sem mudanca"
            p = subprocess.run(["git", "push"], cwd=RAIZ, capture_output=True, text=True, timeout=120)
            if p.returncode != 0:
                subprocess.run(["git", "pull", "--rebase", "-X", "theirs"], cwd=RAIZ, capture_output=True,
                               text=True, timeout=120)
                p = subprocess.run(["git", "push"], cwd=RAIZ, capture_output=True, text=True, timeout=120)
                if p.returncode != 0:
                    return f"push falhou: {p.stderr.strip()[:200]}"
            self.ultimo = time.time()
            return "publicado"
        except Exception as e:
            return f"erro git: {e}"


# ------------------------------------------------------------------ laco
def main() -> int:
    global BU_DB
    ap = argparse.ArgumentParser()
    ap.add_argument("--modo", choices=["ao-vivo", "simula"], default="ao-vivo")
    ap.add_argument("--turno", type=int, default=2)
    ap.add_argument("--intervalo", type=float, default=60.0, help="segundos reais entre ciclos")
    ap.add_argument("--publicar", choices=["local", "pages"], default="local")
    ap.add_argument("--ciclos", type=int, default=0, help="0 = ate o fim")
    ap.add_argument("--simula-frac", type=float, default=0.10)
    ap.add_argument("--sem-feed", action="store_true", help="ao vivo so com boletins")
    ap.add_argument("--bu-db", default=str(BU_DB))
    ap.add_argument("--novo-historico", action="store_true", help="zera live/historico.json")
    a = ap.parse_args()
    BU_DB = Path(a.bu_db)
    import runner.ciclo as _c
    _c.BU_DB = BU_DB

    LIVE_DIR.joinpath("log").mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                        handlers=[logging.StreamHandler(sys.stdout),
                                  logging.FileHandler(LIVE_DIR / "log" / f"ciclo2t_{dt.date.today():%Y%m%d}.log",
                                                      encoding="utf-8")])
    t0 = time.time()
    ctxs = {k: Ctx(k, cfg, a.turno) for k, cfg in NEEDLES.items()}
    assert ctxs["A"].nd.n == ctxs["B"].nd.n, "ancoras com numero de urnas diferente"
    logging.info("needles prontos: %d urnas, %.0f s", ctxs["A"].nd.n, time.time() - t0)
    fonte = FeedSimulado(a.simula_frac) if a.modo == "simula" else Feed2T(ctxs["B"], a.sem_feed)
    abst = Abstencao(ctxs)
    pub = Publicador(a.publicar)
    params = Params()
    arq_hist = DOCS / "live" / "historico.json"
    hist = [] if (a.novo_historico or not arq_hist.exists()) else json.loads(arq_hist.read_text("utf-8"))
    n = 0
    while True:
        t0 = time.time()
        try:
            feed, obs, instante = fonte.le()
            rs, saidas = {}, {}
            for k, ctx in ctxs.items():
                rs[k] = ctx.nd.estima(obs, feed, params)
                s = monta_saida(ctx, rs[k], instante)
                s["modo"] = "simula" if a.modo == "simula" else "ao-vivo"
                s.update({"needle": k, "rotulo": ctx.rotulo, "sigma_fator": ctx.sigma_fator,
                          "sigma_calibrado": False, "ancora_br": ctx.alvo["br"]})
                saidas[k] = s
                escreve_needle(ctx, rs[k], s)
            leituras = fonte.leituras()
            ab = abst.monta(leituras, rs, instante)
            grava(DOCS / "live" / "abstencao.json", ab)
            comp = (ab["br"]["c"] / ab["br"]["ea"]) if ab["br"]["ea"] else None
            hist.append(ponto_historico(saidas, instante, comp))
            grava(arq_hist, hist)
            escreve_compat(saidas["B"], rs["B"])
            st = pub(saidas["B"]["instante"])
            for k, s in saidas.items():
                pr = s["pr"]
                logging.info("%s %s  %5.1f%% apurado  %s %.2f x %s %.2f  margem %+.2f (tela %s)  sigma %.2f  "
                             "P(%s)=%.3f  bu=%d", k, s["instante"], s["pct_secoes"], ctxs[k].nomes["esq"], pr["sh_esq"],
                             ctxs[k].nomes["dir"], pr["sh_dir"], pr["margem"], pr["tela_margem"], pr["sigma"],
                             pr["lider"], pr["p_lider"], s["n_bu"])
            logging.info("abstencao apurada %s (1T %s, 2022 %s)  [%s, %.1fs]", ab["br"]["abst_apurada"],
                         ab["br"]["abst_t1"], ab["br"]["abst_t2_2022"], st, time.time() - t0)
            (LIVE_DIR / "estado_ciclo.json").write_text(json.dumps(
                {"ciclo": n, "instante": saidas["B"]["instante"], "pct": saidas["B"]["pct_secoes"],
                 "margem_A": saidas["A"]["pr"]["margem"], "margem_B": saidas["B"]["pr"]["margem"],
                 "publicacao": st, "gerado_em": saidas["B"]["gerado_em"]}), "utf-8")
        except Exception:
            logging.exception("ciclo perdido; seguindo no proximo")
            time.sleep(max(30.0, a.intervalo - (time.time() - t0)))
            n += 1
            continue
        n += 1
        if a.ciclos and n >= a.ciclos:
            break
        time.sleep(max(0.0, a.intervalo - (time.time() - t0)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
