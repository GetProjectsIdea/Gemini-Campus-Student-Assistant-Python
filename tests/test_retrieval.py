from campus_assistant.backends import MockBackend
from campus_assistant.retrieval import BM25Index, KnowledgeBase, cosine
from campus_assistant.textutil import Chunk


def test_bm25_ranks_relevant_chunk_first():
    idx = BM25Index([Chunk("a.md", "Library timings", "Open 8 AM to 10 PM."),
                     Chunk("b.md", "Mess", "Lunch is at 1 PM."),
                     Chunk("c.md", "Fees", "Pay before the 15th.")])
    hits = idx.search("library timings")
    assert hits[0].chunk.source == "a.md"
    assert hits[0].score > 0


def test_bm25_no_match_returns_empty():
    idx = BM25Index([Chunk("a.md", "x", "alpha beta")])
    assert idx.search("gamma") == []


def test_bm25_empty_query_and_empty_index():
    assert BM25Index([]).search("anything") == []
    assert BM25Index([Chunk("a", "", "text")]).search("the of") == []


def test_bm25_respects_k():
    idx = BM25Index([Chunk(f"{i}.md", "fee", "fee fee") for i in range(10)])
    assert len(idx.search("fee", k=3)) == 3


def test_kb_loads_sample_faq(sample_dir):
    kb = KnowledgeBase(sample_dir / "faq")
    assert "library.md" in kb.sources
    assert len(kb.chunks) > 15


def test_kb_ignores_other_files(tmp_path):
    (tmp_path / "a.md").write_text("## Gate\nCloses at ten.")
    (tmp_path / "b.pdf").write_bytes(b"%PDF")
    (tmp_path / "c.txt").write_text("Canteen opens at 8.")
    kb = KnowledgeBase(tmp_path)
    assert kb.sources == ["a.md", "c.txt"]


def test_kb_from_text():
    kb = KnowledgeBase.from_text("## FCFS\nFirst come first served.\n\n## SJF\nShortest job first.", "os.md")
    assert kb.search("shortest job")[0].chunk.heading == "SJF"


def test_hit_as_dict(sample_dir):
    hit = KnowledgeBase(sample_dir / "faq").search("revaluation fee")[0]
    d = hit.as_dict()
    assert d["source"] == "exams.md" and d["heading"] == "Revaluation" and "500" in d["text"]


def test_cosine():
    assert cosine([1, 0], [1, 0]) == 1.0
    assert cosine([1, 0], [0, 1]) == 0.0
    assert cosine([0, 0], [1, 1]) == 0.0


def test_hybrid_search_with_embeddings_and_cache(sample_dir, tmp_path):
    cache = tmp_path / "emb.json"
    emb = MockBackend()
    kb = KnowledgeBase(sample_dir / "faq", embedder=emb, cache_path=cache)
    hits = kb.search("library fine for late books", k=3)
    assert hits[0].chunk.source == "library.md"
    assert cache.exists()

    class Boom:
        def embed(self, texts):
            if len(texts) > 1:
                raise AssertionError("chunks should come from the cache")
            return emb.embed(texts)
    kb2 = KnowledgeBase(sample_dir / "faq", embedder=Boom(), cache_path=cache)
    assert kb2.search("library fine", k=1)[0].chunk.source == "library.md"


def test_cache_key_is_stable_across_processes(sample_dir):
    kb = KnowledgeBase(sample_dir / "faq")
    c = kb.chunks[0]
    assert kb._key(c) == KnowledgeBase(sample_dir / "faq")._key(c)
    assert len(kb._key(c).split(":")[1]) == 12
