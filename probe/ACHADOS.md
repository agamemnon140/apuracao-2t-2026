# Sondagem 1 — o que o feed do TSE realmente oferece

Executado em 19/08/2026 (`probe/probe_paths.py` e sondas manuais). Tudo verificado contra o
servidor de produção, não contra documentação.

## Vocabulário: pleito != eleição

`comum/config/ele-c.json` distingue **pleito** (`cd`) de **eleição** (`e[].cd`). 2024 é
pleito **452** e eleição **619** (1º turno) — errar isso dá 404 em tudo. Os caminhos de
resultado usam o código de **eleição**; a árvore de boletins usa o de **pleito**.
O mesmo arquivo declara os diretórios por tipo (`arq`) e os cargos de cada eleição (`abr[].cp`),
então **nada precisa ser cravado no código**. A eleição geral de 2026 ainda não aparece ali
(arquivo gerado em 17/06/2026).

## O que responde (ciclo 2024, o corrente — referência de formato para 2026)

| Tipo | Caminho | Conteúdo | Custo |
|---|---|---|---|
| `-e.json` | `{ele}/dados/{uf}/{uf}-c{cargo}-e{ele}-e.json` | **todos os municípios da UF**, votos por candidato, `dt`/`ht` da totalização | **1 requisição por UF** |
| `-u.json` | `{ele}/dados/{uf}/{uf}{mun}-c{cargo}-e{ele}-u.json` | um município, detalhe completo (federações, partidos, candidatos) | 1 por município |
| `-cm.json` | `{ele}/config/mun-e{ele}-cm.json` | malha UF→município→zona com código IBGE | 1 (508 KB) |
| `-cs.json` | `arquivo-urna/{pleito}/config/{uf}/{uf}-p{pleito}-cs.json` | malha município→zona→**seção** | 1 por UF (SP: 2,1 MB) |
| `-aux.json` | `arquivo-urna/{pleito}/dados/{uf}/{mun}/{zona}/{secao}/...-aux.json` | hashes dos arquivos da urna + **`dr`/`hr` da totalização** | 1 por seção |

Não existem: `dados-simplificados` para eleição municipal, `-v.json` por município,
`-ab.json`, `config/{uf}/{uf}-e{ele}-a.json`.

## A descoberta que muda o plano

**`-e.json` entrega a UF inteira em uma requisição.** A camada municipal cai de ~5.570
requisições por ciclo para **27**. O plano aprovado dimensionava L2 como a parte cara da
coleta; ela é, na verdade, mais barata que a camada de UF que já estava prevista.

E cada município vem com `dt`/`ht` — **o horário em que foi totalizado**. A ordem real de
chegada fica gravada no arquivo final.

## Custo por cargo proporcional

Vereador de São Paulo (`-u.json`): **260 KB** contra 8,5 KB do prefeito. Cargo proporcional
carrega todos os candidatos. O `-e.json` de prefeito de SP inteiro: 326 KB. Deputado
federal/estadual em 2026 terá ordem de grandeza parecida por UF — o que mantém L2 barata,
mas encarece o parse.

## 2022 foi podado

No arquivo histórico de 2022 sobrou **só presidente** (`c0001`), só em BR/UF, só como
`dados-simplificados/-r.json` e `dados/-v.json`. Governador, Senado, deputados, e todos os
arquivos municipais: 404. Consequências:

- O ensaio de **formato** usa 2024, não 2022.
- O baseline histórico vem dos **dados abertos** (CSV por seção), como já previsto — o feed
  de resultados nunca foi a fonte do baseline.

## A árvore de boletins de 2022 está viva

`aux.json` de uma seção do Acre responde 200 e traz `"dr": "02/10/2022", "hr": "19:06:03",
"st": "Totalizado"`. Ou seja: **o horário de totalização de cada uma das ~472 mil seções de
2022 é recuperável** — um JSON de ~700 bytes por seção, sem precisar abrir o boletim binário.
Trabalho único, offline: ~472 mil requisições (~350 MB), executável em algumas horas em ritmo
educado. Casado com o resultado por seção dos dados abertos, dá a ordem real de chegada de 2022.

## Dinâmica real medida (eleição municipal 2024, prefeito)

Extraída dos carimbos do `-e.json`:

- **SP** — 553 dos 645 municípios com carimbo do dia da eleição; 92 (14%) foram
  **re-totalizados depois** (até dezembro). O arquivo guarda a *última* totalização, não a
  primeira: esses 14% são contaminação e precisam ser descartados na reconstrução.
- Curva do dia em SP: 17h→4, 18h→110, 19h→300, 20h→66, 21h→54, 22h→19. O grosso fecha
  entre 18h e 19h.
- **AC** — 22 municípios, praticamente todos entre 18h e 20h.

Eleição municipal conta vereador (proporcional, mais lento) — a curva de uma geral tende a ser
mais rápida no majoritário. Serve como piso de realismo para o gerador sintético de ordem.

## Pendências desta sondagem

1. O `-e.json` é publicado **durante** a apuração ou só ao final? O `dg`/`hg` do arquivo é o
   instante da geração (hoje), o que sugere geração sob demanda. Só uma apuração ao vivo
   responde — alvo do ensaio em eleição suplementar.
2. Medir latência e limite de taxa do servidor sob carga (a sondagem foi sequencial e leve).
3. Confirmar o formato do `-e.json` para cargo majoritário estadual (governador) quando 2026 abrir.

