"""Coletor do feed de resultados do TSE para a noite de 2026.

Tres camadas, todas normalizadas no mesmo formato ("leitura"):
  -e  resultado por abrangencia (br e UFs), 1 req por cargo+abrangencia. Em 2026 a arvore
      dados-simplificados/-r de 2022/24 sumiu do servidor; o app oficial passou a ler
      {ele}/dados/{abr}/{abr}-c{cargo}-e{ele}-e.json. O miolo pode vir flat (estilo -r),
      em blocos aninhados (estilo -u) ou como lista "abr" (estilo -e de 2024):
      parse_feed_abr detecta.
  -ab {ele}/dados/br/br-e{ele}-ab.json (novo em 2026): secoes totalizadas (st/ts),
      eleitorado e comparecimento por UF — alimenta o nivel uf quando o -e nao traz.
  -u  um municipio, um cargo por arquivo; traz secoes totalizadas (st/ts), comparecimento,
      brancos, nulos e votos por candidato (mesmo caminho/esquema de 2024; conferido
      zerado no ar em 04/10/2026)

Leitura (dict):
  nivel "br"|"uf"|"mu", uf (minusculo), cd_mun (int|None), ele (int), cargo ("0001"...),
  ts (secoes), st (totalizadas), e (eleitorado), ea (eleitorado das secoes totalizadas),
  c (comparecimento), vb, vn, vv,
  cand {nr: votos}, leg {nr_partido: votos de legenda} (proporcional), dt/ht (totalizacao)

Codigos da eleicao sao descobertos em runtime no ele-c.json (nunca cravados); um
live/config_2026.json com "manual": true tem precedencia (override do dia).

Uso:
  .venv/Scripts/python -m runner.coletor --descobre            grava live/config_2026.json
  .venv/Scripts/python -m runner.coletor --manual PLEITO [6257 6259] [--t2]   override do dia
  .venv/Scripts/python -m runner.coletor --malhas              baixa cm/cs (1x)
  .venv/Scripts/python -m runner.coletor --teste               parseia fixtures e URLs reais 2022/2024
  .venv/Scripts/python -m runner.coletor --ciclo               um ciclo de coleta
"""
from __future__ import annotations

import datetime as dt
import gzip
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from tools.rede import get, get_json
from sintetico.caminhos import DADOS

BASE = "https://resultados.tse.jus.br"
DADOS = DADOS
LIVE = DADOS / "live"
RAIZ = Path(__file__).resolve().parents[1]
FIXT = RAIZ / "tests" / "fixtures"

CARGOS = {"0001": "presidente", "0003": "governador", "0005": "senador",
          "0006": "depfederal", "0007": "depestadual", "0008": "depestadual"}   # 0008 = distrital
UFS = ["ac", "al", "am", "ap", "ba", "ce", "df", "es", "go", "ma", "mg", "ms", "mt", "pa", "pb",
       "pe", "pi", "pr", "rj", "rn", "ro", "rr", "rs", "sc", "se", "sp", "to"]
DATA_T1, DATA_T2 = "04/10/2026", "25/10/2026"
# orcamento de -u por ciclo e por cargo (presidente: todos os municipios ainda abertos)
ORCAMENTO_U = {"0001": 6000, "0003": 1500, "0005": 1500}
THREADS = 16
TIMEOUT_U = 8.0      # segundos; o Akamai tarpita conexoes em excesso -- melhor perder a leitura do que travar o ciclo


# ---------------------------------------------------------------- URLs
def url_ab(amb, ciclo, ele, abr):
    return f"{BASE}/{amb}/{ciclo}/{ele}/dados/{abr}/{abr}-e{int(ele):06d}-ab.json"


def url_e(amb, ciclo, ele, uf, cargo):
    return f"{BASE}/{amb}/{ciclo}/{ele}/dados/{uf}/{uf}-c{cargo}-e{int(ele):06d}-e.json"


def url_u(amb, ciclo, ele, uf, mun, cargo):
    return f"{BASE}/{amb}/{ciclo}/{ele}/dados/{uf}/{uf}{int(mun):05d}-c{cargo}-e{int(ele):06d}-u.json"


def url_cm(amb, ciclo, ele):
    return f"{BASE}/{amb}/{ciclo}/{ele}/config/mun-e{int(ele):06d}-cm.json"


