import json

import pytest

import score


def make_candidate(id_, title, abstract="dummy abstract", journal="Dummy Journal"):
    return {
        "id": id_, "title": title, "abstract": abstract, "journal": journal,
        "authors": ["A. Author"], "date": "2026-08-01",
        "url": f"https://example.org/{id_}", "oa_pdf": "",
    }


@pytest.fixture(autouse=True)
def isolate_io(tmp_path, monkeypatch):
    """score.py の実ファイル I/O をテスト用の一時ディレクトリへ差し替える。"""
    monkeypatch.setattr(score, "CAND_PATH", tmp_path / "candidates.json")
    monkeypatch.setattr(score, "OUT_PATH", tmp_path / "scored.json")
    monkeypatch.setattr(score, "HISTORY_DIR", tmp_path / "history")
    return tmp_path


@pytest.fixture(autouse=True)
def dummy_keywords(monkeypatch):
    """config/keywords.yml の実内容に依存しない、テスト専用の固定キーワードセットに差し替える。"""
    monkeypatch.setattr(score, "KEYWORDS", {
        "seam": ["teleconnection"],
        "tropical": ["MJO", "ENSO"],
        "midlatitude": ["storm track"],
        "regional": ["Baiu"],
        "method": ["ERA5"],
    })
    monkeypatch.setattr(score, "THEME_ORDER",
                         ["seam", "tropical", "midlatitude", "regional", "method"])


class TestMatchKeyword:
    def test_matches_theme_and_keyword(self):
        c = make_candidate("W1", "MJO impacts on East Asian rainfall")
        assert score.match_keyword(c) == ("tropical", "MJO")

    def test_case_insensitive(self):
        c = make_candidate("W1", "the mjo teleconnection to midlatitudes")
        theme, kw = score.match_keyword(c)
        assert theme == "seam"  # seam は THEME_ORDER の先頭なので mjo より優先される
        assert kw == "teleconnection"

    def test_title_only_ignores_abstract(self):
        c = make_candidate("W1", "A study of boundary layer turbulence",
                            abstract="This abstract mentions MJO and ENSO extensively")
        assert score.match_keyword(c) is None

    def test_multi_match_uses_theme_order_priority(self):
        c = make_candidate("W1", "Teleconnection and MJO variability")
        theme, _ = score.match_keyword(c)
        assert theme == "seam"

    def test_no_match_returns_none(self):
        c = make_candidate("W1", "Nothing relevant to any keyword here")
        assert score.match_keyword(c) is None


class TestCallClaude:
    def test_parses_json_response(self, monkeypatch):
        class FakeResp:
            ok = True
            status_code = 200

            def raise_for_status(self):
                pass

            def json(self):
                return {"content": [{"type": "text",
                                      "text": '[{"id": "W1", "score": 7, "reason": "r", "theme": "seam"}]'}]}

        monkeypatch.setattr(score.requests, "post", lambda *a, **k: FakeResp())
        result = score.call_claude([{"id": "W1", "title": "t", "journal": "j", "abstract": "a"}])
        assert result == [{"id": "W1", "score": 7, "reason": "r", "theme": "seam"}]

    def test_strips_code_fences(self, monkeypatch):
        class FakeResp:
            ok = True
            status_code = 200

            def raise_for_status(self):
                pass

            def json(self):
                return {"content": [{"type": "text",
                                      "text": '```json\n[{"id": "W1", "score": 5, "reason": "r", '
                                              '"theme": "other"}]\n```'}]}

        monkeypatch.setattr(score.requests, "post", lambda *a, **k: FakeResp())
        result = score.call_claude([{"id": "W1", "title": "t", "journal": "j", "abstract": "a"}])
        assert result[0]["id"] == "W1"

    def test_invalid_json_returns_empty_list(self, monkeypatch):
        class FakeResp:
            ok = True
            status_code = 200

            def raise_for_status(self):
                pass

            def json(self):
                return {"content": [{"type": "text", "text": "not json at all"}]}

        monkeypatch.setattr(score.requests, "post", lambda *a, **k: FakeResp())
        result = score.call_claude([{"id": "W1", "title": "t", "journal": "j", "abstract": "a"}])
        assert result == []