---

# Sondagem 2 — dados abertos (19/08/2026)

## O CDN bloqueia robô

`cdn.tse.jus.br` devolve **403** para User-Agent de `curl`, `urllib` ou qualquer coisa com
"bot" — inclusive o UA que o repo `eleicoes-2026` usa em produção (ele funciona lá porque
`requests` manda outros cabeçalhos). O que passa é o prefixo `Mozilla/5.0`. Usamos
`Mozilla/5.0 apuracao-2026/0.1`: passa no filtro sem mentir sobre quem está baixando.
Método `HEAD` também é rejeitado; só `GET`. (`tools/cdn.py`)

## Pergunte ao catálogo, não ao palpite

O portal é CKAN: `dadosabertos.tse.jus.br/api/3/action/package_show?id=resultados-2022`
lista os 34 recursos com URL exata. Foi assim que apareceram dois arquivos que nenhum
palpite de nome acharia — inclusive `detalhe_votacao_secao_2022.zip`, que é **um arquivo
nacional único**, não um por UF (por isso as tentativas por estado davam 404).

## CORREÇÃO: o parcial histórico EXISTE

O plano original afirma que nenhum parcial foi preservado. **Está errado.**

`Historico_Totalizacao_Presidente_BR_1T_2022.zip` (1,6 MB) traz **8.438 linhas, segundo a
segundo**, de 02/10/2022 17:04:47 até o fechamento: seções totalizadas acumuladas, eleitorado,
votos totais e **votos acumulados de cada candidato**. Existe também para o 2º turno.

Limites: só **presidente**, só **nacional**, só **2022** — os catálogos de 2014, 2018 e 2024
não têm nada equivalente. Não diz *quais* seções entraram, então não substitui a reconstrução
por seção; mas é **verdade de campo para a trajetória nacional**, e serve de teste de
consistência: alimentado com a ordem reconstruída, o modelo tem que reproduzir esta curva.

## CORREÇÃO: o viés inicial de 2022 favorecia Bolsonaro, não Lula

O plano dizia que o parcial inicial "superestimou muito" o lado de Lula — a narrativa usual do
Nordeste apurando primeiro. O histórico oficial diz o contrário (`probe/curva_vies.py`):

| apurado | 1º turno: margem na tela | erro | 2º turno: margem na tela | erro |
|---|---|---|---|---|
| 0,5% | −6,8 | **−12,1** | −11,1 | **−12,9** |
| 2% | −7,3 | −12,5 | −13,1 | −14,9 |
| 10% | −5,5 | −10,7 | −4,0 | −5,8 |
| 30% | −4,0 | −9,3 | −2,1 | −3,9 |
| 50% | −1,7 | −6,9 | −0,6 | −2,4 |
| 70% | +0,2 | −5,0 | +0,1 | −1,7 |
| 90% | +2,8 | −2,4 | +1,1 | −0,7 |

(margem = Lula − Bolsonaro, em % dos votos aos concorrentes; final 1T: +5,23; final 2T: +1,80)

Ou seja: quem olhasse a tela no 1º turno via **Bolsonaro liderando por 7 pontos** quando o
resultado era **Lula por 5** — 12 pontos de erro, e a liderança só se inverteu perto de 70%
apurado. É a **magnitude exata do problema que o needle existe para resolver**, e agora é um
alvo mensurável: o modelo tem que derrubar esse erro de 12 pontos para perto de zero já nos
primeiros minutos.

Velocidade: o 1º turno levou até ~20h30 para 90%; o 2º turno chegou a 90% às **19h09**. A
janela útil do modelo é ainda mais curta que o plano supunha.

---

# Sondagem 3 — `-e.json` não é garantido (19/08/2026)

A suplementar de **Roraima (21/06/2026, Governador)** é o ensaio mais próximo de 2026 que
existe: cargo majoritário estadual, com 2º turno configurado. Ela mora no ciclo **`ele2024`**
(o ciclo corrente declarado em `ele-c.json`), mesmo re-rodando uma eleição de 2022 — o ciclo
vem do índice, não do ano da disputa. Cargo é `3` no config e `c0003` no caminho.

O que ela revelou sobre os dois tipos de arquivo de resultado:

| Arquivo | Significado | Municipal 2024 | Suplementar RR (UF) |
|---|---|---|---|
| `{abr}-c{cargo}-e{ele}-**u**.json` | resultado **daquela** abrangência | 404 na UF, OK no município | **OK na UF e no município** |
| `{uf}-c{cargo}-e{ele}-**e**.json` | resultado **por abrangência filha** | **OK** (a UF inteira, município a município) | **404** |

Ou seja: `-u` é "o resultado deste lugar", `-e` é "o resultado quebrado pelos lugares filhos".
E **a disponibilidade do `-e` varia por eleição**.

**Consequência para o plano:** o ganho de "27 requisições em vez de 5.570" é **provisório**.
Se o `-e.json` não for publicado para a geral de 2026, a camada municipal volta a custar uma
requisição por município. A cascata já cobre esse risco (L1 segura o needle sozinha), mas o
coletor precisa **detectar em runtime** qual dos dois caminhos existe e escolher — nunca
assumir o barato. Verificação obrigatória assim que 2026 for configurada.