def url_cs(amb, ciclo, pleito, uf):
    return f"{BASE}/{amb}/{ciclo}/arquivo-urna/{pleito}/config/{uf}/{uf}-p{int(pleito):06d}-cs.json"


# ---------------------------------------------------------------- parse
def _i(x) -> int:
    try:
        return int(str(x).replace(".", "").strip() or 0)
    except ValueError:
        return 0


def parse_r(j: dict, cargo: str) -> dict:
    s = j.get("s")
    if isinstance(s, dict):          # blocos aninhados estilo -u (visto nos arquivos de 2026)
        e, v = j.get("e", {}), j.get("v", {})
        tot = {"ts": _i(s.get("ts")), "st": _i(s.get("st")), "e": _i(e.get("te")),
               "ea": _i(e.get("est")), "c": _i(e.get("c")), "vb": _i(v.get("vb")),
               "vn": _i(v.get("tvn", v.get("vn"))), "vv": _i(v.get("vv"))}
    else:                            # flat, estilo -r de 2022/24
        tot = {"ts": _i(s), "st": _i(j.get("st")), "e": _i(j.get("e")), "ea": _i(j.get("ea")),
               "c": _i(j.get("c")), "vb": _i(j.get("vb")), "vn": _i(j.get("tvn", j.get("vn"))),
               "vv": _i(j.get("vv"))}
    return {"nivel": j.get("tpabr", "uf"), "uf": j.get("cdabr", ""), "cd_mun": None,
            "ele": _i(j.get("ele")), "cargo": cargo, **tot,
            "cand": {c["n"]: _i(c.get("vap")) for c in j.get("cand", [])}, "leg": {},
            "dt": j.get("dt", ""), "ht": j.get("ht", "")}


def parse_feed_abr(j: dict, cargo: str, abr: str) -> list[dict]:
    """Arquivo {abr}-c{cargo}-e{ele}-e.json de 2026, esquema detectado em runtime:
    "carg" -> estilo -u (uma leitura da propria abrangencia); "cand" no topo -> flat
    estilo -r; lista "abr" -> uma leitura por entrada (uf dentro de br, municipio
    dentro de uf). Municipio dentro do arquivo br e descartado (vem sem a uf certa;
    os arquivos por UF e o -u cobrem)."""
    if j.get("carg") is not None:
        ler = parse_u(j, abr)
        cd = str(j.get("cdabr", ""))
        if not cd.isdigit():
            ler.update({"nivel": j.get("tpabr", "uf"), "uf": cd, "cd_mun": None})
        ler["cargo"] = ler["cargo"] or cargo
        return [ler]
    if j.get("cand") is not None:
        return [parse_r(j, cargo)]
    uf_pai = str(j.get("cdabr", ""))
    out = []
    for m in j.get("abr", []):
        cd = str(m.get("cdabr", ""))
        eh_mun = cd.isdigit()
        if eh_mun and uf_pai == "br":
            continue
        s, e, v = m.get("s") or {}, m.get("e") or {}, m.get("v") or {}
        tem_s = bool(s)
        out.append({"nivel": "mu" if eh_mun else "uf", "uf": uf_pai if eh_mun else cd,
                    "cd_mun": _i(cd) if eh_mun else None, "ele": _i(j.get("ele")), "cargo": cargo,
                    "ts": _i(s.get("ts")) if tem_s else None, "st": _i(s.get("st")) if tem_s else None,
                    "e": _i(e.get("te")) if e else None, "ea": _i(e.get("est")) if e else None,
                    "c": _i(e.get("c")) if e else None,
                    "vb": _i(v.get("vb")) if v else None,
                    "vn": _i(v.get("tvn", v.get("vn"))) if v else None,
                    "vv": _i(v.get("vv")) if v else None,
                    "cand": {c["n"]: _i(c.get("vap")) for c in m.get("cand", [])}, "leg": {},
                    "dt": m.get("dt", ""), "ht": m.get("ht", "")})
    return out


def parse_ab(j: dict) -> dict:
    """br-e{ele}-ab.json -> {cdabr: {ts, st, e, ea, c, dt, ht}} (so entradas nao municipais)."""
    out = {}
    for m in j.get("abr", []):
        cd = str(m.get("cdabr", ""))
        if cd.isdigit():
            continue
        s, e = m.get("s") or {}, m.get("e") or {}
        out[cd] = {"ts": _i(s.get("ts")), "st": _i(s.get("st")), "e": _i(e.get("te")),
                   "ea": _i(e.get("est")), "c": _i(e.get("c")),
                   "dt": m.get("dt", ""), "ht": m.get("ht", "")}
    return out


