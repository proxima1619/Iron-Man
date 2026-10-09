"""Read-only checks owner 1 can call with a server-trusted source collection.

This validates provenance, quotes and supported proposals, not approval policy or
the semantic truth of a model's applicability assessment. No network or tools.
"""
from backend.contracts import EvidenceReview


def source_bundle_digest(sources: list[dict]) -> str:
    import hashlib
    import json
    return hashlib.sha256(json.dumps(sources, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def verify_review_sources(review: EvidenceReview, sources: list[dict]) -> list[str]:
    review = EvidenceReview.model_validate(review)
    by_id = {source["source_id"]: source for source in sources}
    issues = []
    if len(by_id) != len(sources):
        issues.append("duplicate_source_id")
    cards = {card.evidence_id: card for card in review.cards}
    for card in review.cards:
        source = by_id.get(card.source_id)
        if source is None:
            issues.append(f"unknown_source:{card.source_id}")
            continue
        for key in ("title", "locator", "source_url", "source_type", "publisher", "version", "published_at", "usage"):
            if getattr(card, key) != source.get(key):
                issues.append(f"source_metadata_mismatch:{card.evidence_id}:{key}")
        if not card.excerpt or not card.excerpt.strip() or card.excerpt not in source["text"]:
            issues.append(f"quote_not_found:{card.evidence_id}")
    for candidate in review.proposed_tests:
        card = cards.get(candidate.evidence_id)
        if (candidate.kind != "degraded_cooling" or card is None or card.proposed_test != candidate.kind
                or card.stance not in {"counter", "limitation"} or card.applicability not in {"applicable", "partial"}
                or card.parameter_origin != "demo_assumption"):
            issues.append(f"unsupported_proposal:{candidate.evidence_id}")
    return issues