Ganho colateral: `rr03050-c0003-e006278-u.json` é um arquivo **real de governador**, com
`carg[].fed` (federações), `agr` (agremiações), `par` e `cand` — material para escrever o
parser de cargo majoritário estadual antes de outubro.

## Vigia armado

`tools/vigia_ele_c.py` guarda um retrato do índice em `D:\Claude\eleicoes-dados\ele-c.retrato.json`
e reporta o que aparecer de novo. Hoje: **47 pleitos, nenhum com data futura** — nem a geral de
2026, nem suplementar nova. É o gatilho tanto do ensaio ao vivo quanto da descoberta dos códigos
de 2026. Deve entrar no cron diário.

---

# Sondagem 4 — a ordem real de 2022 estava dentro dos dados abertos (19/08/2026)

`detalhe_votacao_secao_{ano}.zip` (arquivo **BRASIL**, ~245 MB) tem, **por seção e por cargo**:

- `QT_APTOS`, `QT_COMPARECIMENTO`, `QT_ABSTENCOES` — o peso e a abstenção que o modelo usa;
- **`DT_RECEBIMENTO_BU_HOR_TSE`** — quando o boletim daquela urna chegou ao TSE;
- **`DT_PRIM_TOT_PARCIAL_HOR_TSE`** — **quando aquela seção entrou na primeira totalização parcial**;
- `ST_SECAO_INSTALADA`, `ST_SECAO_ANULADA`, modelo da urna, local de votação.

Cobertura no 1º turno de 2022: **460.368 seções com carimbo, zero sem**. Precisão de segundo.
Distribuição da primeira totalização: 17h→11.042, 18h→103.117, 19h→198.524, 20h→124.673,
21h→16.557, 22h→4.831, 23h→1.129 (e ~500 na madrugada).

E vale para **todos os cargos**: Presidente, Governador, Senador, Deputado Federal, Estadual e
Distrital estão no mesmo arquivo. O de 2018 tem as mesmas colunas.

## O que isso apaga do plano

1. **A varredura de ~472 mil `aux.json` deixa de ser necessária.** O plano previa horas de
   crawling para recuperar horário de totalização por seção; o dado já está em um arquivo que
   baixamos em 8 segundos.
2. **É a primeira totalização, não a última.** Resolve a contaminação de re-totalização que
   estragava os carimbos do `-e.json` (onde 14% dos municípios de SP tinham data de dezembro).
3. **O replay deixa de ser sintético.** Juntando `votacao_secao` (o que cada seção votou) com
   `detalhe_votacao_secao` (quando ela entrou), a noite de 2022 pode ser **re-tocada exatamente
   como aconteceu**, segundo a segundo, para todos os cargos — não uma ordem plausível, a ordem real.
   Noites sintéticas continuam úteis, mas como variação em torno de uma noite verdadeira, não como
   substituto dela.
4. **E dá para conferir a reconstrução**: alimentado com essa ordem, o replay tem que reproduzir a
   curva do `Historico_Totalizacao_Presidente_BR_1T_2022`. Se reproduzir, a reconstrução está certa;
   se não, algo na cadeia está errado — e é melhor descobrir agora do que em 4 de outubro.

---

# Marco — replay exato da noite de 2022, validado (19/08/2026)

`pipeline/replay.py` junta o que cada seção votou com o instante em que ela entrou na
apuração, acumula na ordem real e compara com o registro oficial:

```
final reconstruido:  esq 57.259.504  dir 51.072.345  concorrentes 118.229.719
final oficial:       esq 57.259.504  dir 51.072.345  concorrentes 118.229.719

  apurado   margem reconstruida   margem oficial   diferenca
    0.5%           -6.62             -6.83        +0.22
    1.0%           -7.04             -7.04        +0.00
   10.0%           -5.47             -5.48        +0.00
   50.0%           -1.73             -1.71        -0.02
  100.0%           +5.23             +5.23        +0.00
```

A cadeia inteira está provada: chave de seção, carimbo de primeira totalização, agregação.
**A bancada de teste do modelo existe e é a noite real, não uma simulação.**

Detalhes que valem registro:

- 472.075 seções com carimbo; **47 órfãs** (carimbo sem voto de presidente) — seções anuladas
  ou não instaladas. 0,01% do total; tratar explicitamente, não ignorar em silêncio.
- Coerências independentes com o histórico oficial: total de seções (472.075), primeira
  totalização (17:04:47), última (04/10 10:27:34) e eleitorado apto (156.454.011) batem exatamente.
- A diferença de 0,22 em 0,5% vem de granularidade de amostragem entre as duas séries, não de erro.

## Baselines compilados

| Arquivo | Seções | Conferência |
|---|---|---|
| `presidente_secao_2022.parquet` (7,9 MB) | 472.028 | eixo médio **0,4910** = Bolsonaro 49,10% no 2º turno oficial |
| `presidente_secao_2018.parquet` (7,8 MB) | 454.450 | eixo médio **0,5513** = Bolsonaro 55,13% no 2º turno oficial |
| `carimbos_presidente_2022_t1.parquet` | 472.075 | cobertura de carimbo 100% |

Armadilha achada: 2018 grava `DS_CARGO = "Presidente"` e 2022 grava `"PRESIDENTE"`. Comparação
sem caixa, sempre.

---

# Modelo v1 — quanto tempo até acertar 2022 (19/08/2026)

