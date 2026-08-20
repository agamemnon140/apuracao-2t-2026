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
presidente     {lider, margem, tela_crua, p_lider, pct_secoes}
governos[27]   {uf, pct_secoes, lider, share, segundo, share2, p_lider}
senado[27]     idem (2026: p_lider vira P(entre os 2) — 2 vagas)
camara         {nacional: [{agr, p10, med, p90}], por_uf: {UF: [{agr, med}]}}
assembleias    idem
```

O detalhe candidato a candidato (quociente, mínimos, P(eleito), target, ritmo, redutos) vive em
`regua-quociente.html`, gerado pelo mesmo motor.

## Limites conhecidos

- **Um ciclo de validação.** Tudo aqui é 2022 ancorado em 2018. Os testes seguintes: 2018
  ancorado em 2014, e o 2º turno de 2022.
- O Senado de 2026 tem **2 vagas** por estado (formato de 2018) — a calibração de Senado
  precisa ser re-medida nesse formato antes de outubro.
- O feed do TSE pode mudar de layout em 2026; o coletor descobre códigos em runtime
  (`ele-c.json`) e nada é cravado, mas a sondagem se repete quando a eleição aparecer no índice.
