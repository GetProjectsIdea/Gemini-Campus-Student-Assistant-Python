import pytest

from campus_assistant.textutil import chunk_markdown, clip, redact, sentences, stem, tokenize


def test_tokenize_drops_stopwords_and_lowercases():
    assert tokenize("What are the Library Timings?") == ["library", "timing"]


def test_tokenize_keeps_stopwords_when_asked():
    assert "the" in tokenize("the library", keep_stopwords=True)


def test_tokenize_handles_hindi_devanagari():
    toks = tokenize("पुस्तकालय का समय")
    assert "पुस्तकालय" in toks and "समय" in toks


def test_tokenize_hinglish_stopwords_removed():
    assert tokenize("hostel gate kab band hota hai") == ["hostel", "gate", "band"]


@pytest.mark.parametrize("word,expected", [("timings", "timing"), ("books", "book"), ("libraries", "library"),
                                           ("classes", "class"), ("transitively", "transitive"),
                                           ("dependency", "dependent"), ("os", "os"), ("bus", "bus")])
def test_stem(word, expected):
    assert stem(word) == expected


def test_stem_leaves_non_ascii_alone():
    assert stem("कक्षाएं") == "कक्षाएं"


def test_sentences_split():
    assert sentences("First one. Second one! Third? done") == ["First one.", "Second one!", "Third? done"]


def test_sentences_hindi_danda():
    assert len(sentences("यह पहला वाक्य है। यह दूसरा है।")) == 2


def test_sentences_empty():
    assert sentences("   ") == []


def test_chunk_markdown_uses_headings():
    md = "# Title\n\n## Gate\nCloses at 10.\n\n## Mess\nLunch at 1."
    chunks = chunk_markdown(md, "hostel.md")
    assert [c.heading for c in chunks] == ["Gate", "Mess"]
    assert chunks[0].ref == "hostel.md › Gate"
    assert [c.idx for c in chunks] == [0, 1]


def test_chunk_markdown_text_before_heading_gets_title():
    chunks = chunk_markdown("# Library\nIntro text here.", "lib.md")
    assert chunks[0].heading == "Library"


def test_chunk_markdown_splits_long_sections():
    md = "## Big\n" + "\n\n".join("word " * 60 for _ in range(5))
    chunks = chunk_markdown(md, "x.md", max_words=100)
    assert len(chunks) >= 3
    assert all(len(c.text.split()) <= 120 for c in chunks)


def test_chunk_markdown_plain_text_without_headings():
    chunks = chunk_markdown("Just some notes.\nMore notes.", "n.txt")
    assert len(chunks) == 1 and chunks[0].ref == "n.txt"


@pytest.mark.parametrize("text,label", [
    ("mail me at riya.sharma@college.edu.in", "EMAIL"),
    ("my aadhaar is 1234 5678 9012", "AADHAAR"),
    ("call 9876543210 now", "PHONE"),
    ("call +91 98765 43210 now", "PHONE"),
    ("PAN ABCDE1234F", "PAN"),
])
def test_redact(text, label):
    out, counts = redact(text)
    assert f"[{label}]" in out
    assert counts[label] == 1


def test_redact_leaves_course_codes_and_times():
    text = "CS301 at 09:00 in LT-2, fee Rs 500, helpline 1800-180-5522"
    out, counts = redact(text)
    assert "CS301" in out and "09:00" in out and "Rs 500" in out
    assert counts == {}


def test_clip_keeps_head_and_tail():
    s = "A" * 1000 + "Z" * 1000
    out = clip(s, 500)
    assert out.startswith("A") and out.endswith("Z") and "trimmed" in out and len(out) < 600


def test_clip_short_text_unchanged():
    assert clip("short", 100) == "short"


def test_tokenize_unstemmed():
    assert tokenize("Library timings", stemmed=False) == ["library", "timings"]