Pergunta: sabendo a correlação por UF/município/seção, **em quanto tempo** o modelo teria
previsto 2022 com precisão? Testado no replay real do 1º turno, com **âncora em 2018** — nunca
em 2022, senão o modelo estaria olhando a resposta. É exatamente a posição de outubro.

O modelo (`pipeline/modelo.py`) é uma regressão ponderada por seção:

```
m_i ≈ alfa_uf + beta · z_i
```

`m_i` = margem da seção na eleição sendo apurada; `z_i` = margem da mesma seção no 2º turno
anterior. `beta` (quanto a geografia antiga ainda explica a nova) e `alfa_uf` (deslocamento do
estado) saem **só das seções já apuradas** e são aplicados nas que faltam, com peso estimado
pelo eleitorado apto — que se conhece de antemão — vezes o comparecimento observado no estado.
Encolhimento em tudo: `beta` puxado para 1 (swing uniforme) e `alfa_uf` puxado para o nacional,
senão o modelo delira com 200 seções apuradas.

Casamento de seção 2018↔2022: **92,8%** casam pela chave UF/município/zona/seção; as demais
(6,5% do voto) herdam a âncora do município, depois da UF.

## Resultado

| marco | hora | apurado | erro do modelo | erro de quem só lê a tela |
|---|---|---|---|---|
| vencedor certo e nunca mais errado | **17:05** | 0,1% | — | a tela só acerta às **20:00** (68%) |
| erro < 2 pontos e nunca mais acima | **17:50** | 1,6% | ±2 | −12,4 |
| erro < 1 ponto e nunca mais acima | **18:00** | 2,5% | +1,00 | −12,1 |
| estabilizado | 18:15 em diante | 4,9% | < ±0,4 | −12,0 |

Margem final real: +5,23. Às 18h00 o modelo dizia **+6,23** enquanto a tela dizia **−6,86**.

**A resposta curta: cerca de uma hora depois do fim da votação, com 2,5% apurado.** E o
vencedor certo desde o primeiro boletim — enquanto a leitura crua do parcial apontou o
perdedor por quase três horas.

## Ressalvas honestas

- **Uma noite só.** Um cargo, um turno, um ciclo. Não é calibração; é uma amostra de tamanho 1.
  Os testes naturais seguintes: 2º turno de 2022 e o pleito de 2018 (ancorado em 2014).
- A magnitude no começo é ruim mesmo acertando o sinal: às 17:05 o modelo diz +25 quando o
  final é +5,2. O needle precisa mostrar incerteza enorme ali — o acerto de vencedor no minuto
  zero é sorte de sinal, não precisão.
- **Tamanho da seção foi testado e descartado.** Existe sinal real (swing de +0,177 nas seções
  grandes contra +0,067 nas pequenas), e ajuda nos primeiros 20 minutos — mas piora de 2%
  apurado em diante (+0,68 contra +0,37 de erro na metade da apuração). Fica implementado e
  desligado; reavaliar quando houver mais noites para testar.

---

# Armadilha — eleição suplementar dentro do conjunto de 2022

O conjunto `2022` dos dados abertos **não contém só a eleição de 2022**. Em Roraima, o cargo de
governador aparece duas vezes:

```
  7.378 linhas  CD_ELEICAO 546   "Eleições Gerais Estaduais 2022"        02/10/2022
  6.906 linhas  CD_ELEICAO 6278  "Eleição Suplementar Governador 2026"   21/06/2026
```

O governo de RR foi anulado e re-disputado em junho de 2026, e a re-disputa foi arquivada no
conjunto do ano original. Sem filtro, o estado entra no modelo com **duas eleições sobrepostas**
— e o sintoma que denunciou foi discreto: a "última totalização" do 1º turno de 2022 aparecia
como 21/06/2026.

Correção aplicada em `baseline_estadual.py`, `carimbos.py` e `baseline_presidente.py`: filtrar
por `DT_ELEICAO` do ano. Vale para 2026 também — quando houver suplementar de 2028 re-rodando
uma disputa de 2026, ela cairá no mesmo lugar.

Códigos de eleição de 2022, para referência: **544** presidente 1º turno, **545** presidente
2º turno, **546** cargos estaduais 1º turno.

---

# Modelo estadual — 27 testes independentes (19/08/2026)

O presidente dá uma noite; as 27 corridas de governador da **mesma noite** dão 27 testes
independentes — e é delas que sai material para calibrar a probabilidade do needle.

Aqui o candidato **não tem histórico próprio** (o governador de 2022 não estava na cédula de
2018). O que sobrevive entre ciclos é a geografia: `share_c(i) ≈ a_c + b_c · z_i`, onde `z_i` é
a posição da seção no eixo do 2º turno presidencial anterior, e `a_c`/`b_c` nascem do zero e são
estimados **só com as seções já apuradas** (`b_c` encolhido para 0 enquanto há pouca apuração,
senão um punhado de seções de um reduto define a curva inteira do candidato).

Das 27 corridas, 15 se decidiram no 1º turno e 12 foram a 2º turno.

| apurado | líder certo | dupla certa | erro do líder (mediana / pior) |
|---|---|---|---|
| 0,5% | 96% | 93% | 3,06 / **13,54** |
| 1% | **100%** | 96% | 1,89 / 8,36 |
| 3% | 100% | 96% | 1,23 / 6,09 |
| 10% | 100% | 93% | 1,83 / 3,78 |
| 30% | 100% | 93% | 0,94 / 2,60 |
| 90% | 100% | 100% | 0,20 / 0,72 |