def parse_u(j: dict, uf: str) -> dict:
    s, e, v = j.get("s", {}), j.get("e", {}), j.get("v", {})
    cand, leg, cargo = {}, {}, ""
    for cg in j.get("carg", []):
        cargo = f"{_i(cg.get('cd')):04d}"
        for agr in cg.get("agr", []):
            for par in agr.get("par", []):
                nom = 0
                for c in par.get("cand", []):
                    cand[c["n"]] = _i(c.get("vap"))
                    nom += _i(c.get("vap"))
                # tvan = nominais + legenda do partido; tvtn = so nominais (iguais no majoritario)
                lg = _i(par.get("tvan")) - _i(par.get("tvtn"))
                if lg > 0:
                    leg[par.get("n", "")] = lg
    return {"nivel": "mu", "uf": uf, "cd_mun": _i(j.get("cdabr")), "ele": _i(j.get("ele")),
            "cargo": cargo, "ts": _i(s.get("ts")), "st": _i(s.get("st")),
            "e": _i(e.get("te")), "ea": _i(e.get("est")), "c": _i(e.get("c")), "vb": _i(v.get("vb")),
            "vn": _i(v.get("tvn", v.get("vn"))), "vv": _i(v.get("vv")),
            "cand": cand, "leg": leg, "dt": j.get("dt", ""), "ht": j.get("ht", "")}


def parse_e(j: dict, cargo: str) -> list[dict]:
    uf = j.get("cdabr", "")
    out = []
    for m in j.get("abr", []):
        out.append({"nivel": "mu", "uf": uf, "cd_mun": _i(m.get("cdabr")), "ele": _i(j.get("ele")),
                    "cargo": cargo, "ts": None, "st": None, "e": None, "ea": None, "c": None,
                    "vb": None, "vn": None, "vv": None,
                    "cand": {c["n"]: _i(c.get("vap")) for c in m.get("cand", [])}, "leg": {},
                    "dt": m.get("dt", ""), "ht": m.get("ht", "")})
    return out


# ---------------------------------------------------------------- descoberta
def descobre(ambiente: str = "oficial", datas=(DATA_T1, DATA_T2)) -> dict | None:
    """Le ele-c.json (com cache-buster) e monta a config das eleicoes nas datas pedidas.
    Respeita live/config_2026.json com "manual": true."""
    arq = LIVE / "config_2026.json"
    if arq.exists():
        atual = json.loads(arq.read_text("utf-8"))
        if atual.get("manual"):
            return atual
    st, j = get_json(f"{BASE}/{ambiente}/comum/config/ele-c.json?t={int(time.time())}")
    if st != 200 or not j:
        print(f"ele-c.json: HTTP {st}")
        return None
    # as vesperas de 2026 o indice veio com "c" nulo: o ciclo segue o ano da eleicao
    ciclo = j.get("c") or ("ele" + datas[0][-4:])
    cfg = {"ambiente": ambiente, "ciclo": ciclo, "indice_gerado": f"{j.get('dg')} {j.get('hg')}",
           "descoberto_em": dt.datetime.now().isoformat(timespec="seconds"), "turnos": {}}
    for p in j.get("pl", []):
        if p.get("dt") not in datas:
            continue
        turno = "1" if p["dt"] == datas[0] else "2"
        eles = []
        for e in p.get("e", []):
            cargos = sorted({f"{_i(c['cd']):04d}" for a in e.get("abr", []) for c in a.get("cp", [])})
            ufs = sorted({a["cd"] for a in e.get("abr", [])})
            eles.append({"ele": e["cd"], "t": e.get("t"), "nome": e.get("nm", ""), "cargos": cargos,
                         "abr": ufs})
        cfg["turnos"][turno] = {"pleito": p["cd"], "data": p["dt"], "eleicoes": eles}
    if not cfg["turnos"]:
        print(f"ele-c.json (ciclo {cfg['ciclo']}, gerado {cfg['indice_gerado']}): sem eleicao em {datas}")
        return None
    LIVE.mkdir(parents=True, exist_ok=True)
    arq.write_text(json.dumps(cfg, ensure_ascii=False, indent=1), "utf-8")
    return cfg


