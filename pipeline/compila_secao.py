"""Compila o voto por secao de um ano inteiro numa passada so, em streaming (pyarrow).

Mesmas saidas e mesmos esquemas de baseline_presidente / baseline_estadual /
baseline_partido / baseline_candidato, sem o dict Python que esses acumulam (os 27
milhoes de chaves de deputado estadual custam ~8 GB de RAM). Cada zip e lido uma vez,
em lotes; cada lote e filtrado e projetado para as saidas de todos os cargos, e cada UF
vira um row group gravado na hora.

Saidas (BASELINE):
  presidente_secao_{ano}.parquet              largo (t1_esq.. t2_nulo, eixo_dir_t2)
  presidente_secao_{ano}_t{T}.parquet         longo, um por turno presente
  governador_secao_{ano}_t{T}.parquet         idem
  senador_secao_{ano}_t1.parquet
  dep{federal,estadual}_candidato_secao_{ano}_t1.parquet
  dep{federal,estadual}_partido_secao_{ano}_t1.parquet
  detalhe_secao_{ano}.parquet                 aptos/comparecimento/brancos/nulos por cargo e turno

Uso:  .venv/Scripts/python -m pipeline.compila_secao 2026
"""
from __future__ import annotations

import sys
import time
import zipfile

import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.csv as pacsv
import pyarrow.parquet as pq

from sintetico.caminhos import BASELINE, BRUTO_TSE, UFS
from .baseline_presidente import BRANCO, EIXO, NULO

S = pa.large_string()
I = pa.int64()
CHAVE = [("uf", S), ("cd_municipio", S), ("zona", I), ("secao", I)]
ESQ_LONGO = pa.schema(CHAVE + [("nr_votavel", S), ("nm_votavel", S), ("votos", I),
                               ("candidato", pa.bool_())])
ESQ_CAND = pa.schema(CHAVE + [("nr", S), ("votos", I)])
ESQ_PART = pa.schema(CHAVE + [("partido", S), ("votos", I)])

COLUNAS = {"SG_UF": S, "CD_MUNICIPIO": S, "NR_ZONA": I, "NR_SECAO": I, "DS_CARGO": S,
           "NR_TURNO": S, "DT_ELEICAO": S, "NR_VOTAVEL": S, "NM_VOTAVEL": S, "QT_VOTOS": I}
DETALHE = {"SG_UF": S, "CD_MUNICIPIO": S, "NR_ZONA": I, "NR_SECAO": I, "DS_CARGO": S,
           "NR_TURNO": S, "DT_ELEICAO": S, "QT_APTOS": I, "QT_COMPARECIMENTO": I,
           "QT_ABSTENCOES": I, "QT_VOTOS_NOMINAIS": I, "QT_VOTOS_BRANCOS": I,
           "QT_VOTOS_NULOS": I, "QT_VOTOS_LEGENDA": I, "NR_LOCAL_VOTACAO": I}
DEP = {"federal": ("DEPUTADO FEDERAL",), "estadual": ("DEPUTADO ESTADUAL", "DEPUTADO DISTRITAL")}


class Saidas:
    """Um ParquetWriter por arquivo, aberto sob demanda."""

    def __init__(self):
        self.w: dict[str, pq.ParquetWriter] = {}
        self.n: dict[str, int] = {}

    def grava(self, nome: str, tab: pa.Table, esquema: pa.Schema) -> None:
        if tab.num_rows == 0:
            return
        if nome not in self.w:
            self.w[nome] = pq.ParquetWriter(BASELINE / nome, esquema, compression="zstd")
            self.n[nome] = 0
        self.w[nome].write_table(tab.select(esquema.names).cast(esquema))
        self.n[nome] += tab.num_rows

    def fecha(self) -> None:
        for nome, w in self.w.items():
            w.close()
            print(f"  {nome:48s} {self.n[nome]:>12,} linhas  "
                  f"{(BASELINE / nome).stat().st_size / 1e6:7.1f} MB", flush=True)


