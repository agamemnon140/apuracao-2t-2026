"""Crawler de boletins de urna: todas as secoes, na ordem que mais ajuda o needle.

Por secao: aux.json (lista os arquivos da urna e diz se ja foi totalizada) -> imgbu.dat
(texto do boletim) -> runner/imgbu.parse -> sqlite. Retomavel: o estado de cada secao vive
em live/bu.sqlite; matar e reiniciar o processo nao perde nada.

Prioridade: municipios em que o feed ja contou mais secoes do que temos raspadas
(o boletim certamente existe), e dentro deles as secoes mais heterogeneas primeiro.
Secao ainda nao totalizada volta para a fila com espera crescente.

Concorrencia adaptativa: comeca em 8 conexoes; a cada janela de 200 respostas, se mais de
2% vierem 403/429/5xx/erro de rede, corta pela metade e pausa 30 s; se vier tudo limpo,
sobe 4 (teto 48). O Akamai do TSE decide o ritmo, nao nos.

Uso:
  .venv/Scripts/python -m runner.bu_crawler                      usa live/config_2026.json
  .venv/Scripts/python -m runner.bu_crawler --ciclo ele2024 --pleito 452 --ufs ac --limite 300
  .venv/Scripts/python -m runner.bu_crawler --status
"""
from __future__ import annotations

import argparse
import json
import random
import sqlite3
import sys
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path

import numpy as np
import pandas as pd

from runner import budat, imgbu
from tools.rede import get, get_json
from sintetico.caminhos import SAIDA as SAIDA_SINT, VIVO

BASE = "https://resultados.tse.jus.br"
LIVE = VIVO
DB = LIVE / "bu.sqlite"
N_MIN, N_MAX, N_INI = 2, 48, 8

ESQUEMA = """
CREATE TABLE IF NOT EXISTS secoes (uf TEXT, mun INT, zona INT, secao INT, status TEXT DEFAULT 'pendente',
  tentativas INT DEFAULT 0, prox REAL DEFAULT 0, prio REAL DEFAULT 0, hr TEXT, erro TEXT,
  PRIMARY KEY (uf, mun, zona, secao));
CREATE INDEX IF NOT EXISTS ix_fila ON secoes(status, prox);
CREATE TABLE IF NOT EXISTS resumo (uf TEXT, mun INT, zona INT, secao INT, cargo TEXT, aptos INT,
  comparecimento INT, nominais INT, legenda INT, brancos INT, nulos INT, total INT, coletado REAL,
  PRIMARY KEY (uf, mun, zona, secao, cargo));
CREATE TABLE IF NOT EXISTS votos (uf TEXT, mun INT, zona INT, secao INT, cargo TEXT, nr TEXT, votos INT,
  PRIMARY KEY (uf, mun, zona, secao, cargo, nr));
"""


def conecta(db: Path = DB) -> sqlite3.Connection:
    db.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(db, timeout=30, check_same_thread=False)
    c.execute("PRAGMA journal_mode=WAL")
    c.executescript(ESQUEMA)
    return c


def url_aux(amb, ciclo, pleito, uf, mun, zona, secao):
    d = f"{BASE}/{amb}/{ciclo}/arquivo-urna/{pleito}/dados/{uf}/{mun:05d}/{zona:04d}/{secao:04d}"
    return d, f"{d}/p{int(pleito):06d}-{uf}-m{mun:05d}-z{zona:04d}-s{secao:04d}-aux.json"