Três leituras:

1. **O líder é fácil; o segundo lugar é o problema.** A partir de 1% apurado o modelo acerta o
   primeiro colocado nas 27 corridas. Já a **dupla** que vai ao 2º turno só fecha em 100% com
   90% apurado — no Amazonas ela só estabiliza com 50% apurado, no Rio Grande do Sul com 90%.
   Como 12 das 27 corridas foram a 2º turno, é exatamente essa a pergunta que importa nelas.
2. **A mediana engana.** Com 5% apurado a mediana do erro do líder é 1,37 ponto, mas o pior
   estado erra 6,66. Incerteza tem que ser por corrida, nunca uma faixa nacional.
3. **O ganho de precisão é rápido e depois quase para.** De 0,5% para 3% o erro mediano cai pela
   metade; de 3% para 30% cai só de 1,23 para 0,94. O grosso da informação chega cedo.

---

# Efeito de município — a correlação local paga (19/08/2026)

O modelo estadual v1 ignorava município: só a posição da seção no eixo esquerda-direita. Isso
é cego para o caso clássico — Manaus é metade do eleitorado do Amazonas e apura tarde, então o
interior chegava primeiro e nada avisava que a capital votaria diferente do que o eixo previa.

O v2 acrescenta o **desvio local**: o quanto cada candidato foge, naquele município, do que o
eixo previa — medido nas seções já apuradas dali e encolhido por `K_MUN = 300` votos.

| apurado | dupla certa (v1 → v2) | erro mediano do líder | pior erro |
|---|---|---|---|
| 5% | 96% → 96% | 1,37 → **0,97** | 6,66 → **3,54** |
| 10% | 93% → **100%** | 1,83 → **0,92** | 3,78 → **2,95** |
| 20% | 96% → **100%** | 1,41 → **0,51** | 3,32 → **2,76** |
| 50% | 96% → **100%** | 0,61 → **0,29** | 2,06 → **1,52** |

A dupla que vai ao 2º turno passa a fechar em **100% das 27 corridas a partir de 10% apurado**,
e fica. O Amazonas resolve aos 10% (era 50%).

Calibração de `K_MUN` (300, 1.000, 3.000): pouco sensível — 300 ganha no pior caso em todos os
marcos e nunca perde feio. Baixa sensibilidade é bom sinal contra ajuste ao acaso.

**O custo, declarado:** abaixo de 3% apurado a mediana piora (3,06 → 3,35 pontos), porque com
duas seções de um município o desvio local ainda é ruído. Trocamos mediana por cauda de
propósito — num needle o desastre importa mais que o caso típico, e o pior erro melhora
inclusive aos 0,5% (13,54 → 11,94).

## O caso que ainda dói: Rondônia

Margem real entre 1º e 2º: **1,84 ponto** (38,9% x 37,0%). O modelo erra essa margem em **13,5
pontos aos 5%** e 11,4 aos 10% — mostraria uma dianteira folgada numa corrida decidida no fio.
É o retrato do que a incerteza precisa cobrir: acertar o líder não basta se a margem projetada
for confiante e errada.

Ranking dos piores até 5% apurado (erro do líder): ES 11,94 · RR 11,86 · CE 8,49 · AM 7,96 · RJ 5,96.

---

# Vale coletar seção ao vivo? (19/08/2026)

Esta é a decisão mais cara do plano: a camada de seção custa ~472 mil × 2 requisições por ciclo;
a municipal custa 27. Testado nas 27 corridas de governador, simulando um feed que só entrega o
total parcial do município (sem dizer **quais** seções entraram — o melhor palpite para a âncora
do que entrou passa a ser a média da cidade).

O teste é justo: **95-96% do que já apurou está em município pela metade** em qualquer momento
da noite. Municípios não totalizam de uma vez, então o feed municipal perde informação de verdade.

| apurado | erro mediano do líder: município → seção | pior erro | dupla certa |
|---|---|---|---|
| 3% | 1,33 → 1,30 | 5,32 → 4,95 | igual |
| 5% | 1,37 → **0,97** | 4,77 → **3,54** | igual |
| 10% | 1,41 → **0,92** | 4,17 → **2,95** | igual |
| 20% | 0,85 → 0,51 | 3,66 → 2,76 | igual |

**A seção compra ~0,4 ponto na mediana e ~1,2 no pior caso, e não muda nenhuma chamada
qualitativa**: a dupla que vai ao 2º turno é idêntica nos dois feeds, em todos os marcos.

## O mecanismo: viés de ordem dentro da cidade

A seção paga onde a ordem de chegada **dentro** do município é politicamente ordenada:

| cidade | corr(ordem, eixo político) | eixo das 10% primeiras → 10% últimas |
|---|---|---|
| Salvador | +0,226 | +0,321 → +0,403 |
| Fortaleza | +0,221 | +0,062 → +0,172 |
| Manaus | +0,165 | −0,337 → −0,247 |
| São Paulo | +0,115 | −0,219 → −0,117 |
| Rio de Janeiro | −0,084 | sem viés |
| Belo Horizonte / Porto Alegre | ~0,00 | sem viés |