def config_manual(pleito: str, ciclo: str = "ele2026", ele_fed: str = "6257", ele_est: str = "6259",
                  turno: str = "1", ambiente: str = "oficial") -> dict:
    """Override do dia: grava live/config_2026.json com "manual": true (descobre() passa a
    respeita-lo). Codigos de eleicao de 2026 vieram de consulta_cand_2026 (CD_ELEICAO):
    6257 = presidente, 6259 = estaduais. O pleito so aparece no ele-c.json ou na URL do app."""
    arq = LIVE / "config_2026.json"
    cfg = json.loads(arq.read_text("utf-8")) if arq.exists() else {"turnos": {}}
    cfg.update({"manual": True, "ambiente": ambiente, "ciclo": ciclo,
                "descoberto_em": dt.datetime.now().isoformat(timespec="seconds")})
    cfg["turnos"][turno] = {"pleito": pleito, "data": DATA_T1 if turno == "1" else DATA_T2, "eleicoes": [
        {"ele": ele_fed, "t": turno, "nome": "federal (manual)", "cargos": ["0001"], "abr": ["br"]},
        {"ele": ele_est, "t": turno, "nome": "estadual (manual)",
         "cargos": ["0003", "0005", "0006", "0007", "0008"], "abr": [u for u in UFS]}]}
    LIVE.mkdir(parents=True, exist_ok=True)
    arq.write_text(json.dumps(cfg, ensure_ascii=False, indent=1), "utf-8")
    return cfg


def eleicao_do_cargo(cfg: dict, turno: str, cargo: str) -> str | None:
    for e in cfg["turnos"].get(turno, {}).get("eleicoes", []):
        if cargo in e["cargos"]:
            return e["ele"]
    return None


def baixa_malhas(cfg: dict, turno: str = "1") -> None:
    """cm (municipio -> zonas, IBGE) por eleicao e cs (municipio -> zona -> secao) por UF."""
    amb, ciclo = cfg["ambiente"], cfg["ciclo"]
    t = cfg["turnos"][turno]
    for e in t["eleicoes"]:
        st, b = get(url_cm(amb, ciclo, e["ele"]))
        print(f"cm {e['ele']}: HTTP {st} {len(b):,} B")
        if st == 200:
            (LIVE / f"cm-{e['ele']}.json").write_bytes(b)
    d = LIVE / "cs" / str(t["pleito"])
    d.mkdir(parents=True, exist_ok=True)
    for uf in UFS + ["zz"]:
        st, b = get(url_cs(amb, ciclo, t["pleito"], uf))
        if st == 200:
            (d / f"{uf}.json").write_bytes(b)
        print(f"cs {uf}: HTTP {st} {len(b):,} B")


def municipios(cfg: dict, ele: str) -> list[tuple[str, int]]:
    """(uf, cd_mun) da malha cm; sem cm, do universo 2026 dos dados abertos."""
    arq = LIVE / f"cm-{ele}.json"
    if arq.exists():
        j = json.loads(arq.read_text("utf-8"))
        return [(a["cd"], int(m["cd"])) for a in j["abr"] for m in a.get("mu", [])]
    import pandas as pd
    m = pd.read_parquet(DADOS / "sintetico" / "municipios_2026.parquet", columns=["uf", "cd_mun"])
    return [(u.lower(), int(c)) for u, c in zip(m["uf"], m["cd_mun"])]


