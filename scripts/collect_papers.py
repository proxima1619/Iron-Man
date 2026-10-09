"""Explicit external collection; does not invoke an LLM or control equipment."""
import argparse
import json
import sys
from pathlib import Path
from backend.evidence.papers import DEFAULT_QUERY, fetch_paper, retrieve_papers, search_papers


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query", default=DEFAULT_QUERY)
    parser.add_argument("--limit", type=int, default=3)
    parser.add_argument("--pmcid", action="append", default=[])
    parser.add_argument("--search-only", action="store_true")
    parser.add_argument("--output", type=Path, default=Path("data/sources/paper-sources.json"))
    args = parser.parse_args()
    if args.search_only:
        print(json.dumps(search_papers(args.query, args.limit), ensure_ascii=False, indent=2))
        return
    if len(args.pmcid) > 5:
        parser.error("Collect at most five papers")
    sources = ([fetch_paper(pmcid) for pmcid in dict.fromkeys(args.pmcid)] if args.pmcid
               else retrieve_papers(args.query, args.limit))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(sources, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"file": str(args.output), "papers": len(sources),
                      "source_ids": [s["source_id"] for s in sources]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