Por isso o Ceará é quem mais ganha com seção (+1,49 ponto aos 5%): Fortaleza apura de um lado
político para o outro. Onde a chegada intramunicipal é politicamente aleatória (Rio, BH, POA),
o total parcial do município já é quase não-enviesado.

## O atalho que NÃO funciona

A hipótese natural — coletar seção só nas cidades grandes — foi testada e falha:

| coleta fina em | seções | % do eleitorado | erro mediano aos 5% |
|---|---|---|---|
| nenhuma cidade | 0 | 0% | 1,37 |
| top 10 | 74.024 | 17,7% | 1,29 |
| top 100 | 172.491 | 39,6% | 1,14 |
| **todas** | **471.010** | 100% | **0,97** |

As 100 maiores cidades custam 172 mil seções (37% do crawl) e capturam **menos de um terço** do
ganho. O valor da seção está na **cauda longa** dos 5.500 municípios pequenos, não nas capitais
— cada um contribui com um viés minúsculo, e são milhares. Não há meio-termo barato: ou paga o
crawl inteiro, ou fica no município.

Não existe arquivo por **zona** no feed (testado: 404 em todas as variantes de caminho), que
seria o meio-termo elegante — São Paulo tem 58 zonas contra 26 mil seções.

---

# Heterogeneidade, ordem, e a tabela que substitui o crawl de seção (19/08/2026)

## Duas grandezas que se confundem

Medidas nos 4.957 municípios com 10+ seções, usando o presidente (uniforme no país):

- **H** — heterogeneidade interna: desvio-padrão do eixo esquerda-direita **entre as seções da
  mesma cidade**. Mediana 0,124; decil superior acima de 0,218.
- **rho** — ordem: correlação entre a ordem de chegada das seções e o eixo delas.

O viés real do primeiro quarto apurado, cruzando as duas (mediana em pontos de margem):

| | ordem aleatória | → | ordem forte |
|---|---|---|---|
| **homogêneo** | 1,97 | | 3,25 |
| **heterogêneo** | 4,18 | | **11,60** |

Correlação com o viés: H **+0,494**, rho **+0,423**, produto **H×rho +0,625**. A leitura:
**H gera ruído** (o primeiro quarto é uma amostra pequena de uma cidade partida) e **rho gera
viés sistemático**. O estrago grande exige as duas.

## A ordem se repete? Só o resumo dela — e parcialmente

Duas perguntas diferentes, que a primeira versão desta nota confundiu.

**As mesmas seções chegam cedo nos dois anos?** Pouco. Correlação de postos (Spearman) entre a
ordem de chegada de 2018 e a de 2022, por município (3.293 cidades com 20+ seções casadas):
mediana **+0,277**, 1º quartil +0,027, 3º quartil +0,495. **15% dos municípios têm ordem
praticamente aleatória** entre os anos e o decil inferior é negativo (abaixo de −0,236) —
cidades que inverteram. Nas 200 maiores, a mediana é +0,289: não é melhor.

**O resumo político da ordem se repete?** Melhor. O desvio do eixo nos primeiros 10% a chegar,
de 2018 para 2022: **+0,330** em todos, **+0,401** ponderado por eleitorado, **+0,503** nas 200
maiores cidades. (Magnitude típica do desvio: 0,060 na mediana, 0,183 no p90.)

O resumo sobrevive melhor que a sequência porque é mais grosso — a estrutura de quais regiões e
zonas transmitem cedo persiste mesmo quando a sequência exata embaralha. Mas **+0,50 significa
um quarto da variância explicada**: a curva de chegada é um **prior fraco**, não uma previsão da
ordem. É por isso que ela recupera quase todo o ganho da seção a partir de 10% apurado, mas só
parte dele aos 5% — ali ela é quase tudo o que existe, e um quarto de variância não basta.

Por município, a persistência do rho (medida mais grosseira) dá +0,284 geral, +0,429 ponderado e
+0,529 nas 200 maiores: Fortaleza 0,301 → 0,231, Belém 0,314 → 0,343, Recife 0,168 → 0,218,
Rio −0,170 → −0,084. Salvador é a exceção que ilustra o risco: 0,028 → 0,233.

## Consequência: a curva de chegada substitui o crawl de seção

Se a ordem se repete, dá para aprender em 2018 a **curva de chegada** de cada município — o
eixo político médio das seções que compõem os primeiros f% a apurar — e usar essa curva para
corrigir o parcial municipal em 2022. O feed informa quanto cada município já apurou, então
basta consultar a curva no ponto certo. Custo ao vivo: **zero** (é uma tabela pré-computada).

Teste out-of-sample (curvas de 2018 → previsão de 2022), 27 corridas de governador:

| apurado | município cru | município **corrigido** | seção (472 mil requisições) |
|---|---|---|---|
| 5% | 1,37 | 1,27 | **0,97** |
| 10% | 1,41 | **0,99** | 0,92 |
| 20% | 0,85 | **0,50** | 0,51 |
| pior aos 5% | 4,77 | **3,57** | 3,54 |
| pior aos 10% | 4,17 | **2,94** | 2,95 |
| pior aos 20% | 3,66 | **2,55** | 2,76 |

**A partir de 10% apurado o município corrigido empata ou supera a seção**, na mediana e no
pior caso. Abaixo de 5% ele recupera o pior caso mas só parte da mediana (1,27 contra 0,97) —
ali poucos municípios têm fração apurada suficiente para a curva dizer algo.

