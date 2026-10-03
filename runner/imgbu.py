"""Parser do boletim de urna impresso (imgbu.dat).

O imgbu e um envelope ASN.1 com o TEXTO do boletim embutido em latin-1 -- o mesmo que a
urna imprime. Nao precisa de decoder ASN.1: decodifica em latin-1, corta no marcador de
pagina ("--- 1 de N ---", depois dele vem assinatura binaria) e le por expressao regular.

Saida:
  {"mun", "zona", "local", "secao", "aptos", "comparecimento", "faltosos",
   "cargos": {"PRESIDENTE": {"cands": {nr: votos}, "legenda": {partido: votos},
                             "nominais", "legenda_total", "brancos", "nulos", "total"}}}

Invariantes checadas por cargo (falha -> ValueError; a urna nao entra no needle):
  soma dos candidatos == nominais; soma das legendas == total de legenda (se houver);
  nominais + legenda + brancos + nulos == total apurado.

Uso:  .venv/Scripts/python -m runner.imgbu arquivo-imgbu.dat
"""
from __future__ import annotations

import json
import re
import sys

R_CARGO = re.compile(r"^-{3,}\s*([A-ZÁÉÍÓÚÂÊÔÃÕÇ][A-ZÁÉÍÓÚÂÊÔÃÕÇ /º°0-9]*?)\s*-{3,}\s*$")
R_PAG = re.compile(r"^-{3,}\s*\d+\s+de\s+\d+\s*-{3,}\s*$")
R_CAND = re.compile(r"^\s{2}(\S.*?)?\s+(\d{2,5})\s+(\d{4,})\s*$")
R_PARTIDO = re.compile(r"^Partido:\s*(\d+)\s*-\s*(.+?)\s*$")
R_CAMPO = re.compile(r"^\s*(Eleitores aptos|Comparecimento|Eleitores faltosos|Total de votos Nominais|"
                     r"Total de votos de Legenda|Brancos|Nulos|Total Apurado|Votos de legenda|"
                     r"Munic[ií]pio|Zona Eleitoral|Local de Vota[çc][ãa]o|Se[çc][ãa]o Eleitoral)\s+(\d+)\s*$")


def texto(b: bytes) -> str:
    t = b.decode("latin-1", errors="replace")
    i = t.find("Boletim de Urna")
    if i < 0:
        raise ValueError("sem 'Boletim de Urna' no arquivo")
    t = t[i:]
    linhas = []
    for ln in t.split("\n"):
        if R_PAG.match(ln.strip()):
            break
        linhas.append(ln.rstrip("\r"))
    return "\n".join(linhas)


def parse(b: bytes) -> dict:
    out = {"cargos": {}}
    cargo = None
    partido = None
    for ln in texto(b).split("\n"):
        m = R_CARGO.match(ln.strip())
        if m:
            nome = m.group(1).strip()
            cargo = {"cands": {}, "legenda": {}, "nominais": None, "legenda_total": 0,
                     "brancos": None, "nulos": None, "total": None}
            out["cargos"][nome] = cargo
            partido = None
            continue
        m = R_PARTIDO.match(ln.strip())
        if m and cargo is not None:
            partido = m.group(1)
            continue
        m = R_CAMPO.match(ln)
        if m:
            k, v = m.group(1).lower(), int(m.group(2))
            if cargo is None:                                   # cabecalho da secao
                if k.startswith("munic"):
                    out["mun"] = v
                elif k.startswith("zona"):
                    out["zona"] = v
                elif k.startswith("local"):
                    out["local"] = v
                elif k.startswith("se"):
                    out["secao"] = v
                elif k == "eleitores aptos":
                    out["aptos"] = v
                elif k == "comparecimento":
                    out["comparecimento"] = v
                elif k == "eleitores faltosos":
                    out["faltosos"] = v
                continue
            if k == "votos de legenda" and partido:
                cargo["legenda"][partido] = v
            elif k == "total de votos nominais":
                cargo["nominais"] = v
            elif k == "total de votos de legenda":
                cargo["legenda_total"] = v
            elif k == "brancos":
                cargo["brancos"] = v
            elif k == "nulos":
                cargo["nulos"] = v
            elif k == "total apurado":
                cargo["total"] = v
            elif k == "eleitores aptos" and "aptos" not in out:
                out["aptos"] = v
            continue
        m = R_CAND.match(ln)
        if m and cargo is not None:
            nr, votos = m.group(2), int(m.group(3))
            cargo["cands"][nr] = cargo["cands"].get(nr, 0) + votos
    valida(out)
    return out


def valida(bu: dict) -> None:
    if not bu["cargos"]:
        raise ValueError("nenhum cargo encontrado")
    for nome, c in bu["cargos"].items():
        if c["total"] is None or c["nominais"] is None:
            raise ValueError(f"{nome}: rodape incompleto")
        if sum(c["cands"].values()) != c["nominais"]:
            raise ValueError(f"{nome}: candidatos {sum(c['cands'].values())} != nominais {c['nominais']}")
        if c["legenda"] and sum(c["legenda"].values()) != c["legenda_total"]:
            raise ValueError(f"{nome}: legendas {sum(c['legenda'].values())} != {c['legenda_total']}")
        soma = c["nominais"] + c["legenda_total"] + (c["brancos"] or 0) + (c["nulos"] or 0)
        if soma != c["total"]:
            raise ValueError(f"{nome}: {soma} != total apurado {c['total']}")


if __name__ == "__main__":
    bu = parse(open(sys.argv[1], "rb").read())
    resumo = {k: v for k, v in bu.items() if k != "cargos"}
    print(json.dumps(resumo, ensure_ascii=False))
    for nome, c in bu["cargos"].items():
        print(f"{nome}: {len(c['cands'])} candidatos, nominais {c['nominais']}, legenda {c['legenda_total']}, "
              f"brancos {c['brancos']}, nulos {c['nulos']}, total {c['total']}")
    print("invariantes OK")
