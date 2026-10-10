"""Parser do boletim de urna binario (bu.dat), DER/ASN.1 — novo caminho de 2026.

Em 2026 o TSE parou de publicar o imgbu.dat (texto impresso) no arquivo-urna; so o
bu.dat (EntidadeBoletimUrna em DER) esta no ar, e o proprio app oficial o decodifica
no navegador. Este modulo le o DER com um caminhador TLV proprio (sem dependencia da
spec): a estrutura foi levantada de boletins reais de 04/10/2026 e validada pelas
invariantes (nominais + legenda + brancos + nulos == comparecimento por cargo).

Saida: o MESMO contrato de runner/imgbu.parse:
  {"mun", "zona", "local", "secao", "aptos", "comparecimento", "faltosos",
   "cargos": {"PRESIDENTE": {"cands": {nr: votos}, "legenda": {partido: votos},
                             "nominais", "legenda_total", "brancos", "nulos", "total"}}}

Invariante violada ou estrutura inesperada -> ValueError (a urna nao entra no needle).

Uso:  .venv/Scripts/python -m runner.budat arquivo-bu.dat
"""
from __future__ import annotations

import json
import sys

CARGO = {1: "PRESIDENTE", 3: "GOVERNADOR", 5: "SENADOR", 6: "DEPUTADO FEDERAL",
         7: "DEPUTADO ESTADUAL", 8: "DEPUTADO DISTRITAL"}
# tipoVoto do BU: 1 nominal, 2 branco, 3 nulo, 4 legenda
NOMINAL, BRANCO, NULO, LEGENDA = 1, 2, 3, 4


def _tlv(b: bytes, i: int) -> tuple[int, int, int]:
    """-> (tag, inicio_do_valor, fim_do_valor)"""
    tag = b[i]
    i += 1
    if tag & 0x1F == 0x1F:
        while b[i] & 0x80:
            i += 1
        i += 1
    ln = b[i]
    i += 1
    if ln & 0x80:
        n = ln & 0x7F
        ln = int.from_bytes(b[i:i + n], "big")
        i += n
    return tag, i, i + ln


def _filhos(b: bytes, i: int, fim: int) -> list[tuple[int, int, int]]:
    out = []
    while i < fim:
        tag, a, z = _tlv(b, i)
        out.append((tag, a, z))
        i = z
    return out


def _int(b: bytes, a: int, z: int) -> int:
    return int.from_bytes(b[a:z], "big")


def _e_seq_mzls(b, t, a, z) -> bool:
    """SEQ { SEQ{INT,INT}, INT, INT }  (municipio/zona, local, secao)"""
    if t != 0x30:
        return False
    k = _filhos(b, a, z)
    return (len(k) == 3 and k[0][0] == 0x30 and k[1][0] == 0x02 and k[2][0] == 0x02
            and [x[0] for x in _filhos(b, k[0][1], k[0][2])] == [0x02, 0x02])