def lotes(zpath, colunas: dict, nome_csv=None):
    z = zipfile.ZipFile(zpath)
    # _BRASIL.csv repete os arquivos por UF (+ _BR, que e o presidente): leria tudo em dobro
    nomes = [n for n in z.namelist() if n.lower().endswith(".csv") and not n.endswith("_BRASIL.csv")]
    for nome in ([nome_csv] if nome_csv else nomes):
        with z.open(nome) as fh:
            rd = pacsv.open_csv(
                fh,
                read_options=pacsv.ReadOptions(encoding="latin1", block_size=8 << 20),
                parse_options=pacsv.ParseOptions(delimiter=";"),
                convert_options=pacsv.ConvertOptions(column_types=colunas,
                                                     include_columns=list(colunas)))
            for b in rd:
                yield pa.Table.from_batches([b])


NOMES = {"SG_UF": "uf", "CD_MUNICIPIO": "cd_municipio", "NR_ZONA": "zona", "NR_SECAO": "secao",
         "NR_VOTAVEL": "nr_votavel", "NM_VOTAVEL": "nm_votavel", "QT_VOTOS": "votos"}


def renomeia(t: pa.Table) -> pa.Table:
    return t.rename_columns([NOMES.get(c, c) for c in t.column_names])


def soma(t: pa.Table, chave: list[str], fatia: int = 1_000_000):
    """Agrega votos por chave (urna agregada e linhas repetidas viram uma). Em fatias de
    municipios: o group_by de SP inteiro (~7 milhoes de linhas) nao cabe na RAM livre."""
    muns = pc.unique(t["cd_municipio"]).to_numpy()
    partes = max(1, -(-t.num_rows // fatia))
    for grupo in [muns[i::partes] for i in range(partes)]:
        sub = t.filter(pc.is_in(t["cd_municipio"], pa.array(grupo)))
        g = sub.group_by(chave, use_threads=False).aggregate([("votos", "sum")])
        yield g.rename_columns([c if c != "votos_sum" else "votos" for c in g.column_names])


def longo(t: pa.Table) -> pa.Table:
    cand = pc.invert(pc.is_in(t["nr_votavel"], pa.array(["95", "96"])))
    return t.append_column("candidato", cand)


def compacta(t: pa.Table, extra: list[str] = ()) -> pa.Table:
    """Chave como int32 (16 bytes/linha em vez de ~60 com texto): SP tem ~7 milhoes de
    linhas de deputado estadual e a maquina da noite nao tem folga de RAM."""
    cols = {"cd_municipio": pc.cast(t["cd_municipio"], pa.int32()),
            "zona": pc.cast(t["zona"], pa.int32()), "secao": pc.cast(t["secao"], pa.int32()),
            "nr": pc.cast(t["nr_votavel"], pa.int32()), "votos": pc.cast(t["votos"], pa.int32())}
    for c in extra:
        cols[c] = t[c]
    return pa.table(cols)


def expande(t: pa.Table, uf: str, nr_como: str) -> pa.Table:
    """Volta ao esquema dos baselines de 2022 (texto em uf/cd_municipio/nr)."""
    n = t.num_rows
    cols = {"uf": t["uf"] if "uf" in t.column_names else pa.array([uf] * n, S),
            "cd_municipio": pc.cast(t["cd_municipio"], S),
            "zona": pc.cast(t["zona"], I), "secao": pc.cast(t["secao"], I),
            nr_como: pc.cast(t["nr"], S)}
    for c in t.column_names:
        if c not in ("uf", "cd_municipio", "zona", "secao", "nr", "votos"):
            cols[c] = t[c]
    cols["votos"] = pc.cast(t["votos"], I)
    return pa.table(cols)


def compila_uf(ano: int, uf: str, out: Saidas) -> dict:
    acc: dict[str, list[pa.Table]] = {}
    for t in lotes(BRUTO_TSE / str(ano) / f"votacao_secao_{ano}_{uf}.zip", COLUNAS):
        t = t.filter(pc.ends_with(t["DT_ELEICAO"], str(ano)))   # suplementares (ver baseline_estadual)
        t = renomeia(t)
        for turno in pc.unique(t["NR_TURNO"]).to_pylist():
            tt = t.filter(pc.equal(t["NR_TURNO"], turno))
            ct = pc.utf8_upper(tt["DS_CARGO"])
            for nome in ("GOVERNADOR", "SENADOR", "PRESIDENTE"):
                sel = tt.filter(pc.equal(ct, nome))
                if sel.num_rows:
                    acc.setdefault(f"{nome.lower()}_secao_{ano}_t{turno}.parquet", []).append(
                        compacta(sel, ["uf", "nm_votavel"]))
            if turno != "1":
                continue
            for qual, nomes in DEP.items():
                sel = tt.filter(pc.is_in(ct, pa.array(list(nomes))))
                if not sel.num_rows:
                    continue
                nr = sel["nr_votavel"]
                acc.setdefault(f"dep{qual}_candidato_secao_{ano}_t1.parquet", []).append(
                    compacta(sel.filter(pc.greater_equal(pc.utf8_length(nr), 3))))
                part = compacta(sel.filter(pc.invert(pc.is_in(nr, pa.array([BRANCO, NULO])))))
                # partido = 2 primeiros digitos do numero (nominal de 4-5 digitos ou legenda)
                dig = pc.subtract(pc.utf8_length(pc.cast(part["nr"], S)), 2)
                div = pc.power(pa.scalar(10, pa.int32()), pc.cast(dig, pa.int32()))
                acc.setdefault(f"dep{qual}_partido_secao_{ano}_t1.parquet", []).append(
                    part.set_column(3, "nr", pc.divide(part["nr"], div)))
    resumo = {}
    for nome in list(acc):
        tab = pa.concat_tables(acc.pop(nome))
        resumo[nome] = tab.num_rows
        if "secao_" in nome and nome.startswith("dep"):
            cand = "candidato_secao" in nome
            for g in soma(tab, ["cd_municipio", "zona", "secao", "nr"]):
                out.grava(nome, expande(g, uf, "nr" if cand else "partido"), ESQ_CAND if cand else ESQ_PART)
        else:
            out.grava(nome, longo(expande(tab, uf, "nr_votavel")), ESQ_LONGO)
        del tab
    return resumo


def presidente_largo(ano: int) -> None:
    """Formato largo do presidente_secao_{ano}.parquet a partir dos longos ja gravados."""
    codes = EIXO[ano]
    partes = []
    for turno, cols in (("1", ["t1_esq", "t1_dir", "t1_outros", "t1_branco", "t1_nulo"]),
                        ("2", ["t2_esq", "t2_dir", "t2_outros", "t2_branco", "t2_nulo"])):
        arq = BASELINE / f"presidente_secao_{ano}_t{turno}.parquet"
        if not arq.exists():
            continue
        d = pd.read_parquet(arq, columns=["uf", "cd_municipio", "zona", "secao", "nr_votavel", "votos"])
        cat = pd.Series(cols[2], index=d.index)
        cat[d["nr_votavel"] == codes["esq"]] = cols[0]
        cat[d["nr_votavel"] == codes["dir"]] = cols[1]
        cat[d["nr_votavel"] == BRANCO] = cols[3]
        cat[d["nr_votavel"] == NULO] = cols[4]
        d["cat"] = cat
        w = d.pivot_table(index=["uf", "cd_municipio", "zona", "secao"], columns="cat",
                          values="votos", aggfunc="sum", fill_value=0)
        partes.append(w)
    df = pd.concat(partes, axis=1).fillna(0)
    for c in ["t1_esq", "t1_dir", "t1_outros", "t1_branco", "t1_nulo",
              "t2_esq", "t2_dir", "t2_branco", "t2_nulo"]:
        if c not in df:
            df[c] = 0
    df = df.drop(columns=[c for c in df.columns if c == "t2_outros"]).astype("int64").reset_index()
    dois = df["t2_esq"] + df["t2_dir"]
    df["eixo_dir_t2"] = (df["t2_dir"] / dois.where(dois > 0)).astype("float32")
    df["validos_t1"] = df["t1_esq"] + df["t1_dir"] + df["t1_outros"]
    df["comparecimento_t1"] = df["validos_t1"] + df["t1_branco"] + df["t1_nulo"]
    cols = ["uf", "cd_municipio", "zona", "secao", "t1_esq", "t1_dir", "t1_outros", "t1_branco",
            "t1_nulo", "t2_esq", "t2_dir", "t2_branco", "t2_nulo", "eixo_dir_t2", "validos_t1",
            "comparecimento_t1"]
    destino = BASELINE / f"presidente_secao_{ano}.parquet"
    df[cols].to_parquet(destino, index=False, compression="zstd")
    v = df["validos_t1"].sum()
    print(f"  presidente_secao_{ano}.parquet: {len(df):,} secoes; 1o turno "
          f"esq {100 * df['t1_esq'].sum() / v:.2f}%  dir {100 * df['t1_dir'].sum() / v:.2f}% dos validos",
          flush=True)


def detalhe(ano: int) -> None:
    arq = BRUTO_TSE / str(ano) / f"detalhe_votacao_secao_{ano}.zip"
    if not arq.exists():
        return
    partes = []
    for t in lotes(arq, DETALHE):
        partes.append(t.filter(pc.ends_with(t["DT_ELEICAO"], str(ano))))
    t = pa.concat_tables(partes).drop_columns(["DT_ELEICAO"])
    t = t.rename_columns(["uf", "cd_municipio", "zona", "secao", "cargo", "turno", "aptos",
                          "comparecimento", "abstencoes", "nominais", "brancos", "nulos",
                          "legenda", "nr_local"])
    t = t.set_column(4, "cargo", pc.utf8_upper(t["cargo"]))
    destino = BASELINE / f"detalhe_secao_{ano}.parquet"
    pq.write_table(t, destino, compression="zstd")
    print(f"  detalhe_secao_{ano}.parquet: {t.num_rows:,} linhas", flush=True)


def candidatos(ano: int) -> None:
    """dep{federal,estadual}_candidatos_{ano}.parquet (esquema do de 2022) a partir da
    consulta_cand pos-totalizacao (consulta_cand_{ano}_pos.zip: DS_SIT_TOT_TURNO preenchido)."""
    arq = BRUTO_TSE / str(ano) / f"consulta_cand_{ano}_pos.zip"
    z = zipfile.ZipFile(arq)
    nome = next(n for n in z.namelist() if n.endswith("_BRASIL.csv"))
    with z.open(nome) as fh:
        d = pd.read_csv(fh, sep=";", encoding="latin-1", dtype=str,
                        usecols=["SG_UF", "DS_CARGO", "NR_TURNO", "NR_CANDIDATO", "NM_URNA_CANDIDATO",
                                 "SG_PARTIDO", "NR_FEDERACAO", "SG_FEDERACAO", "DS_SIT_TOT_TURNO",
                                 "DS_SITUACAO_CANDIDATURA"])
    d = d[d["NR_TURNO"] == "1"]
    for qual, nomes in DEP.items():
        s = d[d["DS_CARGO"].str.upper().isin(nomes)]
        out = pd.DataFrame({"uf": s["SG_UF"], "nr": s["NR_CANDIDATO"], "nome": s["NM_URNA_CANDIDATO"],
                            "partido": s["SG_PARTIDO"], "nr_fed": s["NR_FEDERACAO"], "sg_fed": s["SG_FEDERACAO"],
                            "sit": s["DS_SIT_TOT_TURNO"], "sit_cand": s["DS_SITUACAO_CANDIDATURA"]})
        out = out.drop_duplicates(["uf", "nr"])
        destino = BASELINE / f"dep{qual}_candidatos_{ano}.parquet"
        out.to_parquet(destino, index=False)
        eleitos = out["sit"].str.startswith("ELEITO", na=False).sum()
        print(f"  {destino.name}: {len(out):,} candidatos, {eleitos} eleitos", flush=True)


def main() -> int:
    ano = int(sys.argv[1]) if len(sys.argv) > 1 else 2026
    if "--candidatos" in sys.argv:
        candidatos(ano)
        return 0
    if "--detalhe" in sys.argv:
        detalhe(ano)
        return 0
    t0 = time.time()
    out = Saidas()
    try:
        for i, uf in enumerate(["BR"] + UFS, 1):
            r = compila_uf(ano, uf, out)
            print(f"[{i:>2}/28] {uf}  " + "  ".join(f"{k.split('_secao')[0]}={v:,}" for k, v in r.items())
                  + f"  ({time.time() - t0:.0f}s)", flush=True)
    finally:
        out.fecha()
    presidente_largo(ano)
    detalhe(ano)
    print(f"concluido em {time.time() - t0:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
