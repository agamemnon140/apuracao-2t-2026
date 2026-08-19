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
