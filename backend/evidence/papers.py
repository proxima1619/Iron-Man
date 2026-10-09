"""Search and retrieve reusable open-access JATS full text from Europe PMC.

Fixed provider URLs, no model-provided fetch URL, bounded sizes and timeouts.
Only paragraphs with a verified reusable license enter the review collection.
"""
import hashlib
import json
import re
import xml.etree.ElementTree as ET
from urllib.parse import urlencode
from urllib.request import Request, urlopen

BASE = "https://www.ebi.ac.uk/europepmc/webservices/rest"
DEFAULT_QUERY = '("heat exchanger" AND fouling) OR (pump AND "variable speed" AND energy)'
LICENSE_PATTERN = re.compile(r"https?://creativecommons\.org/(?:licenses/(?:by|by-sa)/[0-9.]+|publicdomain/zero/1\.0)/?")


def _get(url: str, timeout_s: float = 10) -> bytes:
    request = Request(url, headers={"User-Agent": "IronManEvidence/1.0 (educational open-access review)"})
    with urlopen(request, timeout=timeout_s) as response:
        raw = response.read(5_000_001)
    if len(raw) > 5_000_000:
        raise ValueError("Paper response too large")
    return raw


def search_papers(query: str = DEFAULT_QUERY, limit: int = 3) -> list[dict]:
    if not isinstance(query, str) or not query.strip() or len(query) > 500 or not 1 <= limit <= 5:
        raise ValueError("Invalid paper query or limit")
    params = urlencode({"query": f"({query}) AND OPEN_ACCESS:Y", "format": "json",
                        "pageSize": limit, "resultType": "core"})
    result = json.loads(_get(f"{BASE}/search?{params}"))
    records = result.get("resultList", {}).get("result", [])
    return [{"pmcid": row["pmcid"], "title": row.get("title", ""), "doi": row.get("doi"),
             "published_at": row.get("firstPublicationDate"), "author": row.get("authorString")}
            for row in records if re.fullmatch(r"PMC[0-9]+", row.get("pmcid", ""))]


def _text(node) -> str:
    return " ".join("".join(node.itertext()).split()) if node is not None else ""


def extract_source(pmcid: str, raw: bytes) -> dict:
    if not re.fullmatch(r"PMC[0-9]+", pmcid):
        raise ValueError("Invalid PMCID")
    if b"<!ENTITY" in raw.upper():
        raise ValueError("XML entity declarations are not supported")
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise ValueError("Invalid article XML") from exc
    meta = root.find("./front/article-meta")
    if meta is None:
        raise ValueError("Missing article metadata")
    actual_ids = [_text(n) for n in meta.findall("article-id") if n.get("pub-id-type") in {"pmc", "pmcid"}]
    if not any(pmcid == (value if value.startswith("PMC") else f"PMC{value}") for value in actual_ids):
        raise ValueError("Article identifier mismatch")
    licenses = " ".join(ET.tostring(n, encoding="unicode") for n in meta.findall("./permissions/license"))
    match = LICENSE_PATTERN.search(licenses)
    if not match:
        raise ValueError("No supported reusable license found")
    title = _text(meta.find("./title-group/article-title"))
    journal = _text(root.find("./front/journal-meta/journal-title-group/journal-title"))
    authors = [" ".join(filter(None, [_text(n.find("given-names")), _text(n.find("surname"))]))
               for n in meta.findall("./contrib-group/contrib/name")]
    doi = next((_text(n) for n in meta.findall("article-id") if n.get("pub-id-type") == "doi"), None)
    date = next(iter(meta.findall("pub-date")), None)
    year, month, day = (_text(date.find(name)) if date is not None else "" for name in ("year", "month", "day"))
    # Preserve individual complete paragraphs; omit tables, figures and references.
    selected, locators, used = [], [], 0
    for group, paragraphs in (("abstract", meta.findall("./abstract//p")),
                              ("body", root.findall("./body//p"))):
        for index, paragraph in enumerate(paragraphs, 1):
            if len(selected) >= 6:
                break
            text = _text(paragraph)
            relevant = group == "abstract" or any(term in text.lower() for term in
                ("fouling", "heat transfer", "pump", "variable speed", "cooling", "temperature"))
            if not relevant or not text or len(text) > 3000 or used + len(text) + 2 > 9500:
                continue
            selected.append(text)
            locators.append(f"{group}/p[{index}]")
            used += len(text) + 2
            if len(selected) >= 6:
                break
    if not title or not selected:
        raise ValueError("No reviewable article text")
    fingerprint = hashlib.sha256(raw).hexdigest()
    return {"source_id": f"paper-{pmcid}", "title": title,
            "publisher": (journal or "Europe PMC") + " | " + (", ".join(authors) or "authors in linked article"),
            "version": f"PMCID={pmcid}; DOI={doi or 'not listed'}; XML-SHA256={fingerprint}",
            "published_at": "-".join(part for part in (year, month.zfill(2) if month.isdigit() else month,
                                                        day.zfill(2) if day.isdigit() else day) if part) or "not listed",
            "usage": f"{match.group(0)}; authors attributed; whitespace normalized; selected paragraphs only; no figures",
            "source_url": f"https://pmc.ncbi.nlm.nih.gov/articles/{pmcid}/",
            "source_type": "paper", "locator": f"Europe PMC fullTextXML {pmcid}: " + "; ".join(locators),
            "text": "\n\n".join(selected)}


def fetch_paper(pmcid: str) -> dict:
    if not re.fullmatch(r"PMC[0-9]+", pmcid):
        raise ValueError("Invalid PMCID")
    return extract_source(pmcid, _get(f"{BASE}/{pmcid}/fullTextXML"))


def retrieve_papers(query: str = DEFAULT_QUERY, limit: int = 3) -> list[dict]:
    records = search_papers(query, limit)
    # Errors propagate: a failed retrieval must not look like successful evidence absence.
    return [fetch_paper(row["pmcid"]) for row in records]