def semeia(con: sqlite3.Connection, ufs: list[str], pleito) -> int:
    """Universo a partir de live/cs/{uf}.json (so secoes principais: agregadas vem no BU dela)."""
    n = 0
    heter = {}
    h = SAIDA_SINT / "heterogeneidade_2022.parquet"
    if h.exists():
        d = pd.read_parquet(h)
        heter = dict(zip(d["cd_mun"].astype(int), d["H"].astype(float)))
    for uf in ufs:
        arq = LIVE / "cs" / str(pleito) / f"{uf}.json"
        if not arq.exists():
            print(f"  sem {arq}")
            continue
        j = json.loads(arq.read_text("utf-8"))
        linhas = []
        for a in j["abr"]:
            for m in a["mu"]:
                mun = int(m["cd"])
                for z in m["zon"]:
                    for s in z["sec"]:
                        if "nsp" in s:
                            continue
                        linhas.append((a["cd"], mun, int(z["cd"]), int(s["ns"]), heter.get(mun, 0.1) + random.random() * 1e-3))
        con.executemany("INSERT OR IGNORE INTO secoes(uf, mun, zona, secao, prio) VALUES (?,?,?,?,?)", linhas)
        n += len(linhas)
    con.commit()
    return n


def prioridade_feed(con: sqlite3.Connection) -> None:
    """Sobe a prioridade dos municipios em que o feed ja contou mais secoes que o crawler."""
    arq = LIVE / "feed_atual.json"
    if not arq.exists():
        return
    try:
        feed = json.loads(arq.read_text("utf-8"))
    except Exception:
        return
    st = {(f["uf"], int(f["cd_mun"])): f["st"] for f in feed
          if f.get("nivel") == "mu" and f.get("cargo") == "0001" and f.get("st") is not None}
    ok = dict(((u, m), n) for u, m, n in con.execute(
        "SELECT uf, mun, COUNT(*) FROM secoes WHERE status='ok' GROUP BY uf, mun"))
    quentes = [(u, m) for (u, m), s in st.items() if s > ok.get((u, m), 0)]
    con.execute("UPDATE secoes SET prio = prio - CAST(prio AS INT) WHERE prio >= 10")   # zera o bonus antigo
    con.executemany("UPDATE secoes SET prio = prio + 10, prox = 0 WHERE uf=? AND mun=? AND status!='ok'", quentes)
    con.commit()


def uma_secao(amb, ciclo, pleito, uf, mun, zona, secao, so_aux=False):
    """-> (status, dados|None, http, erro). status: ok | aguardando | sem_imgbu | parse_erro | erro | dry"""
    d, u = url_aux(amb, ciclo, pleito, uf, mun, zona, secao)
    st, j = get_json(u, timeout=15, tentativas=1)
    if st != 200 or not j:
        return ("aguardando" if st == 404 else "erro"), None, st, f"aux HTTP {st}"
    # 2022: "Totalizado"; 2026: "Recebido" (o imgbu ja esta publicado na recepcao)
    hs = [h for h in j.get("hashes", []) if str(h.get("st", "")).lower().startswith(("totaliz", "receb"))]
    if not hs:
        return "aguardando", None, st, j.get("st", "")
    h = hs[-1]
    if so_aux:
        return "dry", {"hr": f"{h.get('dr')} {h.get('hr')}"}, st, None
    # 2026: o imgbu (texto) sumiu do arquivo-urna; o bu.dat (DER) e o caminho principal
    arq = next((a["nm"] for a in h.get("arq", []) if a.get("tp") == "bu"), None)
    parser = budat.parse
    if not arq:
        arq = next((a["nm"] for a in h.get("arq", []) if a.get("tp") == "imgbu"), None)
        parser = imgbu.parse
    if not arq:
        return "sem_imgbu", {"hr": f"{h.get('dr')} {h.get('hr')}"}, st, "sem bu/imgbu"
    st2, b = get(f"{d}/{h['hash']}/{arq}", timeout=20, tentativas=1)
    if st2 != 200:
        return "erro", None, st2, f"bu HTTP {st2}"
    try:
        bu = parser(b)
    except (ValueError, IndexError, KeyError) as e:
        return "parse_erro", None, st2, f"{type(e).__name__}: {e}"[:200]
    bu["hr"] = f"{h.get('dr')} {h.get('hr')}"
    return "ok", bu, st2, None


