# Como a projeção funciona — e o que nela é discutível

Tudo abaixo foi validado no **replay exato da noite de 2022** (a ordem real em que as 472 mil
seções entraram, reconstruída dos dados abertos do TSE e conferida contra o histórico oficial
de totalização, que ela reproduz com diferença ≤ 0,02 ponto). Nenhuma pesquisa entra em nenhum
ponto: só voto contado e geografia histórica.

## A ideia em uma frase

Uma seção apurada não vale pelo voto dela — vale pelo que revela sobre as seções parecidas que
ainda não chegaram. "Parecida" é medida pela posição da seção no **eixo esquerda–direita do 2º
turno presidencial anterior** (para 2026: o 2º turno de 2022), que é a âncora geográfica mais
estável e limpa que existe.

## As camadas

**1. Majoritárias (presidente, governador, senador).** Regressão ponderada nas seções já
apuradas: `share_c(i) ≈ a_c + b_c · z_i`, onde `z_i` é o eixo da seção. Os coeficientes nascem
do zero a cada eleição (o candidato de 2026 não estava na cédula de 2022) e são aplicados às
seções que faltam, ponderadas pelo eleitorado apto — conhecido de antemão — vezes o
comparecimento observado. Por cima, o **efeito de município**: o desvio local de cada candidato
em relação ao que o eixo previa, aprendido ao vivo e encolhido. Sem ele o modelo era cego para
o caso Manaus (metade do eleitorado do AM, apura tarde, vota diferente do interior).

**2. Proporcionais (deputado federal e estadual).** O mesmo motor projeta o total de cada
**agremiação** (federação = partido único); a ordem nominal interna vem do próprio apurado.
Cada projeção passa pelo **quociente eleitoral e pelas sobras** (regras pós-EC 111: piso de
10% do QE para vaga de quociente, 80%/20% para sobra) — o alocador reproduz 498/513 eleitos
reais de 2022, com as divergências explicadas por cassação e anulação judiciais posteriores.

**3. Probabilidade (o needle).** Nunca uma fórmula chutada: **simulação**. Majoritárias:
a distribuição de erro da margem vem das outras corridas do mesmo cargo no mesmo estágio
(leave-one-out — a corrida nunca vê o próprio erro). Proporcionais: Monte Carlo com duas
incertezas calibradas por estágio — o erro do total da agremiação (`k_p`) e a deriva da ordem
nominal (`ESS_p`) — em que cada sorteio é uma eleição completa passando pelo quociente.
P(eleito) = frequência. Calibração medida aos 10% apurados:

| | Brier | leitura |
|---|---|---|
| Governador | 0,0066 | quase perfeito; raramente visita a zona de dúvida |
| Senado | 0,0739 | **na faixa ~50% o modelo fica do lado errado** (diz 50, acontece 7) — abaixo de ~80%, o card deve dizer "disputado", não um número |
| Dep. federal | 0,0133 | subconfiante no miolo (diz 60–70, acontece 72) — direção segura |
| Dep. estadual | 0,0248 | idem, um pouco mais disperso |

## Parâmetros que valem discussão

| parâmetro | valor | o que faz | por que é discutível |
|---|---|---|---|
| `K_B` | 0,05 | encolhe a inclinação `b_c` para 0 com pouca apuração | forte demais atrasa a leitura de candidato com geografia atípica; fraco demais deixa um reduto definir a curva |
| `K_MUN` | 300 votos | encolhe o efeito de município | calibrado em grade (300/1.000/3.000); 300 venceu no pior caso em todos os marcos, e a baixa sensibilidade é bom sinal — mas piora a mediana antes de 3% apurado (troca consciente: cauda > mediana) |
| `tau` | 200 votos | encolhe o share candidato-dentro-do-partido por município (usado no "ritmo"/regiões) | pouco testado; só afeta display, não o needle |
| `k_p`, `ESS_p` | medidos por estágio | variâncias do Monte Carlo dos proporcionais | medidos **no próprio 2022** (in-sample); o teste honesto é re-medir em 2018 — `ESS≈25` aos 10% diz que a ordem nominal ainda deriva muito, e é o parâmetro que domina o P(eleito) marginal |
| prior `b_c = 0` | — | candidato sem inclinação até prova em contrário | alternativa: prior herdado do bloco do candidato (esquerda→b>0); ganharia nos primeiros minutos, ao custo de errar candidatos contra-alinhados |
| limiar de exibição | P≥1% | corta a cauda de candidatos no front | cosmético |

## Como associar um deputado a uma área

Hoje: **pelo próprio apurado** — o share do candidato dentro do partido, município a município,
encolhido por `tau` para o share estadual dele. É o que alimenta o "ritmo" e os "redutos" do
front. Alternativas estudadas:

1. **Histórico do próprio deputado** (quem disputou em 2022 tem geografia nominal conhecida) —
   a melhor opção para os ~60% que são reeleição; planejada para o modelo de 2026, com o
   apurado assumindo o controle conforme chega.