**Isso derruba a justificativa da camada L3.** O crawl de 472 mil × 2 requisições por ciclo — a
peça mais frágil do plano — pode ser trocado por uma tabela calculada offline a partir de 2022,
com perda restrita à primeira meia hora e nenhuma mudança de chamada qualitativa.

Ressalvas, sem maquiagem: é **um ciclo e 27 corridas**; a curva explica só **um quarto da
variância** do desvio que tenta corrigir; e ela deve entrar como **prior encolhido**, cedendo à
observação assim que houver dado — nunca como verdade. Se uma capital mudar a logística de
transmissão em 2026 (Salvador mudou entre 2018 e 2022), a curva erra exatamente ali.

---

# Mira da coleta de seção: heterogeneidade é o melhor critério — e o ganho é pequeno (19/08/2026)

Hipótese do usuário: se a seção vale em algum lugar, é nas cidades heterogêneas. Testada contra
dois critérios rivais (tamanho puro; dano esperado = H × ordem × eleitorado), com orçamentos de
5 mil a 200 mil seções, sempre **em cima do município já corrigido pela curva histórica**.

Erro mediano do líder (27 corridas de governador):

| critério / orçamento | 3% | 5% | 10% | 20% |
|---|---|---|---|---|
| nenhuma seção (só correção histórica) | 1,22 | 1,27 | 0,99 | 0,50 |
| **H, 5 mil seções** | 1,20 | **1,17** | 0,99 | 0,53 |
| H, 200 mil | 1,16 | **0,99** | 0,89 | 0,46 |
| crawl completo (454 mil) | 1,30 | 0,97 | 0,92 | 0,51 |

Três leituras:

1. **A hipótese está certa em termos relativos**: H é o único critério que funciona com orçamento
   pequeno. As cidades heterogêneas são *pequenas* (as do topo têm mediana de 45 seções; H médio
   0,298 contra 0,131 do país), então 5 mil seções compram 100+ cidades. Os critérios por tamanho
   ou dano esperado nem cabem no orçamento — só São Paulo capital tem 26 mil seções, então com
   5-25 mil de orçamento eles selecionam **zero** cidades.
2. **Mas o ganho absoluto é pequeno**: 0,10 ponto aos 5% com 5 mil seções; com 200 mil chega a
   0,28 e **empata com o crawl completo**. A correção histórica de custo zero já tinha capturado
   o grosso do que a seção oferecia.
3. **O crawl completo chega a ser pior que a mira** em alguns marcos (3%: 1,30 contra 1,16) —
   seção de cidade homogênea só adiciona ruído de amostragem ao que o município já dizia.

Conclusão operacional para a noite: **a camada de seção vira "top ~200 mil seções ranqueadas por
H", não 472 mil** — metade do custo, ganho igual ou melhor. E se a camada cair inteira, a perda
real é ~0,1-0,3 ponto de mediana sobre o feed municipal corrigido: a noite não depende dela.

---

# Calibração do needle — primeira medida (19/08/2026)

A probabilidade nasce como o plano exige: da distribuição de **erros reais** do modelo, nunca de
uma logística chutada. Para cada corrida e estágio, os erros de margem vêm das outras 26
corridas do mesmo cargo (leave-one-out) — a corrida nunca vê o próprio erro. 540 previsões
(54 corridas × 10 estágios), aferidas contra quem de fato venceu.

**Brier score: 0,0403** (chute de 50% = 0,25; oráculo = 0).

| needle diz | lider vence | n |
|---|---|---|
| 60-70% | 68,4% | 19 |
| 70-80% | 71,4% | 21 |
| 80-90% | 100% | 20 |
| 90-95% | 96,7% | 91 |
| 95-99% | 98,4% | 374 |
| **50-60%** | **25,0%** | **8** |
| **<50%** | **0%** | **7** |

Por estágio, previsto x observado casa bem (1% apurado: 86,7 x 85,2; 10%: 92,9 x 92,6; de 30%
em diante: ~98 x 100). Controle com um estágio sorteado por corrida (elimina a correlação entre
estágios): 93,6% previsto x 94,4% observado.

## Leitura honesta

1. **No miolo (60-99%), a calibração já nasce boa** — sem nenhum mapa isotônico por cima.
   Emprestar a distribuição de erro das outras corridas do mesmo estágio funciona.
2. **Na cauda de baixo (<60%), o needle está subconfiante ao contrário**: quando diz 50-60%,
   o líder vence só 25% — ou seja, nesses casos o modelo deveria estar dizendo ~30%, não 55%.
   São 15 previsões em 540, quase todas corridas apertadíssimas (RS 0,04 ponto; RO 1,8) nos
   primeiros estágios. Amostra minúscula, mas o sinal é coerente: perto do empate, o erro da
   margem NÃO é simétrico — o líder aparente de um parcial enviesado tende a estar
   sobre-estimado. O mapa isotônico do plano existe exatamente para esta faixa.
3. **O grosso das previsões (465/540) está acima de 90%** porque a maioria das corridas não é
   apertada. O needle vai passar a noite dizendo 95-99% e estará certo — o valor de mercado
   dele está nos poucos cards onde diz 60-80%, e é lá que a calibração precisa de mais amostra
   (2018 ancorado em 2014 é o próximo conjunto de teste natural).

## Calibração aberta por cargo

