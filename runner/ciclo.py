"""O laco da noite: coleta -> needle hierarquico -> JSONs do site -> publica.

Modos:
  --modo replay   re-toca 2022 (1o ou 2o turno) em velocidade acelerada, sem rede: o feed
                  municipal e o crawler sao simulados a partir dos carimbos reais. Testa a
                  cadeia inteira, ate a pagina.
  --modo ao-vivo  le o feed do TSE (runner/coletor.py) e os boletins raspados
                  (runner/bu_crawler.py, se estiver rodando em outro processo).

Saidas (docs/dados/):
  live.json              contrato da tela da noite (index.html); presidente vem do needle
  live/br.json           needle, alvo, desvio da ancora, UFs
  live/uf/{UF}.json      por municipio: apurado, projetado, alvo
  live/mun/{cd}.json     por urna (so no modo local/tunel; fora do git)

Publicacao:
  --publicar local   so escreve (sirva docs/ com `python -m http.server -d docs 8000`
                     e, se quiser, `cloudflared tunnel --url http://localhost:8000`)
  --publicar pages   git add/commit/push de live.json + live/br + live/uf, no maximo a
                     cada 6 min (limite pratico de builds do GitHub Pages)

Uso:
  .venv/Scripts/python -m runner.ciclo --modo replay --turno 1 --velocidade 30 --inicio 17:00
  .venv/Scripts/python -m runner.ciclo --modo ao-vivo --turno 1 --publicar pages
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import math
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

from pipeline.needle_hier import Needle, Params
from sintetico.caminhos import BASELINE, SAIDA
from sintetico.caminhos import VIVO

RAIZ = Path(__file__).resolve().parents[1]
DOCS = RAIZ / "docs" / "dados"
LIVE_DIR = VIVO
PUSH_MIN_SEG = 360
BU_DB = LIVE_DIR / "bu.sqlite"          # trocado por --bu-db (ex.: banco sintetico de teste)


def phi(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


class Contexto:
    def __init__(self, modo: str, turno: int):
        self.modo, self.turno = modo, turno
        replay = modo == "replay"
        anc = pd.read_parquet(SAIDA / ("ancora_2022_calib.parquet" if replay else "ancora_2026.parquet"))
        self.nd = Needle(anc, turno=turno)
        self.calib = json.loads((BASELINE / "calib_presidente.json").read_text("utf-8"))
        arq_alvo = "alvo_2022_calib.json" if replay else f"alvo_2026_t{turno}.json"
        self.alvo = json.loads((SAIDA / arq_alvo).read_text("utf-8"))
        if replay:
            self.nomes = {"esq": "Lula", "dir": "Bolsonaro", "nr_esq": "13", "nr_dir": "22"}
        else:
            c = json.loads((RAIZ / "config" / "candidatos_2026.json").read_text("utf-8"))["presidente"]
            self.nomes = {"esq": c["cands"][c["esq"]]["nome"].title(), "dir": c["cands"][c["dir"]]["nome"].title(),
                          "nr_esq": c["esq"], "nr_dir": c["dir"]}

    def sigma(self, pct: float, chave="sigma_br") -> float:
        return float(np.interp(pct, self.calib["pct"], self.calib[chave]))


# ------------------------------------------------------------------ fontes de dados
class ReplayFeed:
    """Relogio simulado sobre a noite de 2022: feed municipal exato + crawler parcial."""

    def __init__(self, ctx: Contexto, inicio: str, velocidade: float, rho: float, lag: float):
        from probe.calibra_hier import prepara
        _, self.tr = prepara(ctx.turno)
        self.nd = ctx.nd
        dia = "2022-10-02" if ctx.turno == 1 else "2022-10-30"
        self.t0_sim = pd.Timestamp(f"{dia} {inicio}")
        self.t0_real = time.time()
        self.vel, self.rho, self.lag = velocidade, rho, lag
        self.rng = np.random.default_rng(7).random(ctx.nd.n)
        self.fim = pd.Timestamp(self.tr["tempo"][self.tr["tem"]].max())

    def agora(self) -> pd.Timestamp:
        return self.t0_sim + pd.Timedelta(seconds=(time.time() - self.t0_real) * self.vel)

    def le(self):
        from probe.calibra_hier import no_instante
        t = self.agora()
        feed, obs, _ = no_instante(self.nd, self.tr, t.to_datetime64(), self.rho, self.lag, self.rng)
        return feed, obs, t


class FeedAoVivo:
    def __init__(self, ctx: Contexto, sem_feed: bool = False):
        from runner.coletor import Coletor, descobre
        self.ctx = ctx
        self.sem_feed = sem_feed
        if sem_feed:                                       # so boletins (teste ou feed fora do ar)
            self.col = None
            return
        self.cfg = descobre()
        if not self.cfg:
            raise SystemExit("config de 2026 indisponivel: rode `runner.coletor --descobre` ou "
                             "grave live/config_2026.json com \"manual\": true")
        self.col = Coletor(self.cfg, str(ctx.turno))

    def le(self):
        if self.sem_feed:
            return None, le_boletins(self.ctx.nd, self.ctx.nomes["nr_esq"], self.ctx.nomes["nr_dir"]), pd.Timestamp.now()
        r = self.col.ciclo()
        logging.info("coleta: %s", r)
        linhas = []
        e_, d_ = self.ctx.nomes["nr_esq"], self.ctx.nomes["nr_dir"]
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
        obs = le_boletins(self.ctx.nd, e_, d_)
        return feed, obs, pd.Timestamp.now()

    def _uf(self, cargo_cd):
        if self.col is None:
            return {}
        return {l["uf"].upper(): l for l in self.col.atual.values() if l["cargo"] == cargo_cd and l["nivel"] == "uf"}

    def tela_estadual(self) -> dict:
        out = {}
        for cargo, cd in (("governador", "0003"), ("senador", "0005")):
            for uf, l in self._uf(cd).items():
                out[(cargo, uf)] = l["cand"]
        return out

    def pct_estadual(self) -> dict:
        return {uf: 100 * l["st"] / max(l["ts"], 1) for uf, l in self._uf("0003").items()
                if l.get("ts") and l.get("st") is not None}


def le_boletins(nd: Needle, nr_esq: str, nr_dir: str):
    """Urnas raspadas pelo bu_crawler (sqlite), casadas com a ancora."""
    if not BU_DB.exists():
        return None
    try:
        from runner.bu_crawler import observadas
        return observadas(nd, nr_esq, nr_dir, BU_DB)
    except Exception as e:                                  # o needle nao cai por causa do crawler
        logging.warning("boletins indisponiveis: %s", e)
        return None


# ------------------------------------------------------------------ governador e Senado
class Estaduais:
    """Needle estadual por UF sobre as urnas raspadas (replay: as mesmas urnas do presidente)."""

    CARGOS = {"governador": ("GOVERNADOR", "governador_secao_2022_t1.parquet"),
              "senador": ("SENADOR", "senador_secao_2022_t1.parquet")}

    def __init__(self, ctx: Contexto):
        from pipeline.estadual_live import ARQ_CALIB
        self.ctx = ctx
        self.calib = json.loads(ARQ_CALIB.read_text("utf-8"))
        a = ctx.nd.anc[["uf", "cd_mun", "zona", "secao", "aptos", "a_ed"]]
        self.anc_uf = {u: g.reset_index(drop=True) for u, g in a.groupby("uf") if u != "ZZ"}
        self.nomes, self.largo = {}, {}
        if ctx.modo == "replay":
            for cargo, (_, arq) in self.CARGOS.items():
                v = pd.read_parquet(BASELINE / arq)
                v = v[v["candidato"]]
                v["cd_mun"] = v["cd_municipio"].astype(int)
                self.nomes[cargo] = {(r.uf, r.nr_votavel): r.nm_votavel for r in
                                     v[["uf", "nr_votavel", "nm_votavel"]].drop_duplicates().itertuples()}
                w = v.pivot_table(index=["uf", "cd_mun", "zona", "secao"], columns="nr_votavel", values="votos",
                                  aggfunc="sum", fill_value=0)
                self.largo[cargo] = {u: g.droplevel(0).reset_index() for u, g in w.groupby(level=0)}
        else:
            c = json.loads((RAIZ / "config" / "candidatos_2026.json").read_text("utf-8"))
            for cargo in self.CARGOS:
                self.nomes[cargo] = {(u, nr): d["nome"] for u, cs in c[cargo].items() for nr, d in cs.items()}

    def obs_replay(self, cargo: str, uf: str, obs: dict | None) -> pd.DataFrame | None:
        if obs is None or not len(obs["idx"]):
            return None
        a = self.ctx.nd.anc.iloc[obs["idx"]]
        k = a.loc[a["uf"] == uf, ["cd_mun", "zona", "secao"]]
        w = self.largo[cargo].get(uf)
        if w is None or k.empty:
            return None
        o = k.merge(w, on=["cd_mun", "zona", "secao"], how="inner")
        return o.loc[:, (o != 0).any(axis=0)]

    def obs_bu(self, cargo: str, uf: str) -> pd.DataFrame | None:
        if not BU_DB.exists():
            return None
        import sqlite3
        con = sqlite3.connect(BU_DB, timeout=30)
        v = pd.read_sql("SELECT mun AS cd_mun, zona, secao, nr, votos FROM votos WHERE cargo=? AND uf=? "
                        "AND nr NOT LIKE 'L%'", con, params=(self.CARGOS[cargo][0], uf.lower()))
        con.close()
        if v.empty:
            return None
        return v.pivot_table(index=["cd_mun", "zona", "secao"], columns="nr", values="votos",
                             aggfunc="sum", fill_value=0).reset_index()

    def paineis(self, obs: dict | None, pct_uf: dict, tela: dict) -> tuple[list, list]:
        from pipeline.estadual_live import corrida, painel
        out = {"governador": [], "senador": []}
        for cargo in out:
            for uf, anc in sorted(self.anc_uf.items()):
                o = self.obs_replay(cargo, uf, obs) if self.ctx.modo == "replay" else self.obs_bu(cargo, uf)
                cands = [c for c in (o.columns if o is not None else []) if c not in ("cd_mun", "zona", "secao")]
                try:
                    pr = corrida(anc, o, cands) if o is not None else None
                except Exception as e:                       # uma UF nao derruba as outras
                    logging.warning("%s %s: %s", cargo, uf, e)
                    pr = None
                nomes = {nr: nm for (u, nr), nm in self.nomes[cargo].items() if u == uf}
                vagas = 2 if (cargo == "senador" and self.ctx.modo != "replay") else 1
                out[cargo].append(painel(cargo, uf, pr, pct_uf.get(uf, 0.0), self.calib, nomes,
                                         tela.get((cargo, uf)), vagas))
        return out["governador"], out["senador"]


# ------------------------------------------------------------------ deputados
class Deputados:
    """Bancadas (quociente + sobras + clausula) a cada 5 ciclos. No replay a conta e
    sincrona (determinismo no ensaio); ao vivo roda numa thread para nao segurar o needle
    presidencial (~20-50 s por rodada)."""

    def __init__(self, ctx: Contexto):
        self.ctx = ctx
        self.res: dict = {}
        self._dep = None
        self._fonte = None
        self._th = None

    def _init(self):
        from pipeline.dep_live import DepLive, FonteBU, FonteReplay
        if self.ctx.modo == "replay":
            self._fonte = FonteReplay(self.ctx.nd.anc)
            self._dep = DepLive(self.ctx.nd.anc, 2022, self._fonte)
        else:
            self._fonte = FonteBU(BU_DB)
            self._dep = DepLive(self.ctx.nd.anc, 2026, self._fonte)

    def dispara(self, obs) -> str:
        import threading
        if self._th is not None and self._th.is_alive():
            return "ocupado"
        if self._dep is None:
            self._init()
        if self.ctx.modo == "replay":
            self._fonte.define_idx(obs["idx"] if obs is not None else None)

        def alvo():
            try:
                t0 = time.time()
                self.res = self._dep.roda()
                cam = self.res.get("camara")
                logging.info("deputados: camara %s, assembleias %s [%.0fs]",
                             "ok" if cam else f"parcial (faltam {self.res.get('camara_parcial')})",
                             "ok" if self.res.get("assembleias") else "parcial", time.time() - t0)
            except Exception as e:
                logging.warning("deputados falhou: %s", e)
        if self.ctx.modo == "replay":
            alvo()
        else:
            self._th = threading.Thread(target=alvo, daemon=True)
            self._th.start()
        return "disparado"


# ------------------------------------------------------------------ saida
def monta_saida(ctx: Contexto, r: dict, instante: pd.Timestamp) -> dict:
    b = r["br"]
    pct = b["pct_secoes"]
    sg = ctx.sigma(pct)
    lider = "esq" if b["margem"] >= 0 else "dir"
    alvo = ctx.alvo
    pr = {
        "apur": {k: round(b["apur_" + k]) for k in ["esq", "dir", "val", "bn"]},
        "proj": {k: round(b[k]) for k in ["esq", "dir", "out", "bn", "val", "comp"]},
        "sh_esq": round(100 * b["sh_esq"], 2), "sh_dir": round(100 * b["sh_dir"], 2),
        "sh_out": round(100 * b["sh_out"], 2),
        "margem": round(b["margem"], 2),
        "tela_margem": None if b["tela_margem"] is None else round(b["tela_margem"], 2),
        "sigma": round(sg, 2),
        "lider": ctx.nomes[lider],
        "p_lider": round(min(0.999, phi(abs(b["margem"]) / sg)), 3),
        # liquidar no 1o turno: fatia dos validos >= 50%; erro da fatia ~ sigma/2
        "p_esq50": round(phi((100 * b["sh_esq"] - 50) / (sg / 2)), 3),
        "p_dir50": round(phi((100 * b["sh_dir"] - 50) / (sg / 2)), 3),
        "dois_esq": round(100 * b["dois_esq"], 2),
        "ancora_dois_esq": round(100 * alvo["br"]["ancora_esq"], 2),
        "delta_equiv": round(b["delta_equiv"], 4),
        "delta_alvo_esq": round(alvo["delta_esq"], 4), "delta_alvo_dir": round(alvo["delta_dir"], 4),
        "comparecimento": round(100 * b["comp"] / ctx.nd.aptos.sum(), 2),
    }
    ufs = {}
    for u, s in sorted(r["uf"].items()):
        a = alvo["uf"].get(u, {})
        su = ctx.sigma(s["pct_secoes"], "sigma_uf")
        ufs[u] = [round(s["pct_secoes"], 1),
                  round(100 * s["apur_esq"] / s["apur_val"], 2) if s["apur_val"] else None,
                  round(100 * s["apur_dir"] / s["apur_val"], 2) if s["apur_val"] else None,
                  round(100 * s["sh_esq"], 2), round(100 * s["sh_dir"], 2), round(s["margem"], 2),
                  round(su, 2),
                  round(100 * a.get("alvo_esq", float("nan")), 2), round(100 * a.get("alvo_dir", float("nan")), 2),
                  round(100 * a.get("ancora_esq", float("nan")), 2), int(s["n_bu"])]
    return {"gerado_em": dt.datetime.now().isoformat(timespec="seconds"),
            "modo": "replay-2022" if ctx.modo == "replay" else "ao-vivo", "turno": ctx.turno,
            "instante": instante.strftime("%H:%M:%S"), "pct_secoes": round(pct, 2),
            "n_bu": int(b["n_bu"]), "n_urnas": int(ctx.nd.n), "nomes": ctx.nomes, "pr": pr,
            "ufs_cols": ["pct", "apur_esq", "apur_dir", "proj_esq", "proj_dir", "margem", "sigma",
                         "alvo_esq", "alvo_dir", "ancora_esq", "n_bu"],
            "ufs": ufs}


def escreve(ctx: Contexto, r: dict, saida: dict, publicar: str, govs=None, sens=None,
            dep_res: dict | None = None) -> list[Path]:
    (DOCS / "live" / "uf").mkdir(parents=True, exist_ok=True)
    escritos = []

    def grava(p: Path, obj):
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")), "utf-8")
        tmp.replace(p)
        escritos.append(p)

    if govs is not None:
        saida["gov"] = {g["uf"]: g for g in govs}
        saida["sen"] = {g["uf"]: g for g in sens}
    grava(DOCS / "live" / "br.json", saida)
    m = r["mun"]
    am = ctx.alvo.get("mun", {})
    cols = ["cd_mun", "st", "ts", "n_bu", "apur_esq", "apur_dir", "apur_val", "proj_esq", "proj_dir",
            "proj_val", "proj_comp", "alvo_esq", "ancora_esq"]
    for u, g in m.groupby("uf"):
        linhas = []
        for row in g.itertuples(index=False):
            a = am.get(str(row.cd_mun), {})
            linhas.append([int(row.cd_mun), int(row.st), int(row.ts), int(row.n_bu),
                           int(row.apur_esq), int(row.apur_dir), int(row.apur_val),
                           int(round(row.esq)), int(round(row.dir)), int(round(row.val)), int(round(row.comp)),
                           round(100 * a["alvo_esq"], 2) if a else None,
                           round(100 * a["ancora_esq"], 2) if a else None])
        grava(DOCS / "live" / "uf" / f"{u}.json", {"instante": saida["instante"], "cols": cols, "mun": linhas})

    # contrato antigo (index.html): so o presidente, a cobertura e o modo mudam
    arq = DOCS / "live.json"
    live = json.loads(arq.read_text("utf-8")) if arq.exists() else {}
    pr = saida["pr"]
    live.update({
        "modo": saida["modo"], "gerado_em": saida["gerado_em"], "instante": saida["instante"][:5],
        "congelado_em": (f"replay acelerado de {'02/10' if ctx.turno == 1 else '30/10'}/2022"
                         if ctx.modo == "replay" else ""),
        # a tela da noite desenha tudo do ponto de vista de quem lidera a projecao
        "presidente": {"lider": pr["lider"], "margem": abs(pr["margem"]),
                       "tela_crua": (0.0 if pr["tela_margem"] is None else
                                     round(pr["tela_margem"] * (1 if pr["margem"] >= 0 else -1), 2)),
                       "p_lider": pr["p_lider"], "pct_secoes": saida["pct_secoes"],
                       "sigma": pr["sigma"], "sh_esq": pr["sh_esq"], "sh_dir": pr["sh_dir"],
                       "p_esq50": pr["p_esq50"], "p_dir50": pr["p_dir50"]},
        **({"governos": govs, "senado": sens} if govs is not None else {}),
        "camara": (dep_res or {}).get("camara"),
        "assembleias": (dep_res or {}).get("assembleias"),
        "cobertura": sorted(({"uf": u, "tot": int(g["st"].sum()), "de": int(g["ts"].sum()),
                              "pct": round(100 * g["st"].sum() / max(g["ts"].sum(), 1), 1)}
                             for u, g in m.groupby("uf") if u != "ZZ"), key=lambda x: -x["pct"]),
    })
    grava(arq, live)
    return escritos


class Publicador:
    def __init__(self, modo: str):
        self.modo, self.ultimo = modo, 0.0

    def __call__(self, instante: str) -> str:
        if self.modo != "pages" or time.time() - self.ultimo < PUSH_MIN_SEG:
            return "local"
        alvos = ["docs/dados/live.json", "docs/dados/live/br.json", "docs/dados/live/uf"]
        try:
            subprocess.run(["git", "add", *alvos], cwd=RAIZ, check=True, capture_output=True)
            c = subprocess.run(["git", "commit", "-m", f"live {instante} [skip ci]"], cwd=RAIZ,
                               capture_output=True, text=True)
            if c.returncode != 0 and "nothing to commit" in (c.stdout + c.stderr):
                return "sem mudanca"
            p = subprocess.run(["git", "push"], cwd=RAIZ, capture_output=True, text=True, timeout=120)
            if p.returncode != 0:
                # alguem commitou no meio (bot, edicao manual): rebase mantendo o NOSSO live
                subprocess.run(["git", "pull", "--rebase", "-X", "theirs"], cwd=RAIZ, capture_output=True,
                               text=True, timeout=120)
                p = subprocess.run(["git", "push"], cwd=RAIZ, capture_output=True, text=True, timeout=120)
                if p.returncode != 0:
                    return f"push falhou: {p.stderr.strip()[:200]}"
            self.ultimo = time.time()
            return "publicado"
        except Exception as e:                                # a noite nao para por causa do git
            return f"erro git: {e}"


def main() -> int:
    global BU_DB
    ap = argparse.ArgumentParser()
    ap.add_argument("--modo", choices=["replay", "ao-vivo"], default="replay")
    ap.add_argument("--turno", type=int, default=1)
    ap.add_argument("--velocidade", type=float, default=20.0)
    ap.add_argument("--inicio", default="17:00")
    ap.add_argument("--rho", type=float, default=0.6)
    ap.add_argument("--lag", type=float, default=10.0)
    ap.add_argument("--intervalo", type=float, default=60.0, help="segundos reais entre ciclos")
    ap.add_argument("--publicar", choices=["local", "pages"], default="local")
    ap.add_argument("--ciclos", type=int, default=0, help="0 = ate o fim")
    ap.add_argument("--bu-db", default=str(BU_DB), help="banco do bu_crawler")
    ap.add_argument("--sem-feed", action="store_true", help="ao vivo so com boletins (sem o feed do TSE)")
    a = ap.parse_args()
    BU_DB = Path(a.bu_db)

    LIVE_DIR.joinpath("log").mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                        handlers=[logging.StreamHandler(sys.stdout),
                                  logging.FileHandler(LIVE_DIR / "log" / f"ciclo_{dt.date.today():%Y%m%d}.log",
                                                      encoding="utf-8")])
    ctx = Contexto(a.modo, a.turno)
    fonte = (ReplayFeed(ctx, a.inicio, a.velocidade, a.rho, a.lag) if a.modo == "replay"
             else FeedAoVivo(ctx, a.sem_feed))
    desde_bu = 0.0
    pub = Publicador(a.publicar)
    est = Estaduais(ctx)
    dep = Deputados(ctx)
    params = Params()
    n = 0
    while True:
        t0 = time.time()
        try:
            feed, obs, instante = fonte.le()
            r = ctx.nd.estima(obs, feed, params)
            saida = monta_saida(ctx, r, instante)
            pct_uf = {u: s["pct_secoes"] for u, s in r["uf"].items()}
            tela = getattr(fonte, "tela_estadual", lambda: {})()
            if a.modo == "ao-vivo":
                pct_uf.update(getattr(fonte, "pct_estadual", lambda: {})())
            t_est = time.time()
            govs, sens = est.paineis(obs, pct_uf, tela)
            logging.info("estaduais: %d governos, %d senados projetados [%.1fs]",
                         sum(g.get("projetado", False) for g in govs), sum(g.get("projetado", False) for g in sens),
                         time.time() - t_est)
            if n % 5 == 0:
                dep.dispara(obs)
            escreve(ctx, r, saida, a.publicar, govs, sens, dep.res)
            if a.modo == "ao-vivo" and n % 10 == 0:        # status das fontes (o workflow fica quieto a noite)
                subprocess.run([sys.executable, str(RAIZ / "tools" / "checa_fontes.py"), str(DOCS / "live.json")],
                               cwd=RAIZ, capture_output=True, timeout=120)
            if a.modo == "ao-vivo":
                from runner.exporta_bu import exporta
                t_ex = time.time()
                n_ex, desde_bu = exporta(ctx.nd.anc, BU_DB, DOCS / "live" / "mun", desde_bu)
                if n_ex:
                    logging.info("boletins exportados para o mapa: %d municipios [%.1fs]", n_ex, time.time() - t_ex)
            st = pub(saida["instante"])
            pr = saida["pr"]
            logging.info("%s  %5.1f%% apurado  %s %.2f%% x %s %.2f%%  margem %+.2f (tela %s)  sigma %.2f  "
                         "P(%s)=%.3f  bu=%d  [%s, %.1fs]",
                         saida["instante"], saida["pct_secoes"], ctx.nomes["esq"], pr["sh_esq"],
                         ctx.nomes["dir"], pr["sh_dir"], pr["margem"], pr["tela_margem"], pr["sigma"],
                         pr["lider"], pr["p_lider"], saida["n_bu"], st, time.time() - t0)
            (LIVE_DIR / "estado_ciclo.json").write_text(json.dumps(
                {"ciclo": n, "instante": saida["instante"], "pct": saida["pct_secoes"], "margem": pr["margem"],
                 "sigma": pr["sigma"], "publicacao": st, "gerado_em": saida["gerado_em"]}), "utf-8")
        except Exception:                                  # inclui MemoryError: pula o ciclo, nao a noite
            logging.exception("ciclo perdido; seguindo no proximo")
            time.sleep(max(30.0, a.intervalo - (time.time() - t0)))
            n += 1
            continue
        n += 1
        if a.ciclos and n >= a.ciclos:
            break
        if a.modo == "replay" and fonte.agora() > fonte.fim:
            break
        time.sleep(max(0.0, a.intervalo - (time.time() - t0)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