2. **Eleição municipal anterior (vereador 2020→2022, análogo de 2024→2026)** — **testada e
   reprovada**: covariável por candidato (share do partido dele no vereador 2020 por seção,
   com fallback municipal) não melhora nada — erro mediano do líder de governador vai de
   1,30 para 1,65 aos 3% apurados, e presidente fica idêntico. O voto municipal é
   idiossincrático demais (candidato local) para transferir; o eixo presidencial + o efeito de
   município ao vivo já contêm o sinal aproveitável. Vale o registro: resultado negativo
   medido em 27 corridas, não suposição.

## O contrato de dados da noite (`dados/live.json`)

A página `index.html` lê `dados/live.json?t=<agora>` (anti-cache) e cai no JSON embutido se o
fetch falhar. Em 2026, o runner local recalcula este arquivo a cada ciclo e dá push; o site
não muda. Campos:

```
modo           "replay-2022" | "aguardando" | "ao-vivo"
congelado_em   texto do instante retratado
presidente     {lider, margem, tela_crua, p_lider, pct_secoes, sigma, sh_esq, sh_dir, p_esq50, p_dir50}
               (margem e tela_crua do ponto de vista de quem lidera a projeção)
governos[27]   {uf, pct_secoes, lider, share, segundo, share2, p_lider}
senado[27]     idem (2026: p_lider vira P(entre os 2) — 2 vagas)
camara         {nacional: [{agr, p10, med, p90}], por_uf: {UF: [{agr, med}]}}
assembleias    idem
```

O detalhe candidato a candidato (quociente, mínimos, P(eleito), target, ritmo, redutos) vive em
`regua-quociente.html`, gerado pelo mesmo motor.

## 2026: uma âncora só para alvo, needle e desvio

A partir de 2026 o presidente deixa de ser projetado pelo eixo puro de 2022 e passa a partir de
uma **âncora por urna** (`sintetico/ancora_2026.py`): o resultado real do 2º turno de 2022
naquela seção, **andado pela demografia** até 2026. A caminhada vem do modelo sintético
(coeficientes de 2022 aplicados à demografia de 2026: envelhecimento, escolaridade, religião),
somada em log-odds:

```
a_ed   = log(Lula/Bolsonaro 2022 na seção) + [logit q_2026 − logit q_2022]     (q = Lula/(Lula+dir) do sintético)
a_part = log(votos nos dois / resto)       + [logit (1−nenhum)_2026 − logit (1−nenhum)_2022]
a_out  = terceiros do 1º turno de 2022 na seção;  a_bn = brancos+nulos do 1º turno de 2022
```

Urna nova (10% das urnas de 2026 não existiam em 2022) herda a média do **local de votação**,
depois do município, depois da UF. Somada no país, a âncora dá **Lula 49,19% dos válidos dois a
dois** (o sintético puro dava 48,98%; 2022 real foi 50,90%).

**Alvo** (`sintetico/alvo_2026.py`): o mesmo deslocamento δ em log-odds do confronto em toda
urna, escolhido por bisseção para o campo fechar **50% dos VÁLIDOS + 1 voto** no país — com os
terceiros no denominador, ancorados no 1º turno de 2022 (8,5% dos válidos; não são modelados,
só ocupam espaço). Log-odds porque ganhar 3 pontos num reduto de 80% não é o mesmo esforço que
3 pontos onde se está em 50%. Resultado: pela demografia Lula parte de 45,2% dos válidos e
Flávio Bolsonaro de 46,3% — **faltam +4,8 e +3,7 pontos** (δ = +0,237 e +0,185). Cada UF,
município, zona, local e seção tem o seu alvo, e o mapa tem **duas lentes globais** — Lula ×
50%+1 e Flávio × 50%+1 — que pintam tudo pela distância do candidato ao próprio alvo (ao vivo,
pela projeção; antes, pela demografia). De onde vêm os votos que faltam (adversário ou
terceiros) não entra na conta. Uma versão anterior fechava o alvo sobre o confronto dois-a-dois
(equivalente a ignorar terceiros) e dava ±0,8 ponto; era otimista com os dois — corrigida em
27/09.

**Needle hierárquico** (`pipeline/needle_hier.py`): cada urna apurada revela um desvio em relação
à âncora; o desvio das urnas que faltam é previsto por

```
desvio(j) = X_j·β  (25 covariáveis do sintético + o nível da própria âncora, ridge)
          + u[UF] + m[município] + l[local]      (efeitos aninhados, encolhidos para 0)
```

em quatro dimensões (esquerda×direita, comparecimento, terceiros, brancos+nulos). Sem voto
nenhum, desvio = 0 e o needle = âncora. Duas fontes entram no mesmo estimador: boletins de urna
raspados (desvio exato da urna) e totais municipais do feed (o que o município apurou além das
urnas raspadas vira uma pseudo-observação). Qual urna o feed já contou é estimado pela ordem de
chegada da eleição anterior.

Calibração no replay de 2022 (âncora = 2018 + deriva demográfica 2018→2022 com coeficientes de
2018, sem olhar a resposta). Erro da margem nacional, pontos:

