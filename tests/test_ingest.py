from __future__ import annotations

import pytest

from rlm_notebook.ingest import ingest_new, ingest_one, is_url


def test_is_url():
    assert is_url("https://example.com/x")
    assert is_url("http://example.com/x")
    assert not is_url("./notes.txt")
    assert not is_url("paper.pdf")


def test_ingest_one_text_file(tmp_path):
    path = tmp_path / "notes.txt"
    path.write_text("hello world", encoding="utf-8")
    source = ingest_one(str(path), "s1")
    assert source.kind == "text"
    assert source.blocks[0].text == "hello world"


def test_ingest_one_pdf(tmp_path):
    fitz = pytest.importorskip("fitz")
    path = tmp_path / "doc.pdf"
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), "hello pdf")
    doc.save(str(path))
    source = ingest_one(str(path), "s1")
    assert source.kind == "pdf"
    assert source.blocks[0].locator == "page:1"


def test_ingest_new_skips_existing_origins(tmp_path):
    a = tmp_path / "a.txt"
    a.write_text("hello a", encoding="utf-8")
    b = tmp_path / "b.txt"
    b.write_text("hello b", encoding="utf-8")

    sources = ingest_new([str(a), str(b)], start_index=3, skip_origins={str(a)})

    assert [s.origin for s in sources] == [str(b)]
    assert sources[0].id == "s3"


def test_ingest_new_numbers_ids_from_start_index(tmp_path):
    a = tmp_path / "a.txt"
    a.write_text("hello a", encoding="utf-8")
    b = tmp_path / "b.txt"
    b.write_text("hello b", encoding="utf-8")

    sources = ingest_new([str(a), str(b)], start_index=5, skip_origins=set())

    assert [s.id for s in sources] == ["s5", "s6"]


def test_ingest_new_dedupes_a_value_repeated_within_the_same_call(tmp_path):
    """Found by an independent review: the first version only checked the caller's static
    `skip_origins` set, so `--source a.txt --source a.txt` in ONE invocation (not across two) sailed
    through and ingested `a.txt` twice under two different ids."""
    a = tmp_path / "a.txt"
    a.write_text("hello a", encoding="utf-8")

    sources = ingest_new([str(a), str(a), str(a)], start_index=1, skip_origins=set())

    assert len(sources) == 1
    assert sources[0].id == "s1"