# ---------------------------------------------------------------- coleta
class Coletor:
    """Guarda a ultima leitura de cada (cargo, nivel, uf, mun) e decide o que buscar."""

    def __init__(self, cfg: dict, turno: str = "1", cargos=("0001", "0003", "0005", "0006", "0007")):
        self.cfg, self.turno, self.cargos = cfg, turno, [c for c in cargos
                                                         if eleicao_do_cargo(cfg, turno, c)]
        self.atual: dict[tuple, dict] = {}
        self.modo_e: dict[str, bool] = {}
        self.ultimo_u: dict[tuple, float] = {}
        self.n_ciclo = 0
        self.stats = {"req": 0, "erro": 0}

    def _busca(self, urls: list[str]) -> list[tuple[str, int, object]]:
        def um(u):
            try:
                st, j = get_json(u, timeout=TIMEOUT_U, tentativas=1)
            except Exception:       # inclui MemoryError: uma url perdida nao derruba a noite
                return u, 0, None
            return u, st, j
        with ThreadPoolExecutor(THREADS) as ex:
            res = list(ex.map(um, urls))
        self.stats["req"] += len(res)
        self.stats["erro"] += sum(1 for _, st, _ in res if st not in (200, 404))
        return res

    def _guarda(self, ler: dict, bruto_dir: Path | None, nome: str, j) -> None:
        k = (ler["cargo"], ler["nivel"], ler["uf"], ler["cd_mun"])
        self.atual[k] = ler
        if bruto_dir is not None:
            (bruto_dir / (nome + ".gz")).write_bytes(gzip.compress(json.dumps(j).encode()))

    def ciclo(self, guarda_bruto: bool = True) -> dict:
        amb, ciclo = self.cfg["ambiente"], self.cfg["ciclo"]
        agora = time.time()
        bruto = None
        if guarda_bruto:
            bruto = LIVE / "feed" / "raw" / dt.datetime.now().strftime("%Y%m%d_%H%M%S")
            bruto.mkdir(parents=True, exist_ok=True)
        t0, r0 = time.time(), self.stats["req"]

        # 1. resultado por abrangencia: BR (presidente) e UFs
        #    (2026: {abr}-c{cargo}-e{ele}-e.json; a arvore dados-simplificados/-r sumiu)
        urls = []
        for cg in self.cargos:
            ele = eleicao_do_cargo(self.cfg, self.turno, cg)
            abrs = (["br"] if cg == "0001" else []) + UFS
            if cg == "0008":
                abrs = ["df"]
            urls += [(cg, a, url_e(amb, ciclo, ele, a, cg)) for a in abrs]
        for (cg, a, _), (u, st, j) in zip(urls, self._busca([u for _, _, u in urls])):
            if st != 200 or not j:
                continue
            for ler in parse_feed_abr(j, cg, a):
                k = (ler["cargo"], ler["nivel"], ler["uf"], ler["cd_mun"])
                if ler["nivel"] == "mu" and ler.get("st") is None and \
                        k in self.atual and self.atual[k].get("st") is not None:
                    continue              # -u ja tem o municipio com contagem de secoes
                self.atual[k] = ler
            if bruto is not None:
                (bruto / (u.rsplit("/", 1)[1] + ".gz")).write_bytes(gzip.compress(json.dumps(j).encode()))

        # 1b. -ab (novo em 2026): st/ts, eleitorado e comparecimento por UF, por eleicao
        eles: dict[str, list[str]] = {}
        for cg in self.cargos:
            eles.setdefault(eleicao_do_cargo(self.cfg, self.turno, cg), []).append(cg)
        for ele, (u, st, j) in zip(eles, self._busca([url_ab(amb, ciclo, e, "br") for e in eles])):
            if st != 200 or not j:
                continue
            for cd, ab in parse_ab(j).items():
                nivel = "br" if cd == "br" else "uf"
                for cg in eles[ele]:
                    k = (cg, nivel, cd, None)
                    ler = self.atual.get(k)
                    if ler is None:
                        ler = {"nivel": nivel, "uf": cd, "cd_mun": None, "ele": _i(ele),
                               "cargo": cg, "cand": {}, "leg": {}, "vb": None, "vn": None,
                               "vv": None, "dt": "", "ht": ""}
                        self.atual[k] = ler
                    ler.update({c: ab[c] for c in ("ts", "st", "e", "ea", "c")})
            if bruto is not None:
                (bruto / (u.rsplit("/", 1)[1] + ".gz")).write_bytes(gzip.compress(json.dumps(j).encode()))

        # (o antigo passo 2, -e por UF, virou o proprio passo 1)

        # 3. -u por municipio, com orcamento e prioridade (aberto, grande, velho)
        for cg, orc in ORCAMENTO_U.items():
            if cg not in self.cargos:
                continue
            ele = eleicao_do_cargo(self.cfg, self.turno, cg)
            cand = []
            for uf, mun in municipios(self.cfg, ele):
                ler = self.atual.get((cg, "mu", uf, mun))
                if ler and ler.get("ts") and ler["st"] >= ler["ts"]:
                    continue                                   # municipio fechado
                idade = agora - self.ultimo_u.get((cg, uf, mun), 0)
                peso = (ler["ts"] - ler["st"]) if ler and ler.get("ts") else 50
                cand.append((-(idade * (1 + peso)), uf, mun))
            cand.sort()
            alvo = cand[:orc]
            us = [url_u(amb, ciclo, ele, uf, mun, cg) for _, uf, mun in alvo]
            for (_, uf, mun), (u, st, j) in zip(alvo, self._busca(us)):
                self.ultimo_u[(cg, uf, mun)] = agora
                if st == 200 and j:
                    ler = parse_u(j, uf)
                    ler["cargo"] = ler["cargo"] or cg
                    self._guarda(ler, bruto, u.rsplit("/", 1)[1], j)

        self.n_ciclo += 1
        res = {"ciclo": self.n_ciclo, "req": self.stats["req"] - r0, "seg": round(time.time() - t0, 1),
               "leituras": len(self.atual), "erros_acum": self.stats["erro"], "modo_e": self.modo_e}
        self.grava()
        return res

    def grava(self) -> None:
        LIVE.mkdir(parents=True, exist_ok=True)
        tmp = LIVE / "feed_atual.json.tmp"
        tmp.write_text(json.dumps([v for v in self.atual.values()], ensure_ascii=False), "utf-8")
        tmp.replace(LIVE / "feed_atual.json")


