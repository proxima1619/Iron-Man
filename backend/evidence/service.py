"""Owner 3: compatible fixture and validated pre-collected document review."""
import hashlib
import json
import os
from pathlib import Path
from urllib.parse import urlsplit
from backend.contracts import NewRequest, Snapshot, EvidenceReview, Scenario, EvidenceCatalog
from backend.evidence import llm
from backend.evidence.schema import Analysis
from backend.evidence.context import review_context, context_description
from backend.evidence import papers

SOURCE_PATH = Path(__file__).resolve().parents[2] / "data" / "sources" / "cooling-demo.json"


def load_sources(path: Path | None = None) -> list[dict]:
    if path is None:
        path = Path(os.environ.get("IRON_MAN_EVIDENCE_SOURCE_PATH", str(SOURCE_PATH)))
    sources = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(sources, list) or len(sources) > 20:
        raise ValueError("Invalid source collection")
    seen = set()
    required = {"source_id", "title", "publisher", "version", "published_at", "usage",
                "source_url", "source_type", "locator", "text"}
    for source in sources:
        if not isinstance(source, dict) or set(source) != required:
            raise ValueError("Invalid source metadata")
        if any(not isinstance(source[k], str) or not source[k].strip()
               for k in required - {"source_url"}):
            raise ValueError("Missing source metadata")
        if source["source_type"] not in {"team_authored_demo", "team_authored_fixture", "paper", "manual", "field_record"}:
            raise ValueError("Invalid source type")
        if source["source_url"] is not None:
            if not isinstance(source["source_url"], str):
                raise ValueError("Invalid source URL")
            url = urlsplit(source["source_url"])
            if url.scheme != "https" or not url.hostname or url.username or url.password:
                raise ValueError("Invalid source URL")
        if source["source_id"] in seen or len(source["text"]) > 10000:
            raise ValueError("Duplicate or oversized source")
        seen.add(source["source_id"])
    return sources


def evidence_catalog() -> EvidenceCatalog:
    """Read-only configuration and metadata, never credentials or document bodies."""
    mode = os.getenv("IRON_MAN_EVIDENCE_MODE", "fixture")
    source_mode = os.getenv("IRON_MAN_EVIDENCE_SOURCE_MODE", "local")
    key_ready = bool(os.getenv("OPENAI_API_KEY", "").strip())
    model_ready = bool(os.getenv("IRON_MAN_EVIDENCE_MODEL", "").strip())
    issues, summaries = [], []
    catalog_error = False
    if mode != "live":
        issues.append("현재 모의 검토 모드입니다. 실제 논문 분석에는 live 설정이 필요합니다.")
    if mode not in {"fixture", "live"} or source_mode not in {"local", "europepmc"}:
        issues.append("근거 모드 설정이 유효하지 않습니다.")
    if not key_ready:
        issues.append("서버에 OPENAI_API_KEY가 설정되지 않았습니다.")
    if not model_ready:
        issues.append("서버에 IRON_MAN_EVIDENCE_MODEL이 설정되지 않았습니다.")
    if source_mode == "local":
        try:
            sources = load_sources()
            summaries = [{k: source[k] for k in ("source_id", "title", "source_type", "source_url", "publisher", "locator")}
                         for source in sources]
            if not sources:
                issues.append("사전 수집 문서 목록이 비어 있습니다.")
        except Exception:
            catalog_error = True
            issues.append("문서 목록을 읽거나 검증하지 못했습니다. 서버의 출처 설정을 확인하세요.")
    return EvidenceCatalog(mode=mode if mode in {"fixture", "live"} else "invalid",
        source_mode=source_mode if source_mode in {"local", "europepmc"} else "invalid",
        api_key_configured=key_ready, model_configured=model_ready, ready=not issues,
        sources=summaries, issues=issues, catalog_error=catalog_error)