def parse(b: bytes) -> dict:
    # envelope: SEQ { ..., conteudo OCTET STRING }
    tag, a, z = _tlv(b, 0)
    if tag != 0x30:
        raise ValueError("envelope nao e SEQUENCE")
    conteudo = None
    for t, i, j in _filhos(b, a, z):
        if t == 0x04:
            conteudo = b[i:j]
    if not conteudo:
        raise ValueError("envelope sem conteudo")

    tag, a, z = _tlv(conteudo, 0)
    if tag != 0x30:
        raise ValueError("conteudo nao e SEQUENCE")
    topo = _filhos(conteudo, a, z)

    out = {"cargos": {}}
    seqs = [(t, i, j) for t, i, j in topo if t == 0x30]
    for t, i, j in seqs:
        if _e_seq_mzls(conteudo, t, i, j):
            k = _filhos(conteudo, i, j)
            mz = _filhos(conteudo, k[0][1], k[0][2])
            out["mun"] = _int(conteudo, mz[0][1], mz[0][2])
            out["zona"] = _int(conteudo, mz[1][1], mz[1][2])
            out["local"] = _int(conteudo, k[1][1], k[1][2])
            out["secao"] = _int(conteudo, k[2][1], k[2][2])
            break
    ints = [(i, j) for t, i, j in topo if t == 0x02]
    if ints:
        out["aptos"] = _int(conteudo, *ints[0])

    resultados = max(seqs, key=lambda s: s[2] - s[1])      # o maior SEQ do topo

    comp_sec = 0
    for t, i, j in _filhos(conteudo, resultados[1], resultados[2]):      # por eleicao
        if t != 0x30:
            continue
        kids = _filhos(conteudo, i, j)
        rvs = next(((a2, z2) for t2, a2, z2 in kids if t2 == 0x30), None)
        if rvs is None:
            continue
        for t3, a3, z3 in _filhos(conteudo, *rvs):                       # bloco por tipo de cargo
            if t3 != 0x30:
                continue
            bk = _filhos(conteudo, a3, z3)
            comp = next((_int(conteudo, a4, z4) for t4, a4, z4 in bk if t4 == 0x02), 0)
            comp_sec = max(comp_sec, comp)
            totais = next(((a4, z4) for t4, a4, z4 in bk if t4 == 0x30), None)
            if totais is None:
                continue
            for t5, a5, z5 in _filhos(conteudo, *totais):                # por cargo
                if t5 != 0x30:
                    continue
                ck = _filhos(conteudo, a5, z5)
                cod = next((_int(conteudo, a6, z6) for t6, a6, z6 in ck if t6 == 0x81), None)
                votaveis = next(((a6, z6) for t6, a6, z6 in ck if t6 == 0x30), None)
                nome = CARGO.get(cod, f"CARGO {cod}")
                cg = out["cargos"].setdefault(nome, {"cands": {}, "legenda": {}, "nominais": 0,
                                                     "legenda_total": 0, "brancos": 0, "nulos": 0,
                                                     "total": 0, "comparecimento": comp})
                if votaveis is None:
                    continue
                for t7, a7, z7 in _filhos(conteudo, *votaveis):          # por votavel
                    if t7 != 0x30:
                        continue
                    vk = _filhos(conteudo, a7, z7)
                    tipo = qtd = partido = codigo = None
                    for t8, a8, z8 in vk:
                        if t8 == 0x81:
                            tipo = _int(conteudo, a8, z8)
                        elif t8 == 0x82:
                            qtd = _int(conteudo, a8, z8)
                        elif t8 == 0xA3:
                            pk = _filhos(conteudo, a8, z8)
                            partido = _int(conteudo, pk[0][1], pk[0][2])
                            if len(pk) > 1:
                                codigo = _int(conteudo, pk[1][1], pk[1][2])
                    if tipo is None or qtd is None:
                        raise ValueError("votavel sem tipo/quantidade")
                    cg["total"] += qtd
                    if tipo == NOMINAL:
                        cg["cands"][str(codigo if codigo is not None else partido)] = \
                            cg["cands"].get(str(codigo if codigo is not None else partido), 0) + qtd
                        cg["nominais"] += qtd
                    elif tipo == BRANCO:
                        cg["brancos"] += qtd
                    elif tipo == NULO:
                        cg["nulos"] += qtd
                    elif tipo == LEGENDA:
                        p = str(partido if partido is not None else codigo)
                        cg["legenda"][p] = cg["legenda"].get(p, 0) + qtd
                        cg["legenda_total"] += qtd
                    else:
                        raise ValueError(f"tipoVoto desconhecido: {tipo}")

    out["comparecimento"] = comp_sec
    if "aptos" in out:
        out["faltosos"] = max(out["aptos"] - comp_sec, 0)
    if not out["cargos"]:
        raise ValueError("sem cargos no boletim")
    for nome, cg in out["cargos"].items():
        if sum(cg["cands"].values()) != cg["nominais"]:
            raise ValueError(f"{nome}: soma dos candidatos != nominais")
        if cg["nominais"] + cg["legenda_total"] + cg["brancos"] + cg["nulos"] != cg["total"]:
            raise ValueError(f"{nome}: nominais+legenda+brancos+nulos != total")
        # 2026: senador tem 2 votos por eleitor, entao total e comp ou 2*comp
        comp = cg.pop("comparecimento")
        if cg["total"] not in (comp, 2 * comp):
            raise ValueError(f"{nome}: total {cg['total']} incompativel com comparecimento {comp}")
    return out


def main() -> int:
    b = open(sys.argv[1], "rb").read()
    print(json.dumps(parse(b), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
