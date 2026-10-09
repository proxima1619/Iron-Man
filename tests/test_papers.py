import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
import pytest
from backend.evidence import papers, service


XML = b'''<article><front><journal-meta><journal-title-group><journal-title>Test Journal</journal-title></journal-title-group></journal-meta>
<article-meta><article-id pub-id-type="pmc">123</article-id><article-id pub-id-type="doi">10.1/example</article-id>
<title-group><article-title>Heat transfer and fouling</article-title></title-group>
<contrib-group><contrib><name><surname>Author</surname><given-names>A</given-names></name></contrib></contrib-group>
<pub-date><year>2024</year><month>2</month><day>3</day></pub-date>
<permissions><license><p>https://creativecommons.org/licenses/by/4.0/</p></license></permissions>
<abstract><p>Fouling reduces heat transfer.</p></abstract></article-meta></front>
<body><sec><title>Methods</title><p>Pump speed affects cooling conditions.</p></sec></body></article>'''


def test_actual_xml_paragraphs_have_provenance():
    source = papers.extract_source("PMC123", XML)
    assert source["source_type"] == "paper"
    assert source["published_at"] == "2024-02-03"
    assert "A Author" in source["publisher"]
    assert "abstract/p[1]" in source["locator"] and "body/p[1]" in source["locator"]
    assert source["text"] == "Fouling reduces heat transfer.\n\nPump speed affects cooling conditions."
    assert "10.1/example" in source["version"] and "XML-SHA256" in source["version"]


@pytest.mark.parametrize("raw", [
    XML.replace(b"licenses/by/4.0", b"licenses/by-nc/4.0"),
    XML.replace(b">123<", b">456<"),
    b"<article />", b"not XML", b'<!ENTITY x "private">' + XML,
])
def test_unusable_or_wrong_article_rejected(raw):
    with pytest.raises(ValueError):
        papers.extract_source("PMC123", raw)


@pytest.mark.parametrize("pmcid", ["123", "PMC../private", "https://example.com", "PMC123?x=1"])
def test_pmcid_cannot_supply_a_url(monkeypatch, pmcid):
    monkeypatch.setattr(papers, "_get", lambda *args: pytest.fail("Unexpected network call"))
    with pytest.raises(ValueError):
        papers.fetch_paper(pmcid)


def test_search_uses_bounded_open_access_provider_query(monkeypatch):
    def get(url):
        parsed = urlsplit(url)
        assert parsed.hostname == "www.ebi.ac.uk"
        query = parse_qs(parsed.query)
        assert "OPEN_ACCESS:Y" in query["query"][0]
        assert query["pageSize"] == ["3"]
        return json.dumps({"resultList": {"result": [
            {"pmcid": "PMC123", "title": "Cooling"}, {"id": "missing pmcid"}]}}).encode()
    monkeypatch.setattr(papers, "_get", get)
    assert papers.search_papers()[0]["pmcid"] == "PMC123"


@pytest.mark.parametrize("query,limit", [("", 3), ("x", 0), ("x", 6), ("x" * 501, 3)])
def test_invalid_search_settings_rejected(query, limit):
    with pytest.raises(ValueError):
        papers.search_papers(query, limit)


def test_collected_real_paper_bundle_validates():
    sources = service.load_sources(Path("data/sources/paper-sources.json"))
    assert len(sources) == 3
    assert all(source["source_type"] == "paper" for source in sources)
    assert all("creativecommons.org" in source["usage"] for source in sources)


def test_failed_retrieval_is_not_silently_empty(monkeypatch):
    monkeypatch.setattr(papers, "search_papers", lambda *args: [{"pmcid": "PMC123"}])
    def fail(*args): raise TimeoutError("provider outage")
    monkeypatch.setattr(papers, "fetch_paper", fail)
    with pytest.raises(TimeoutError):
        papers.retrieve_papers()
