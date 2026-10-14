"""Gene models: GTF / genePred / BED readers, the union of exons per gene, the JSON layout, the RefSeq cache."""
from __future__ import annotations

import gzip
import json

import pytest

from spatialscape import genes as G

SIZES = {"chr1": 1_000_000, "chr2": 1_000_000, "chrM": 16_569}

GTF = """##description: test
1\tHAVANA\tgene\t1001\t5000\t.\t+\t.\tgene_id "G1"; gene_name "ALPHA";
1\tHAVANA\texon\t1001\t1200\t.\t+\t.\tgene_id "G1"; transcript_id "T1"; gene_name "ALPHA";
1\tHAVANA\texon\t2001\t2500\t.\t+\t.\tgene_id "G1"; transcript_id "T1"; gene_name "ALPHA";
1\tHAVANA\texon\t2301\t2800\t.\t+\t.\tgene_id "G1"; transcript_id "T2"; gene_name "ALPHA";
1\tHAVANA\texon\t4001\t5000\t.\t+\t.\tgene_id "G1"; transcript_id "T2"; gene_name "ALPHA";
MT\tHAVANA\texon\t577\t647\t.\t-\t.\tgene_id "ENSG0001"; transcript_id "T3";
KI270728.1\tHAVANA\texon\t10\t20\t.\t+\t.\tgene_id "G9"; gene_name "SCAFFOLD";
"""


def _genepred(tmp_path):
    p = tmp_path / "refGene.txt.gz"
    with gzip.open(p, "wt") as fh:
        fh.write("0\tNM_1\tchr1\t+\t10\t100\t10\t100\t1\t10,\t100,\t0\tEPS\tcmpl\tcmpl\t0,\n")
    return p


def test_gtf_union_of_exons_and_chrom_names(tmp_path):
    p = tmp_path / "genes.gtf.gz"
    with gzip.open(p, "wt") as fh:
        fh.write(GTF)
    models = G.read_gene_models(p, SIZES)
    assert set(models) == {"chr1", "chrM"}  # Ensembl names mapped onto chrom.sizes; the scaffold dropped
    (alpha,) = models["chr1"]
    assert alpha.name == "ALPHA" and alpha.strand == 1 and (alpha.start, alpha.end) == (1000, 5000)
    assert alpha.exon_starts == [1000, 2000, 4000] and alpha.exon_ends == [1200, 2800, 5000]  # overlapping exons merged
    (mt,) = models["chrM"]
    assert mt.name == "ENSG0001" and mt.strand == -1 and (mt.start, mt.end) == (576, 647)  # gene_id when there is no name


def test_genepred_table_with_bin_column(tmp_path):
    p = tmp_path / "refGene.txt"
    p.write_text(
        "585\tNM_1\tchr2\t-\t100\t900\t150\t850\t2\t100,500,\t300,900,\t0\tBETA\tcmpl\tcmpl\t0,0,\n"
        "585\tNM_2\tchr2\t-\t100\t950\t150\t850\t1\t100,\t950,\t0\tBETA\tcmpl\tcmpl\t0,\n"
    )
    models = G.read_gene_models(p, SIZES)
    (beta,) = models["chr2"]
    assert beta.name == "BETA" and beta.strand == -1 and beta.exon_starts == [100] and beta.exon_ends == [950]


def test_bed12_and_plain_bed(tmp_path):
    bed12 = tmp_path / "a.bed"
    bed12.write_text("chr1\t100\t1000\tGAMMA\t0\t+\t100\t1000\t0\t2\t100,200,\t0,700,\n")
    (g,) = G.read_gene_models(bed12, SIZES)["chr1"]
    assert g.exon_starts == [100, 800] and g.exon_ends == [200, 1000] and g.strand == 1
    bed4 = tmp_path / "b.bed"
    bed4.write_text("chr1\t5000\t6000\tDELTA\nchr1\t7000\t7500\n")
    d, anon = G.read_gene_models(bed4, SIZES)["chr1"]
    assert (d.name, d.strand, d.exon_starts, d.exon_ends) == ("DELTA", 0, [5000], [6000])
    assert anon.name == "chr1:7001-7500"


def test_gff3_is_refused(tmp_path):
    p = tmp_path / "x.gff3"
    p.write_text("chr1\t.\texon\t1\t2\t.\t+\t.\tID=e1\n")
    with pytest.raises(ValueError, match="GFF3"):
        G.read_gene_models(p, SIZES)


def test_same_name_far_apart_stays_separate():
    """GENCODE names every U6 copy "U6": overlapping transcripts merge, distant copies are their own models."""
    models = G.collapse([("chr1", "U6", 1, "t1", 100, 200), ("chr1", "U6", 1, "t2", 150, 260), ("chr1", "U6", -1, "t3", 5_000_000, 5_000_100)])
    assert [(g.start, g.end, g.strand) for g in models["chr1"]] == [(100, 260, 1), (5_000_000, 5_000_100, -1)]


def test_write_gene_models_layout(tmp_path):
    models = G.collapse([("chr1", "B", 1, "b", 500, 600), ("chr1", "A", -1, "a", 10, 20), ("chr1", "A", -1, "a", 30, 40), ("chr2", "C", 0, "c", 1, 2)])
    n = G.write_gene_models(models, tmp_path / "genes", source="test.gtf", order=["chr2", "chr1", "chrX"])
    assert n == 3
    index = json.loads((tmp_path / "genes" / "index.json").read_text())
    assert index == {"source": "test.gtf", "chroms": {"chr2": ["C"], "chr1": ["A", "B"]}}  # chrom.sizes order, genes by start
    rows = json.loads((tmp_path / "genes" / "chr1.json").read_text())
    assert rows == [["A", -1, 10, 40, [10, 30], [20, 40]], ["B", 1, 500, 600, [500], [600]]]


def test_refseq_table_is_downloaded_once(tmp_path, monkeypatch):
    calls = []

    def fake_download(url, dest):
        calls.append(url)
        dest.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(dest, "wt") as fh:
            fh.write("0\tNM_1\tchr1\t+\t10\t100\t10\t100\t1\t10,\t100,\t0\tEPS\tcmpl\tcmpl\t0,\n")

    monkeypatch.setattr(G, "_download", fake_download)
    logs = []
    p1 = G.refseq_table("hg38", log=logs.append, cache=tmp_path)
    p2 = G.refseq_table("hg38", log=logs.append, cache=tmp_path)
    assert p1 == p2 == tmp_path / "genomes" / "hg38" / "refGene.txt.gz"
    assert calls == [G.REFSEQ_URL.format(genome="hg38")] and any("downloading" in line for line in logs)
    with pytest.raises(ValueError, match="no RefSeq gene table"):
        G.refseq_table("custom", log=logs.append, cache=tmp_path)


def test_gene_models_for_keywords(tmp_path, monkeypatch):
    logs = []
    assert G.gene_models_for("none", "hg38", SIZES, log=logs.append) is None
    assert G.gene_models_for(None, "hg38", SIZES, log=logs.append) is None
    assert G.gene_models_for("refseq", "custom", SIZES, log=logs.append) is None and "no RefSeq" in logs[-1]
    monkeypatch.setattr(G, "refseq_table", lambda genome, log, cache=None: _genepred(tmp_path))
    models, source = G.gene_models_for("refseq", "hg38", SIZES, log=logs.append)
    assert source == "RefSeq (hg38)" and [g.name for g in models["chr1"]] == ["EPS"]
    models, source = G.gene_models_for(str(_genepred(tmp_path)), "hg38", SIZES, log=logs.append)
    assert source == "refGene.txt.gz" and models["chr1"][0].exon_ends == [100]