| | GOV (270 prev.) | SEN (270 prev.) |
|---|---|---|
| Brier | **0,0066** | **0,0739** |
| faixa <60% | n=1 | previsto 49,7 → observado **7,1%** (n=14) |
| faixa 60-70% | 100% (n=5) | 57,1% (n=14) |
| faixa 80%+ | tudo ≥94% observado | calibrado (86→100, 93→94, 98→96) |

**Toda a patologia da faixa baixa é do Senado.** No governador o needle quase não visita a zona
de dúvida (a geografia esquerda-direita explica governador muito bem); no Senado, quando o
needle diz ~50%, o líder projetado vence 7% das vezes — ou seja, naquela zona o modelo está
sistematicamente do lado errado, não apenas incerto. Coerente com o diagnóstico anterior:
senador tem voto pessoal que o eixo não explica, e o líder aparente do parcial enviesado é
sobre-estimado. O conserto (mapa isotônico ou prior asimétrico perto do empate) deve ser
ajustado POR CARGO, e o card de Senado abaixo de ~80% merece rótulo de "disputado" em vez de
número.

A dispersão do erro da margem (a "barra" do needle) por estágio: GOV 6,1 pontos com 1% apurado
→ 3,4 aos 10% → 0,9 aos 50%; SEN 8,8 → 3,8 → 1,0. Em 2022 o Senado teve 1 vaga/estado; 2026
terá 2 (formato de 2018), então essa dispersão precisa ser re-medida em 2018 antes de valer
para 2026.

---

# Deputado federal: quociente, sobras e as 513 cadeiras congeladas (19/08/2026)

## Alocador validado — e as divergências são a lição

`pipeline/quociente.py` implementa as regras vigentes (QE com arredondamento do art. 106, piso
de 10% do QE nas vagas de quociente, sobras com 80%/20% da EC 111, reabertura sem pisos,
federações de 2022 como agremiação única). Aplicado aos totais finais: **498/513 contra a
lista oficial de eleitos** — e os 15 que divergem contam três histórias:

- **RJ e SE**: Gabriel Monteiro e André Moura, eleitos na urna e cassados depois. O oficial
  lista 45/7 eleitos nesses estados; na noite, elegê-los É o resultado certo.
- **AP (4 trocas)**: o caso judicial do Amapá, votações anuladas sub judice.
- **9 estados com 1 troca**: a última cadeira de sobra, sensível a minúcia de divisor.

Por isso a simulação compara contra o próprio alocador nos totais finais — isola erro de
projeção de erro de mecânica.

## A noite congelada — 513 cadeiras por estágio

Share de agremiação projetado pelo modelo estadual (agremiação como "candidato"); ordem
nominal dentro da agremiação vinda do próprio apurado; fração de legenda por agremiação
medida no apurado; quociente + sobras a cada estágio.

| apurado | nomes certos | bancada partidária (cadeiras fora) |
|---|---|---|
| 1% | 377/513 (73,5%) | 57 |
| 3% | 400/513 (78,0%) | 44 |
| 5% | 414/513 (80,7%) | 39 |
| 10% | 427/513 (83,2%) | 28 |
| 20% | 441/513 (86,0%) | 21 |
| 50% | 467/513 (91,0%) | 12 |

Leituras: (a) **bancada converge mais rápido que nome** — aos 10% o share partidário está
quase resolvido (28 cadeiras fora de 513, ~5%), mas o nome da última cadeira de cada partido
depende de ordem nominal fina e do degrau do quociente; (b) mesmo aos 50% ainda há 46 nomes
trocados — a maioria disputas de última cadeira dentro do próprio partido, o tipo de coisa que
o needle do P2 deve expressar como P(eleito) intermediário, nunca como certeza; (c) aos 3%
apurado já se sabe a **forma da Câmara** (bancadas com erro médio de ~1,6 cadeira por estado).

---

# Lote de 19-20/08 (noite): needle completo, tela da noite v1 e o teste das municipais

- **Municipais NÃO turbinam** (`probe/municipais_2020.py`, teste 2020→2022 = análogo de
  2024→2026): covariável por candidato (share do partido no vereador) piora governador
  (1,30→1,65 aos 3%) e não muda presidente. O eixo presidencial + efeito de município ao vivo
  já contêm o sinal. Resultado negativo medido, encerrado.
- **Bancada com IC**: o MC agora grava cadeiras por agremiação por sorteio; a soma no mesmo
  índice de sorteio dá a bancada nacional com p10–p90. Aos 10% de 2022: PL 86–96 (real 99 no
  limite), FE Brasil 79–87 (real 80), PP 44–51 (real 47), PSD 38–44 (real 42).
- **Tela da noite v1** em `docs/index.html` + contrato `docs/dados/live.json` (documentado no
  METODO.md): abas Presidente/Governos/Senado/Câmara/Assembleias, needle nacional, P(líder)
  leave-one-out por corrida, bancadas com IC, banner de modo demonstração. Na noite, o runner
  só recalcula o JSON. **GitHub Pages ativado**: https://agamemnon140.github.io/apuracao-2026/
- **Régua do Quociente** ganhou: estadual, mínimos para eleger por agremiação (QE, 10% QE,
  20% QE de sobra, corte prático), votos contabilizados, ritmo (fração apurada do candidato ÷
  fração do estado, 100 = sem vento) e os 3 redutos de cada candidato com nome de município.