class TestCallClaudeReasons:
    def test_returns_id_to_reason_map(self, monkeypatch):
        class FakeResp:
            def raise_for_status(self):
                pass

            def json(self):
                return {"content": [{"type": "text", "text": '[{"id": "W1", "reason": "面白い理由"}]'}]}

        monkeypatch.setattr(score.requests, "post", lambda *a, **k: FakeResp())
        result = score.call_claude_reasons([{"id": "W1", "title": "t", "journal": "j", "abstract": "a"}])
        assert result == {"W1": "面白い理由"}

    def test_network_failure_returns_empty_dict(self, monkeypatch):
        def raise_err(*a, **k):
            raise score.requests.RequestException("boom")

        monkeypatch.setattr(score.requests, "post", raise_err)
        result = score.call_claude_reasons([{"id": "W1", "title": "t", "journal": "j", "abstract": "a"}])
        assert result == {}

    def test_malformed_json_returns_empty_dict(self, monkeypatch):
        class FakeResp:
            def raise_for_status(self):
                pass

            def json(self):
                return {"content": [{"type": "text", "text": "not json"}]}

        monkeypatch.setattr(score.requests, "post", lambda *a, **k: FakeResp())
        result = score.call_claude_reasons([{"id": "W1", "title": "t", "journal": "j", "abstract": "a"}])
        assert result == {}


class TestWriteHistoryMarkdown:
    def test_writes_table_with_notified_marks(self, tmp_path):
        candidates = [make_candidate("W1", "Title A"), make_candidate("W2", "Title B")]
        verdicts = {
            "W1": {"score": 8, "reason": "good", "theme": "seam"},
            "W2": {"score": 3, "reason": "meh", "theme": "other"},
        }
        out = tmp_path / "history" / "2026-01-01.md"
        score.write_history_markdown(candidates, verdicts, threshold=6, out_path=out)
        text = out.read_text(encoding="utf-8")
        assert "Title A" in text and "Title B" in text
        w1_line = next(line for line in text.splitlines() if "Title A" in line)
        w2_line = next(line for line in text.splitlines() if "Title B" in line)
        assert "✅" in w1_line
        assert "✅" not in w2_line

    def test_missing_verdict_shown_as_na(self, tmp_path):
        candidates = [make_candidate("W1", "No Verdict Paper")]
        out = tmp_path / "history" / "2026-01-01.md"
        score.write_history_markdown(candidates, {}, threshold=6, out_path=out)
        text = out.read_text(encoding="utf-8")
        assert "N/A" in text

    def test_keyword_matches_go_in_their_own_section(self, tmp_path):
        candidates = [make_candidate("W1", "Teleconnection paper"),
                      make_candidate("W2", "LLM scored paper")]
        verdicts = {
            "W1": {"score": score.KEYWORD_SCORE, "theme": "seam", "method": "keyword",
                   "matched_keyword": "teleconnection", "reason": "おすすめ理由"},
            "W2": {"score": 7, "theme": "method", "method": "llm", "reason": "good"},
        }
        out = tmp_path / "history" / "2026-01-01.md"
        score.write_history_markdown(candidates, verdicts, threshold=6, out_path=out)
        text = out.read_text(encoding="utf-8")

        assert "## キーワード一致で採用（1件）" in text
        assert "## LLM 採点（1件" in text
        keyword_section = text.split("## キーワード一致で採用")[1].split("## LLM 採点")[0]
        assert "Teleconnection paper" in keyword_section
        assert "teleconnection" in keyword_section
        assert "LLM scored paper" not in keyword_section

    def test_no_keyword_matches_omits_keyword_section(self, tmp_path):
        candidates = [make_candidate("W1", "Only LLM scored")]
        verdicts = {"W1": {"score": 7, "theme": "method", "method": "llm", "reason": "good"}}
        out = tmp_path / "history" / "2026-01-01.md"
        score.write_history_markdown(candidates, verdicts, threshold=6, out_path=out)
        text = out.read_text(encoding="utf-8")
        assert "キーワード一致で採用" not in text


