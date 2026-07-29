from src.pdf_extractor import extract_context

def test_extract_returns_capped_text():
    ctx = extract_context(["aurionpro transcript.pdf"], max_chars=5000)
    assert isinstance(ctx, str)
    assert 0 < len(ctx) <= 5200
    assert "aurionpro transcript.pdf" in ctx

def test_missing_file_is_skipped():
    ctx = extract_context(["does_not_exist.pdf", "aurionpro transcript.pdf"], max_chars=3000)
    assert "does_not_exist.pdf" not in ctx or "unavailable" in ctx.lower()

def test_empty_list_returns_empty():
    assert extract_context([], max_chars=1000) == ""
