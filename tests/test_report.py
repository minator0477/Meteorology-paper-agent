import json

import report


def make_paper(id_="W1", score=9, theme="seam", authors=None, oa_pdf=""):
    return {
        "id": id_, "title": "A Great Paper", "url": f"https://example.org/{id_}",
        "journal": "Journal of Testing", "date": "2026-08-01",
        "score": score, "theme": theme, "reason": "面白いから",
        "authors": authors if authors is not None else ["Alice"], "oa_pdf": oa_pdf,
    }


class TestToEmbed:
    def test_builds_embed_with_theme_color(self):
        embed = report.to_embed(make_paper(theme="seam"))
        assert embed["title"] == "A Great Paper"
        assert embed["color"] == report.THEME_COLOR["seam"]
        assert "面白いから" in embed["description"]

    def test_unknown_theme_falls_back_to_other_color(self):
        embed = report.to_embed(make_paper(theme="unknown-theme"))
        assert embed["color"] == report.THEME_COLOR["other"]

    def test_more_than_three_authors_appends_hoka(self):
        embed = report.to_embed(make_paper(authors=["A", "B", "C", "D"]))
        assert "ほか" in embed["description"]

    def test_three_or_fewer_authors_no_hoka(self):
        embed = report.to_embed(make_paper(authors=["A", "B"]))
        assert "ほか" not in embed["description"]

    def test_oa_pdf_link_included_when_present(self):
        embed = report.to_embed(make_paper(oa_pdf="https://example.org/p.pdf"))
        assert "OA PDF" in embed["description"]

    def test_oa_pdf_link_omitted_when_absent(self):
        embed = report.to_embed(make_paper(oa_pdf=""))
        assert "OA PDF" not in embed["description"]

    def test_keyword_method_shows_keyword_badge_not_score(self):
        paper = make_paper()
        paper["method"] = "keyword"
        paper["matched_keyword"] = "MJO"
        embed = report.to_embed(paper)
        assert "🔑" in embed["description"]
        assert "MJO" in embed["description"]
        assert "score" not in embed["description"]

    def test_llm_method_shows_score_badge(self):
        paper = make_paper(score=8)
        paper["method"] = "llm"
        embed = report.to_embed(paper)
        assert "🤖" in embed["description"]
        assert "8/10" in embed["description"]

    def test_missing_method_defaults_to_llm_badge(self):
        embed = report.to_embed(make_paper(score=7))
        assert "🤖" in embed["description"]
        assert "7/10" in embed["description"]

    def test_long_title_is_truncated(self):
        paper = make_paper()
        paper["title"] = "T" * 300
        embed = report.to_embed(paper)
        assert len(embed["title"]) == 250


class TestPost:
    def test_sends_payload_to_webhook_dummy(self, monkeypatch):
        """report.WEBHOOK には実際にアクセスせず、requests.post をダミーに差し替える。"""
        calls = []

        class FakeResp:
            def raise_for_status(self):
                pass

        def fake_post(url, json, timeout):
            calls.append((url, json, timeout))
            return FakeResp()

        monkeypatch.setattr(report.requests, "post", fake_post)
        report.post([{"title": "x"}], header="hello")

        assert len(calls) == 1
        url, payload, _ = calls[0]
        assert url == report.WEBHOOK
        assert payload == {"embeds": [{"title": "x"}], "content": "hello"}

    def test_omits_content_key_when_no_header(self, monkeypatch):
        calls = []

        class FakeResp:
            def raise_for_status(self):
                pass

        monkeypatch.setattr(report.requests, "post",
                             lambda url, json, timeout: calls.append(json) or FakeResp())
        report.post([{"title": "x"}])
        assert "content" not in calls[0]


class TestMain:
    def test_reports_and_updates_seen_store(self, tmp_path, monkeypatch):
        scored_path = tmp_path / "scored.json"
        seen_path = tmp_path / "seen.json"
        scored_path.write_text(json.dumps([make_paper(id_="W1"), make_paper(id_="W2")]),
                                encoding="utf-8")
        monkeypatch.setattr(report, "SCORED_PATH", scored_path)
        monkeypatch.setattr(report, "SEEN_PATH", seen_path)

        posted = []

        class FakeResp:
            def raise_for_status(self):
                pass

        def fake_post(url, json, timeout):
            posted.append(json)
            return FakeResp()

        monkeypatch.setattr(report.requests, "post", fake_post)
        monkeypatch.setattr(report.time, "sleep", lambda s: None)

        report.main()

        assert len(posted) == 1
        assert len(posted[0]["embeds"]) == 2
        seen = json.loads(seen_path.read_text(encoding="utf-8"))
        assert seen["reported"] == ["W1", "W2"]

    def test_header_breaks_down_keyword_vs_llm_counts(self, tmp_path, monkeypatch):
        scored_path = tmp_path / "scored.json"
        seen_path = tmp_path / "seen.json"
        w1 = make_paper(id_="W1")
        w1["method"] = "keyword"
        w1["matched_keyword"] = "MJO"
        w2 = make_paper(id_="W2")
        w2["method"] = "llm"
        scored_path.write_text(json.dumps([w1, w2]), encoding="utf-8")
        monkeypatch.setattr(report, "SCORED_PATH", scored_path)
        monkeypatch.setattr(report, "SEEN_PATH", seen_path)

        posted = []

        class FakeResp:
            def raise_for_status(self):
                pass

        monkeypatch.setattr(report.requests, "post",
                             lambda url, json, timeout: posted.append(json) or FakeResp())
        monkeypatch.setattr(report.time, "sleep", lambda s: None)

        report.main()

        header = posted[0]["content"]
        assert "🔑キーワード一致 1 件" in header
        assert "🤖LLM採点 1 件" in header

    def test_no_scored_papers_posts_placeholder_message(self, tmp_path, monkeypatch):
        scored_path = tmp_path / "scored.json"
        scored_path.write_text("[]", encoding="utf-8")
        monkeypatch.setattr(report, "SCORED_PATH", scored_path)

        posted = []

        class FakeResp:
            def raise_for_status(self):
                pass

        monkeypatch.setattr(report.requests, "post",
                             lambda url, json, timeout: posted.append(json) or FakeResp())

        report.main()

        assert len(posted) == 1
        assert posted[0]["embeds"] == []
        assert "ヒットはありませんでした" in posted[0]["content"]
