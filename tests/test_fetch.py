import fetch


class TestReconstructAbstract:
    def test_reconstructs_word_order_from_inverted_index(self):
        inv = {"Hello": [0], "world": [1], "this": [2], "is": [3], "great": [4]}
        assert fetch.reconstruct_abstract(inv) == "Hello world this is great"

    def test_handles_repeated_words(self):
        inv = {"a": [0, 2], "b": [1]}
        assert fetch.reconstruct_abstract(inv) == "a b a"

    def test_none_returns_empty_string(self):
        assert fetch.reconstruct_abstract(None) == ""

    def test_empty_dict_returns_empty_string(self):
        assert fetch.reconstruct_abstract({}) == ""


class TestToRecord:
    def test_extracts_expected_fields(self):
        work = {
            "id": "https://openalex.org/W123456789",
            "doi": "https://doi.org/10.1/xyz",
            "title": "A Great Paper",
            "publication_date": "2026-08-01",
            "authorships": [
                {"author": {"display_name": "Alice"}},
                {"author": {"display_name": "Bob"}},
            ],
            "primary_location": {"source": {"display_name": "Journal of Testing"}},
            "best_oa_location": {"pdf_url": "https://example.org/paper.pdf"},
            "abstract_inverted_index": {"word1": [0], "word2": [1]},
        }
        rec = fetch.to_record(work)
        assert rec["id"] == "W123456789"
        assert rec["title"] == "A Great Paper"
        assert rec["authors"] == ["Alice", "Bob"]
        assert rec["journal"] == "Journal of Testing"
        assert rec["abstract"] == "word1 word2"
        assert rec["url"] == "https://doi.org/10.1/xyz"
        assert rec["oa_pdf"] == "https://example.org/paper.pdf"

    def test_missing_optional_fields_fall_back(self):
        work = {
            "id": "https://openalex.org/W999",
            "publication_date": "2026-01-01",
            "authorships": [],
            "primary_location": None,
            "best_oa_location": None,
            "abstract_inverted_index": None,
        }
        rec = fetch.to_record(work)
        assert rec["title"] == "(no title)"
        assert rec["url"] == "https://openalex.org/W999"  # doi が無い場合は id にフォールバック
        assert rec["oa_pdf"] == ""
        assert rec["abstract"] == ""


class TestLoadSeen:
    def test_missing_file_returns_empty_set(self, tmp_path, monkeypatch):
        monkeypatch.setattr(fetch, "SEEN_PATH", tmp_path / "does-not-exist.json")
        assert fetch.load_seen() == set()

    def test_existing_file_returns_reported_ids(self, tmp_path, monkeypatch):
        import json
        p = tmp_path / "seen.json"
        p.write_text(json.dumps({"reported": ["W1", "W2"]}), encoding="utf-8")
        monkeypatch.setattr(fetch, "SEEN_PATH", p)
        assert fetch.load_seen() == {"W1", "W2"}


class TestFetch:
    def test_fetch_calls_dummied_get_and_returns_results(self, monkeypatch):
        """OpenAlex への実際の HTTP 通信は行わず、requests.get をダミーに差し替える。"""
        captured = {}

        class FakeResp:
            def raise_for_status(self):
                pass

            def json(self):
                return {"results": [{"id": "https://openalex.org/W1", "title": "Dummy"}]}

        def fake_get(url, timeout):
            captured["url"] = url
            return FakeResp()

        monkeypatch.setattr(fetch.requests, "get", fake_get)
        results = fetch.fetch("primary_location.source.issn:1234-5678,from_publication_date:2026-01-01")
        assert results == [{"id": "https://openalex.org/W1", "title": "Dummy"}]
        assert captured["url"].startswith(fetch.OPENALEX)