def grava(con, uf, mun, zona, secao, status, bu, erro, agora):
    if status == "ok":
        for nome, c in bu["cargos"].items():
            con.execute("INSERT OR REPLACE INTO resumo VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (uf, mun, zona, secao, nome, bu.get("aptos"), bu.get("comparecimento"), c["nominais"],
                         c["legenda_total"], c["brancos"], c["nulos"], c["total"], agora))
            con.executemany("INSERT OR REPLACE INTO votos VALUES (?,?,?,?,?,?,?)",
                            [(uf, mun, zona, secao, nome, nr, v) for nr, v in c["cands"].items()]
                            + [(uf, mun, zona, secao, nome, "L" + p, v) for p, v in c["legenda"].items()])
        con.execute("UPDATE secoes SET status='ok', hr=?, erro=NULL WHERE uf=? AND mun=? AND zona=? AND secao=?",
                    (bu.get("hr"), uf, mun, zona, secao))
    else:
        espera = {"aguardando": 90, "erro": 30, "sem_imgbu": 600, "parse_erro": 3600, "dry": 1e9}[status]
        con.execute("UPDATE secoes SET status=?, tentativas=tentativas+1, erro=?, "
                    "prox=? + ? * MIN(8, tentativas + 1) WHERE uf=? AND mun=? AND zona=? AND secao=?",
                    (status if status != "aguardando" else "pendente", erro, agora, espera, uf, mun, zona, secao))


