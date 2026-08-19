# Apuração 2026 — needle ao vivo

Previsão do resultado nacional **durante a apuração** de 04/10/2026 e 25/10/2026, a partir dos
primeiros parciais publicados pelo TSE. Presidente, 27 governos, Senado, e (P2) deputado federal
e estadual.

Projeto separado do [`eleicoes-2026`](https://github.com/agamemnon140/eleicoes-2026), que projeta
a partir de **pesquisas**. Aqui a pesquisa não entra: **só voto apurado**.

## Por que existe

A ordem de apuração não é aleatória, e ler o número da tela engana. Medido no histórico oficial
de totalização de 2022 (`probe/curva_vies.py`):

| apurado | margem na tela (1º turno) | erro |
|---|---|---|
| 0,5% | Bolsonaro +6,8 | **12,1 pontos** |
| 10% | Bolsonaro +5,5 | 10,7 pontos |
| 50% | Bolsonaro +1,7 | 6,9 pontos |
| 70% | Lula +0,2 | 5,0 pontos |

O resultado final foi **Lula +5,2**. Quem olhasse a tela às 17h25 veria o segundo colocado
liderando por 7 pontos, e a liderança só se inverteu perto de 70% apurado. Corrigir esses 12
pontos de viés de composição — projetando o que falta a partir de como cada lugar votou em 2022 —
é a única razão de o projeto existir.

## Estado

Sondagem concluída e **bancada de teste pronta** (`probe/ACHADOS.md`). Nada de coleta ao vivo ainda.

O replay reconstrói a noite de 2022 na ordem real em que as seções entraram e reproduz a curva
oficial do TSE com diferença de até **0,02 ponto**, com os totais finais batendo voto a voto. O
modelo da noite vai ser medido contra a noite de verdade, não contra uma simulação.

- `tools/fetch.py` — cliente do feed de resultados (`resultados.tse.jus.br`)
- `tools/cdn.py` — cliente dos dados abertos (`cdn.tse.jus.br`, que bloqueia UA de robô)
- `tools/baixa_baseline.py` — baseline por seção de 2018 e 2022, URLs vindas do catálogo CKAN
- `tools/vigia_ele_c.py` — vigia o índice de pleitos: dispara quando a geral de 2026 (ou uma
  suplementar para ensaio) for configurada
- `probe/probe_paths.py` — matriz de caminhos do feed
- `probe/curva_vies.py` — a curva de viés acima, do histórico oficial
- `pipeline/baseline_presidente.py` — baseline presidencial por seção (2018 e 2022)
- `pipeline/carimbos.py` — quando cada seção entrou na apuração, e seu eleitorado
- `pipeline/replay.py` — re-toca a noite de 2022 e confere contra o registro oficial

Dados pesados: `D:\Claude\eleicoes-dados` (fora do repo e fora do Google Drive).

## Rodar

```sh
py probe/curva_vies.py        # baixa e mede o vies de 2022
py tools/vigia_ele_c.py       # checa se 2026 ja foi configurada
py tools/baixa_baseline.py    # 6 GB, retomavel

.venv/Scripts/python -m pipeline.baseline_presidente   # baseline por secao
.venv/Scripts/python -m pipeline.carimbos              # ordem real de chegada
.venv/Scripts/python -m pipeline.replay                # confere contra o oficial
```
