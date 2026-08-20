"""Alocador de cadeiras do proporcional -- regras vigentes em 2022 (pos-EC 111/2021).

Recebe, para um estado: votos validos por agremiacao (partido ou federacao; nominal+legenda)
e votos nominais por candidato. Devolve quem leva cadeira.

  QE  = validos / cadeiras (fracao <= 0,5 despreza; > 0,5 arredonda p/ cima)  [art. 106]
  QP  = floor(validos_da_agremiacao / QE)                                     [art. 107]
        vagas de QP preenchidas na ordem nominal, so por candidato com >= 10% do QE
        [art. 108 par. unico]; vaga de QP sem candidato apto desce para as sobras
  Sobras (medias): media = votos / (vagas_ja_obtidas + 1); leva a maior media a cada rodada.
        So disputa agremiacao com >= 80% do QE E candidato restante com >= 20% do QE
        [art. 109, EC 111/2021]. Se sobrar vaga sem ninguem apto, reabre sem os pisos
        [art. 109 par. 2o].

Federacoes de 2022 (nacionais, por numero de partido):
  FE BRASIL: PT 13, PC do B 65, PV 43 | PSDB/CIDADANIA: 45, 23 | PSOL/REDE: 50, 18
"""
from __future__ import annotations

FEDERACOES = {"13": "FED-PT/PCdoB/PV", "65": "FED-PT/PCdoB/PV", "43": "FED-PT/PCdoB/PV",
              "45": "FED-PSDB/CID", "23": "FED-PSDB/CID",
              "50": "FED-PSOL/REDE", "18": "FED-PSOL/REDE"}

CADEIRAS = {"SP": 70, "MG": 53, "RJ": 46, "BA": 39, "RS": 31, "PR": 30, "PE": 25, "CE": 22,
            "MA": 18, "GO": 17, "PA": 17, "SC": 16, "PB": 12, "ES": 10, "PI": 10, "AL": 9,
            "AC": 8, "AM": 8, "AP": 8, "DF": 8, "MS": 8, "MT": 8, "RN": 8, "RO": 8,
            "RR": 8, "SE": 8, "TO": 8}          # total 513


def agremiacao(nr_partido: str) -> str:
    return FEDERACOES.get(nr_partido, nr_partido)


def qe_oficial(validos: float, cadeiras: int) -> int:
    q = validos / cadeiras
    inteiro = int(q)
    return inteiro + 1 if (q - inteiro) > 0.5 else max(inteiro, 1)


def aloca(votos_agr: dict[str, float], nominais: dict[str, float], uf: str,
          vagas: int | None = None) -> list[str]:
    """Devolve a lista dos nr de candidato eleitos. nominais: {nr_candidato: votos}.

    `vagas` default e a Camara federal; assembleia estadual passa o tamanho dela --
    esquecer isso ja fez o needle estadual eleger 513 deputados num pais com 1.059.
    """
    vagas = vagas if vagas is not None else CADEIRAS[uf]
    validos = sum(votos_agr.values())
    qe = qe_oficial(validos, vagas)

    # candidatos por agremiacao, em ordem nominal
    por_agr: dict[str, list[str]] = {}
    for nr in sorted(nominais, key=lambda n: -nominais[n]):
        por_agr.setdefault(agremiacao(nr[:2]), []).append(nr)

    eleitos: list[str] = []
    obtidas = {a: 0 for a in votos_agr}

    # 1) vagas de quociente partidario
    for a, v in votos_agr.items():
        qp = int(v // qe)
        aptos = [nr for nr in por_agr.get(a, []) if nominais[nr] >= 0.10 * qe]
        leva = aptos[:qp]
        eleitos += leva
        obtidas[a] = len(leva)                  # vaga de QP sem apto desce p/ sobras

    # 2) sobras pelas maiores medias
    def melhor_restante(a: str, piso: float) -> str | None:
        for nr in por_agr.get(a, []):
            if nr not in eleitos and nominais[nr] >= piso:
                return nr
        return None

    while len(eleitos) < vagas:
        com_piso = [(votos_agr[a] / (obtidas[a] + 1), a) for a in votos_agr
                    if votos_agr[a] >= 0.80 * qe and melhor_restante(a, 0.20 * qe)]
        if com_piso:
            _, a = max(com_piso)
            eleitos.append(melhor_restante(a, 0.20 * qe))
        else:                                    # par. 2o: reabre sem pisos
            livres = [(votos_agr[a] / (obtidas[a] + 1), a) for a in votos_agr
                      if melhor_restante(a, 0.0)]
            if not livres:
                break
            _, a = max(livres)
            eleitos.append(melhor_restante(a, 0.0))
        obtidas[a] += 1
    return eleitos