class TestMain:
    def test_keyword_match_bypasses_llm_scoring_and_stays_mechanical(self, isolate_io, monkeypatch):
        candidates = [
            make_candidate("W1", "MJO-related teleconnection study"),   # keyword match -> seam
            make_candidate("W2", "Some unrelated paper about clouds"),  # LLM scoring, below threshold
            make_candidate("W3", "Another unrelated paper about fronts"),  # LLM scoring, above threshold
        ]
        (isolate_io / "candidates.json").write_text(json.dumps(candidates), encoding="utf-8")

        call_claude_batches = []
        reasons_batches = []

        def fake_call_claude(batch):
            call_claude_batches.append([c["id"] for c in batch])
            return [
                {"id": "W2", "score": 3, "reason": "not interesting", "theme": "other"},
                {"id": "W3", "score": 8, "reason": "簡易理由", "theme": "other"},
            ]

        def fake_call_claude_reasons(batch):
            reasons_batches.append([c["id"] for c in batch])
            return {c["id"]: f"LLM生成理由:{c['id']}" for c in batch}

        monkeypatch.setattr(score, "call_claude", fake_call_claude)
        monkeypatch.setattr(score, "call_claude_reasons", fake_call_claude_reasons)
        monkeypatch.setitem(score.CONFIG, "batch_size", 25)
        monkeypatch.setitem(score.CONFIG, "min_score", 6)

        score.main()

        assert call_claude_batches == [["W2", "W3"]]  # LLM 採点は非キーワード一致分のみ
        assert reasons_batches == [["W3"]]             # 理由生成は「LLM採点で閾値超え」分のみ

        scored = json.loads((isolate_io / "scored.json").read_text(encoding="utf-8"))
        assert {p["id"] for p in scored} == {"W1", "W3"}   # W2 は閾値未満で不採用

        w1 = next(p for p in scored if p["id"] == "W1")
        assert w1["score"] == score.KEYWORD_SCORE
        assert w1["theme"] == "seam"
        assert w1["method"] == "keyword"
        assert w1["matched_keyword"] == "teleconnection"
        assert w1["reason"] == "キーワード「teleconnection」に一致"  # 常に定型文、LLM は呼ばれない

        w3 = next(p for p in scored if p["id"] == "W3")
        assert w3["method"] == "llm"
        assert w3["reason"] == "LLM生成理由:W3"  # こちらは Sonnet 生成の理由に置き換わる

    def test_reason_generation_failure_falls_back_to_mechanical_text(self, isolate_io, monkeypatch):
        candidates = [make_candidate("W1", "ENSO variability and prediction")]
        (isolate_io / "candidates.json").write_text(json.dumps(candidates), encoding="utf-8")

        monkeypatch.setattr(score, "call_claude", lambda batch: [])
        monkeypatch.setattr(score, "call_claude_reasons", lambda batch: {})  # 生成失敗を模す
        monkeypatch.setitem(score.CONFIG, "batch_size", 25)
        monkeypatch.setitem(score.CONFIG, "min_score", 6)

        score.main()

        scored = json.loads((isolate_io / "scored.json").read_text(encoding="utf-8"))
        assert scored[0]["reason"] == "キーワード「ENSO」に一致"

    def test_keyword_only_run_never_calls_reason_generation(self, isolate_io, monkeypatch):
        """キーワード一致だけの回では、LLM 採点対象がゼロなので Sonnet は一度も呼ばれない。"""
        candidates = [make_candidate("W1", "ENSO variability and prediction")]
        (isolate_io / "candidates.json").write_text(json.dumps(candidates), encoding="utf-8")

        reasons_calls = []
        monkeypatch.setattr(score, "call_claude", lambda batch: [])
        monkeypatch.setattr(score, "call_claude_reasons",
                             lambda batch: reasons_calls.append(batch) or {})
        monkeypatch.setitem(score.CONFIG, "batch_size", 25)
        monkeypatch.setitem(score.CONFIG, "min_score", 6)

        score.main()

        assert reasons_calls == []

    def test_llm_scored_paper_kept_when_above_threshold(self, isolate_io, monkeypatch):
        candidates = [make_candidate("W3", "A paper about clouds and radiation")]
        (isolate_io / "candidates.json").write_text(json.dumps(candidates), encoding="utf-8")

        monkeypatch.setattr(score, "call_claude",
                             lambda batch: [{"id": "W3", "score": 8, "reason": "interesting",
                                              "theme": "method"}])
        monkeypatch.setattr(score, "call_claude_reasons", lambda batch: {})
        monkeypatch.setitem(score.CONFIG, "batch_size", 25)
        monkeypatch.setitem(score.CONFIG, "min_score", 6)

        score.main()

        scored = json.loads((isolate_io / "scored.json").read_text(encoding="utf-8"))
        assert len(scored) == 1 and scored[0]["score"] == 8
        assert scored[0]["method"] == "llm"
        # Sonnet での理由生成が失敗（空dict）した場合、Haiku 採点時の簡易理由にフォールバックする
        assert scored[0]["reason"] == "interesting"

    def test_llm_kept_paper_reason_upgraded_by_stage3(self, isolate_io, monkeypatch):
        candidates = [make_candidate("W3", "A paper about clouds and radiation")]
        (isolate_io / "candidates.json").write_text(json.dumps(candidates), encoding="utf-8")

        monkeypatch.setattr(score, "call_claude",
                             lambda batch: [{"id": "W3", "score": 8, "reason": "簡易理由",
                                              "theme": "method"}])
        monkeypatch.setattr(score, "call_claude_reasons",
                             lambda batch: {"W3": "Sonnetによる詳細なおすすめ理由"})
        monkeypatch.setitem(score.CONFIG, "batch_size", 25)
        monkeypatch.setitem(score.CONFIG, "min_score", 6)

        score.main()

        scored = json.loads((isolate_io / "scored.json").read_text(encoding="utf-8"))
        assert scored[0]["reason"] == "Sonnetによる詳細なおすすめ理由"

    def test_stage2_and_stage3_use_expected_models_and_payload_fields(self, isolate_io, monkeypatch):
        """第2段(採点)は SCORE_MODEL でタイトル+ジャーナルのみ、
        第3段(理由生成)は REASON_MODEL で abstract も含めて送っていることを確認する。"""
        candidates = [make_candidate("W3", "A paper about clouds and radiation",
                                      abstract="full abstract text")]
        (isolate_io / "candidates.json").write_text(json.dumps(candidates), encoding="utf-8")

        score_bodies = []
        reason_bodies = []

        class FakeResp:
            ok = True
            status_code = 200

            def __init__(self, text):
                self._text = text

            def raise_for_status(self):
                pass

            def json(self):
                return {"content": [{"type": "text", "text": self._text}]}

        def fake_post(url, headers=None, json=None, timeout=None):
            if json["system"] == score.SYSTEM:
                score_bodies.append(json)
                return FakeResp('[{"id": "W3", "score": 8, "reason": "r", "theme": "method"}]')
            reason_bodies.append(json)
            return FakeResp('[{"id": "W3", "reason": "詳細理由"}]')

        monkeypatch.setattr(score.requests, "post", fake_post)
        monkeypatch.setitem(score.CONFIG, "batch_size", 25)
        monkeypatch.setitem(score.CONFIG, "min_score", 6)

        score.main()

        assert len(score_bodies) == 1 and score_bodies[0]["model"] == score.SCORE_MODEL
        score_payload = json.loads(score_bodies[0]["messages"][0]["content"].split("\n", 1)[1])
        assert set(score_payload[0].keys()) == {"id", "title", "journal"}

        assert len(reason_bodies) == 1 and reason_bodies[0]["model"] == score.REASON_MODEL
        reason_payload = json.loads(reason_bodies[0]["messages"][0]["content"].split("\n", 1)[1])
        assert reason_payload[0]["abstract"] == "full abstract text"

    def test_no_candidates_writes_empty_scored_json(self, isolate_io, monkeypatch):
        (isolate_io / "candidates.json").write_text("[]", encoding="utf-8")
        score.main()
        assert json.loads((isolate_io / "scored.json").read_text(encoding="utf-8")) == []