def roda(amb, ciclo, pleito, ufs, limite=0, so_aux=False, db=DB):
    con = conecta(db)
    n = semeia(con, ufs, pleito)
    print(f"universo: {n:,} secoes principais em {len(ufs)} UFs", flush=True)
    N = N_INI
    feitos, janela, t0, t_prio = 0, [], time.time(), 0
    trava = threading.Lock()
    with ThreadPoolExecutor(N_MAX) as ex:
        voando = {}
        while True:
            agora = time.time()
            if agora - t_prio > 60:
                prioridade_feed(con); t_prio = agora
            vagas = N - len(voando)
            if vagas > 0:
                fila = con.execute("SELECT uf, mun, zona, secao FROM secoes WHERE status IN ('pendente','erro') "
                                   "AND prox <= ? ORDER BY prio DESC LIMIT ?", (agora, vagas + len(voando))).fetchall()
                em_voo = set(voando.values())
                for k in [k for k in fila if k not in em_voo][:vagas]:
                    fut = ex.submit(uma_secao, amb, ciclo, pleito, *k, so_aux)
                    voando[fut] = k
            if not voando:
                pend = con.execute("SELECT MIN(prox) FROM secoes WHERE status IN ('pendente','erro')").fetchone()[0]
                if pend is None:
                    print("fila vazia: todas as secoes resolvidas", flush=True)
                    break
                time.sleep(min(10.0, max(0.5, pend - time.time())))
                continue
            prontos, _ = wait(list(voando), timeout=5, return_when=FIRST_COMPLETED)
            for fut in prontos:
                k = voando.pop(fut)
                try:
                    status, bu, http, erro = fut.result()
                except Exception as e:
                    status, bu, http, erro = "erro", None, -1, str(e)[:200]
                with trava:
                    grava(con, *k, status, bu, erro, time.time())
                feitos += 1
                janela.append(http in (403, 429) or http >= 500 or http < 0)
            con.commit()
            if len(janela) >= 200:
                taxa = sum(janela) / len(janela)
                if taxa > 0.02:
                    N = max(N_MIN, N // 2)
                    print(f"  {taxa:.1%} de erro/bloqueio: concorrencia -> {N}, pausa 30 s", flush=True)
                    time.sleep(30)
                elif taxa == 0:
                    N = min(N_MAX, N + 4)
                janela = []
                ok = con.execute("SELECT COUNT(*) FROM secoes WHERE status='ok'").fetchone()[0]
                print(f"  {feitos:,} respostas em {time.time() - t0:.0f}s ({feitos / (time.time() - t0):.1f}/s) "
                      f"N={N}  ok={ok:,}", flush=True)
            if limite and feitos >= limite:
                break
    mostra_status(con)


def mostra_status(con=None) -> None:
    con = con or conecta()
    print(pd.read_sql("SELECT status, COUNT(*) n FROM secoes GROUP BY status", con).to_string(index=False))
    print(pd.read_sql("SELECT erro, COUNT(*) n FROM secoes WHERE erro IS NOT NULL GROUP BY erro ORDER BY n DESC LIMIT 8",
                      con).to_string(index=False))


def observadas(nd, nr_esq: str, nr_dir: str, db: Path = DB) -> dict | None:
    """Urnas raspadas do PRESIDENTE casadas com a ancora do needle."""
    con = sqlite3.connect(db, timeout=30)
    r = pd.read_sql("SELECT uf, mun, zona, secao, comparecimento, nominais, brancos, nulos FROM resumo "
                    "WHERE cargo='PRESIDENTE'", con)
    if r.empty:
        return None
    v = pd.read_sql(f"SELECT uf, mun, zona, secao, nr, votos FROM votos WHERE cargo='PRESIDENTE' "
                    f"AND nr IN ('{nr_esq}', '{nr_dir}')", con)
    con.close()
    p = v.pivot_table(index=["uf", "mun", "zona", "secao"], columns="nr", values="votos", aggfunc="sum").reset_index()
    r = r.merge(p, on=["uf", "mun", "zona", "secao"], how="left").fillna(0)
    chave = pd.MultiIndex.from_frame(nd.anc[["uf", "cd_mun", "zona", "secao"]].assign(uf=lambda d: d["uf"].str.upper()))
    pos = pd.Series(np.arange(nd.n), index=chave)
    k = pd.MultiIndex.from_arrays([r["uf"].str.upper(), r["mun"].astype(int), r["zona"].astype(int), r["secao"].astype(int)])
    idx = pos.reindex(k).to_numpy()
    ok = ~np.isnan(idx)
    r = r[ok]
    esq = r.get(nr_esq, 0) if nr_esq in r else pd.Series(0, index=r.index)
    dir_ = r.get(nr_dir, 0) if nr_dir in r else pd.Series(0, index=r.index)
    return {"idx": idx[ok].astype(int), "esq": esq.to_numpy(float), "dir": dir_.to_numpy(float),
            "out": (r["nominais"] - esq - dir_).clip(lower=0).to_numpy(float),
            "bn": (r["brancos"] + r["nulos"]).to_numpy(float)}


def main() -> int:
    global N_MAX, N_INI
    ap = argparse.ArgumentParser()
    ap.add_argument("--ambiente", default="oficial")
    ap.add_argument("--ciclo"); ap.add_argument("--pleito")
    ap.add_argument("--ufs", default="")
    ap.add_argument("--limite", type=int, default=0)
    ap.add_argument("--dry-run", action="store_true", help="so aux.json (mede caminho e ritmo)")
    ap.add_argument("--db", default=str(DB))
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--turno", default="1")
    ap.add_argument("--teto", type=int, default=N_MAX, help="concorrencia maxima (divide o IP com o coletor do feed)")
    a = ap.parse_args()
    N_MAX = max(N_MIN, a.teto)
    N_INI = min(N_INI, N_MAX)
    if a.status:
        mostra_status(conecta(Path(a.db)))
        return 0
    ciclo, pleito = a.ciclo, a.pleito
    if not (ciclo and pleito):
        cfg = json.loads((LIVE / "config_2026.json").read_text("utf-8"))
        ciclo, pleito = cfg["ciclo"], cfg["turnos"][a.turno]["pleito"]
    from runner.coletor import UFS
    ufs = [u.strip().lower() for u in a.ufs.split(",") if u.strip()] or UFS + ["zz"]
    if not all((LIVE / "cs" / str(pleito) / f"{u}.json").exists() for u in ufs):
        from runner.coletor import url_cs
        (LIVE / "cs" / str(pleito)).mkdir(parents=True, exist_ok=True)
        for u in ufs:
            st, b = get(url_cs(a.ambiente, ciclo, pleito, u))
            if st == 200:
                (LIVE / "cs" / str(pleito) / f"{u}.json").write_bytes(b)
    roda(a.ambiente, ciclo, pleito, ufs, a.limite, a.dry_run, Path(a.db))
    return 0


if __name__ == "__main__":
    sys.exit(main())