def validate_analysis(raw: dict, sources: list[dict], context: dict | None = None) -> EvidenceReview:
    analysis = Analysis.model_validate(raw)
    by_id = {source["source_id"]: source for source in sources}
    cards, tests = [], []
    for index, claim in enumerate(analysis.cards):
        source = by_id.get(claim.source_id)
        if source is None or claim.excerpt not in source["text"]:
            raise ValueError("Unknown source or fabricated quotation")
        if claim.applicability == "applicable" and claim.missing_conditions:
            raise ValueError("Contradictory applicability")
        if claim.proposed_test and (claim.stance == "support" or
                                   claim.applicability not in {"applicable", "partial"}):
            raise ValueError("Unsupported counterexample")
        identity = json.dumps([claim.source_id, source["version"], claim.claim, claim.excerpt, claim.stance],
                              ensure_ascii=False).encode()
        evidence_id = "evidence-" + hashlib.sha256(identity).hexdigest()[:16]
        if any(card["evidence_id"] == evidence_id for card in cards):
            raise ValueError("Duplicate evidence claim")
        card = claim.model_dump()
        card.update({key: source[key] for key in source if key != "text"})
        card["evidence_id"] = evidence_id
        card["parameter_origin"] = "demo_assumption" if claim.proposed_test else None
        if claim.proposed_test and claim.proposed_test != "degraded_cooling":
            card["missing_conditions"] = [*card["missing_conditions"],
                f"지원되지 않는 시험 {claim.proposed_test}: 검증하지 못함. 2번 시험 계약 합의 필요"]
            card["proposed_test"] = None
            card["parameter_origin"] = None
            card["applicability"] = "partial"
        cards.append(card)
        if card["proposed_test"] and not tests:
            tests.append(Scenario(kind=claim.proposed_test, evidence_id=evidence_id))
    sufficient = bool(cards) and all(c["applicability"] == "applicable" and c["matched_conditions"] for c in cards)
    missing = list(dict.fromkeys([*analysis.missing_conditions,
                                 *(condition for c in cards for condition in c["missing_conditions"])]))
    if any(source["source_type"] == "paper" for source in sources):
        for stance, label in (("support", "지지 근거"), ("counter", "반례·실패 조건 근거")):
            if not any(c["stance"] == stance for c in cards):
                missing.append(f"수집한 논문 발췌에서 적용 가능한 {label}를 확보하지 못했습니다.")
    sufficient = sufficient and not missing
    kinds = {source["source_type"] for source in sources}
    limitation = "실제 LLM 문서 검토. 현실 설비 안전을 보증하지 않습니다."
    if "paper" in kinds:
        limitation += " 공개 논문 원문 발췌를 사용하며 해당 논문의 설비·유체·범위와 가상 모델의 차이를 확인해야 합니다."
    if "team_authored_demo" in kinds:
        limitation += " 팀 작성 데모 규정은 실제 제조사 자료가 아닙니다."
    if context:
        limitation += " " + context_description(context)
    if missing:
        limitation += " 미확인 조건: " + "; ".join(missing)
    fingerprint = hashlib.sha256(json.dumps(sources, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    limitation += f" 문서 묶음 SHA256: {fingerprint}"
    return EvidenceReview(mock=False, status="completed" if sufficient else "insufficient",
                          cards=cards, proposed_tests=tests, limitation=limitation)

def review_evidence(request: NewRequest, snapshot: Snapshot) -> EvidenceReview:
    mode = os.environ.get("IRON_MAN_EVIDENCE_MODE", "fixture")
    if mode != "fixture":
        failure_stage = "configuration"
        try:
            if mode != "live":
                raise ValueError("Unsupported evidence mode")
            context = review_context(request, snapshot)
            if context["domain_reasons"]:
                return EvidenceReview(mock=False, status="insufficient", cards=[], proposed_tests=[],
                    limitation=context_description(context) + " 입력 부적합: " + "; ".join(context["domain_reasons"]))
            source_mode = os.environ.get("IRON_MAN_EVIDENCE_SOURCE_MODE", "local")
            failure_stage = "source_collection"
            if source_mode == "local":
                sources = load_sources()
            elif source_mode == "europepmc":
                sources = papers.retrieve_papers(os.environ.get("IRON_MAN_EVIDENCE_QUERY") or papers.DEFAULT_QUERY)
            else:
                raise ValueError("Unsupported source mode")
            if not sources:
                return EvidenceReview(mock=False, status="insufficient", cards=[], proposed_tests=[],
                                      limitation="선택한 문서 묶음 또는 논문 검색에서 검토 가능한 원문 근거를 확보하지 못했습니다.")
            failure_stage = "llm_review"
            raw = llm.analyze({"request": request.model_dump(),
                                                 "snapshot": snapshot.model_dump(),
                                                 "review_context": context,
                                                 "documents": sources})
            failure_stage = "output_validation"
            result = validate_analysis(raw, sources, context)
            label = "실시간 Europe PMC 논문 검색·원문 수집" if source_mode == "europepmc" else "사전 수집 문서 검토"
            return result.model_copy(update={"limitation": label + ". " + result.limitation})
        except Exception:
            return EvidenceReview(mock=False, status="failed", cards=[], proposed_tests=[],
                                  limitation=f"근거 검토 실패 단계: {failure_stage}. 문서·LLM 검토 실패 또는 시간 초과. 실행을 보류하고 설정·출처를 확인하세요.")
    return EvidenceReview(mock=True, status="demo_fixture", cards=[{
        "evidence_id": "demo-evidence-01", "source_id": "team-demo-note",
        "title": "팀 작성 모의 운전 조건", "stance": "limitation",
        "claim": "냉각 효율 저하 조건을 추가 확인하는 흐름을 시연합니다.",
        "applicability": "unknown", "locator": "fixtures/demo-source.md",
        "source_url": None, "source_type": "team_authored_fixture",
    }], proposed_tests=[Scenario(kind="degraded_cooling", evidence_id="demo-evidence-01")],
        limitation="실제 검색·논문·LLM 검토가 아닙니다. 가상 설비 전용 모의 응답입니다. "
                   + context_description(review_context(request, snapshot)))