| apurado (1º turno) | tela | needle v1* | hier. só feed | hier. 60% dos boletins | hier. todos |
|---|---|---|---|---|---|
| 1% (17h38) | −12,3 | +3,5 | −0,4 | −0,2 | +0,5 |
| 3% (18h04) | −12,2 | +0,7 | −0,6 | −0,1 | +0,3 |
| 10% (18h32) | −10,7 | −0,1 | −0,7 | −0,3 | +0,1 |
| 30% (19h06) | −9,3 | +0,2 | −0,8 | −0,5 | +0,1 |

\*o v1 supõe todas as seções visíveis na hora — compara com a última coluna. No 2º turno de 2022
o hierárquico fica em ±0,25 ponto a partir de 2% apurado. Parâmetros (grade em
`sintetico/calib_hier_grade_t1.csv`): `L=0,005`, `K0=5.000`, `K_UF=200.000`, `K_MUN=300`,
`K_LOC=1.500`, `lam_ordem=1`. A incerteza (`baseline/calib_presidente.json`) é o RMS do erro nas
duas noites × três coberturas de boletim, com folga de 25%, envoltória conservadora e piso de
0,5 ponto; P(liquidar no 1º turno) usa metade desse σ na fatia dos válidos.

**Governador e Senado** seguem o modelo estadual acima, agora alimentado por boletins e com o eixo
de cada seção tirado da mesma âncora. σ por estágio: RMS do erro nas 27 corridas de 2022
(`baseline/calib_estadual_hier.json`; aos 10%: 3,8 pontos governador, 4,0 Senado). Senado 2026
(2 vagas) ganha P(entre os 2) pela margem 2º−3º.

**Deputados ao vivo** (`pipeline/dep_live.py`): o mesmo Monte Carlo do needle validado —
share da agremiação projetado pelo modelo estadual sobre o eixo da âncora (erro `k_p` por
estágio), ordem nominal via Dirichlet (`ESS_p`), e cada sorteio atravessa o quociente com os
pisos individuais (10% do QE; 80%/20% nas sobras) — agora alimentado pelos boletins raspados
e pelas federações de 2026 (PT/PCdoB/PV, PSDB/CID, PSOL/REDE, PRD/SOLID, UNIÃO/PP). No replay
aos 9,8% apurados com 60% dos boletins: PL 87 (real 99 — o "vento" tardio do PL é justamente
o que os estágios seguintes corrigem), FE Brasil 81 (real 80), soma 514/513. Sobre a bancada
entra a **cláusula de desempenho de 2026** (EC 97/2017: 2,5% dos válidos com 1,5% em ≥9 UFs,
ou 13 eleitos em ≥9 UFs) como flag informativa por agremiação, federação avaliada como bloco —
ela restringe fundo e propaganda, não tira cadeira. A calibração estadual só existe aos 10%
(k 14% menor que a federal, ESS igual): a curva federal entra escalada por essa razão, e fora
de 3–20% os valores são grampeados — conservador de propósito.

## O contrato de dados do mapa (`dados/`)

Base estática (`web/gera_estatico.py`, ~200 MB, carregada por nível): `meta.json`, `br.json`,
`uf/{UF}.json`, `mun/{cd}.json` (zonas e locais com lat/lon), `sec/{cd}/{zona}.json` (urnas),
`dep/{UF}.json` e `dep/{UF}/{cd}.json` (todos os candidatos a deputado por município e zona),
`geo/*.json` (TopoJSON do IBGE com código TSE). Cada unidade leva, por cargo e turno, um vetor
de votos alinhado à lista de candidatos + [branco, nulo, abstenção], e a projeção 2026
`[Lula, direita, outros, brancos+nulos, abstenção]` com o alvo.

Ao vivo (`runner/ciclo.py`): `live/br.json` (needle, alvo, UFs, governos e Senado com o vetor
projetado), `live/uf/{UF}.json` (por município), e — só no modo local/túnel, fora do git —
`live/mun/{cd}.json` (boletins por urna, local, zona e município, todos os cargos; deputados até a
zona). O mapa aceita `?live=<url>` para ler de um túnel.

## Limites conhecidos

- **Um ciclo de validação.** Tudo aqui é 2022 ancorado em 2018. Os testes seguintes: 2018
  ancorado em 2014, e o 2º turno de 2022.
- O Senado de 2026 tem **2 vagas** por estado (formato de 2018) — a calibração de Senado
  precisa ser re-medida nesse formato; por ora P(entre os 2) usa o σ de 2022 (1 vaga).
- A incerteza do presidente vem de **duas noites** (1º e 2º turno de 2022): o piso de 0,5 ponto
  existe porque duas noites não são uma distribuição.
- Só com o feed municipal (sem boletins) sobra um viés de −0,6 a −1,2 ponto entre 5% e 30%
  apurado no replay: dentro de cada cidade o swing varia com o perfil da seção, e o total do
  município não revela isso. Mesmo sabendo exatamente quais seções o feed contou (teste com
  oráculo), sobram −0,4 a −0,6. Os boletins fecham essa distância.
- O feed do TSE pode mudar de layout em 2026; o coletor descobre códigos em runtime
  (`ele-c.json`) e nada é cravado, mas a sondagem se repete quando a eleição aparecer no índice.