def le_feed() -> list[dict]:
    arq = LIVE / "feed_atual.json"
    return json.loads(arq.read_text("utf-8")) if arq.exists() else []


# ---------------------------------------------------------------- teste
def teste() -> int:
    ok = True
    r = parse_r(json.loads((FIXT / "br-c0001-e000544-r.json").read_text("utf-8")), "0001")
    print("r 2022 BR:", r["st"], "/", r["ts"], "c", r["c"], "13:", r["cand"]["13"], "22:", r["cand"]["22"])
    ok &= r["cand"]["13"] == 57259504 and r["cand"]["22"] == 51072345 and r["st"] == 472075
    u = parse_u(json.loads((FIXT / "ac01392-c0011-e000619-u.json").read_text("utf-8")), "ac")
    print("u 2024 Rio Branco:", u["cargo"], u["st"], "/", u["ts"], "c", u["c"], "vb", u["vb"], "vn", u["vn"],
          "soma cand", sum(u["cand"].values()), "vv", u["vv"])
    ok &= u["cd_mun"] == 1392 and sum(u["cand"].values()) == u["vv"] and u["st"] == 883
    e = parse_e(json.loads((FIXT / "ac-c0011-e000619-e.json").read_text("utf-8")), "0011")
    print("e 2024 AC:", len(e), "municipios; Rio Branco:", [x for x in e if x["cd_mun"] == 1392][0]["cand"])
    ok &= len(e) == 22
    # ao vivo, os mesmos arquivos
    # ao vivo: so o que importa para AMANHA (o TSE poda arvores de eleicoes passadas)
    st, j = get_json(f"{BASE}/oficial/comum/config/ele-c.json?t={int(time.time())}")
    print("ele-c.json ao vivo: HTTP", st, (f"gerado {j.get('dg')} {j.get('hg')}" if j else ""))
    ok &= st == 200
    st, _ = get(url_cm("oficial", "ele2026", 6257), tentativas=1)
    print("cm 2026 (presidente) ao vivo: HTTP", st)
    ok &= st == 200
    st, j = get_json(url_u("oficial", "ele2024", 619, "sp", 71072, "0011"), tentativas=1)
    print("u 2024 SP (so aviso se cair): HTTP", st)
    print("OK" if ok else "FALHOU")
    return 0 if ok else 1


def main() -> int:
    a = sys.argv[1:]
    if "--teste" in a:
        return teste()
    if "--manual" in a:
        # --manual PLEITO [ELE_FED ELE_EST] [--t2]
        i = a.index("--manual")
        args = [x for x in a[i + 1:] if not x.startswith("--")]
        cfg = config_manual(args[0], ele_fed=args[1] if len(args) > 1 else "6257",
                            ele_est=args[2] if len(args) > 2 else "6259", turno="2" if "--t2" in a else "1")
        print(json.dumps(cfg, ensure_ascii=False, indent=1))
        return 0
    if "--descobre" in a:
        cfg = descobre()
        print(json.dumps(cfg, ensure_ascii=False, indent=1) if cfg else "2026 ainda nao esta no indice")
        return 0 if cfg else 1
    cfg = descobre()
    if not cfg:
        return 1
    if "--malhas" in a:
        baixa_malhas(cfg, "2" if "--t2" in a else "1")
        return 0
    if "--ciclo" in a:
        c = Coletor(cfg, "2" if "--t2" in a else "1")
        print(c.ciclo())
    return 0


if __name__ == "__main__":
    sys.exit(main())
