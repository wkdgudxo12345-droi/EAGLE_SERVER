from __future__ import annotations

import csv
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import requests
import yaml


@dataclass(frozen=True)
class Link:
    text: str
    url: str


class PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._href: str | None = None
        self._anchor_parts: list[str] = []
        self.links: list[Link] = []
        self.text_parts: list[str] = []
        self.title_parts: list[str] = []
        self._in_title = False
        self._in_h1 = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = dict(attrs)
        if tag == "a":
            self._href = attrs_dict.get("href")
            self._anchor_parts = []
        elif tag == "title":
            self._in_title = True
        elif tag == "h1":
            self._in_h1 = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._href:
            text = _clean(" ".join(self._anchor_parts))
            self.links.append(Link(text=text, url=self._href.strip()))
            self._href = None
            self._anchor_parts = []
        elif tag == "title":
            self._in_title = False
        elif tag == "h1":
            self._in_h1 = False

    def handle_data(self, data: str) -> None:
        text = _clean(data)
        if not text:
            return
        self.text_parts.append(text)
        if self._href is not None:
            self._anchor_parts.append(text)
        if self._in_title or self._in_h1:
            self.title_parts.append(text)


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _lower(value: Any) -> str:
    return _clean(value).lower()


def _contains_any(text: str, terms: list[str]) -> list[str]:
    lowered = text.lower()
    return [term for term in terms if term and term.lower() in lowered]


def _job_like(url: str, text: str) -> bool:
    parsed = urlparse(url)
    path = parsed.path.lower()
    title = text.lower()
    return any(
        marker in path or marker in title
        for marker in (
            "/job/",
            "/jobs/",
            "advertid=",
            "harvest",
            "weighbridge",
            "sampler",
            "classifier",
            "quality",
            "despatch",
            "dispatch",
            "administrator",
            "data entry",
        )
    )


def _fetch(session: requests.Session, url: str, timeout: int) -> tuple[str, str]:
    response = session.get(url, timeout=timeout, allow_redirects=True)
    response.raise_for_status()
    content_type = response.headers.get("content-type", "")
    if "text/html" not in content_type and "application/xhtml" not in content_type:
        raise ValueError(f"unsupported content type: {content_type}")
    return response.url, response.text


def _parse(html: str, base_url: str) -> tuple[str, str, list[Link]]:
    parser = PageParser()
    parser.feed(html)
    page_text = _clean(" ".join(parser.text_parts))
    page_title = _clean(" ".join(parser.title_parts))
    links: list[Link] = []
    seen: set[str] = set()
    for link in parser.links:
        absolute = urljoin(base_url, link.url)
        if not absolute.startswith(("http://", "https://")) or absolute in seen:
            continue
        seen.add(absolute)
        links.append(Link(text=link.text, url=absolute))
    return page_title, page_text, links


def _route_matches(route: str, text: str, config: dict[str, Any]) -> list[str]:
    if route == "grain":
        return _contains_any(text, list(config.get("grain_terms") or []))
    if route == "food":
        industry = _contains_any(text, list(config.get("food_industry_terms") or []))
        function = _contains_any(text, list(config.get("food_function_terms") or []))
        return industry + function if industry and function else []
    return []


def _date_hint(text: str) -> str:
    patterns = (
        r"(?:date published|posted|closing date)\s*:?\s*(\d{1,2}\s+[A-Za-z]{3,9}\s+20\d{2})",
        r"(20\d{2}-\d{2}-\d{2})",
        r"(\d{1,2}/\d{1,2}/20\d{2})",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return _clean(match.group(1))
    return ""


def _evaluate(text: str, config: dict[str, Any]) -> tuple[str, list[str], list[str], list[str]]:
    closed = _contains_any(text, list(config.get("closed_terms") or []))
    hard = _contains_any(text, list(config.get("hard_reject_terms") or []))
    transport = _contains_any(text, list(config.get("transport_risk_terms") or []))
    positives = _contains_any(text, list(config.get("positive_terms") or []))
    if closed:
        return "REJECT-CLOSED", closed, transport, positives
    if hard:
        return "REJECT-HARD-GATE", hard, transport, positives
    if transport:
        return "HOLD-TRANSPORT", [], transport, positives
    return "KEEP", [], [], positives


def _candidate_key(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.netloc.lower()}{parsed.path.rstrip('/').lower()}?{parsed.query}"


def run() -> int:
    config_path = Path(os.getenv("EAGLE_CRAWL_CONFIG", "config/crawl_aug22_2026.yml"))
    output_dir = Path(os.getenv("OUTPUT_DIR", "output/crawl"))
    max_rows_override = os.getenv("MAX_ROWS", "").strip()

    try:
        config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        print(f"crawl config failed: {exc}", file=sys.stderr)
        return 2

    max_rows = int(max_rows_override or config.get("max_rows", 50))
    timeout = int(config.get("timeout_seconds", 15))
    session = requests.Session()
    session.headers.update({"User-Agent": str(config.get("user_agent") or "EagleJobIntelligence/4.1")})

    discovered: dict[str, dict[str, Any]] = {}
    rejected: list[dict[str, Any]] = []
    source_errors: list[dict[str, str]] = []
    fetched_at = datetime.now(timezone.utc).isoformat()

    for source in config.get("sources") or []:
        source_url = _clean(source.get("url"))
        if not source_url:
            continue
        try:
            resolved_url, html = _fetch(session, source_url, timeout)
            page_title, page_text, links = _parse(html, resolved_url)
        except (requests.RequestException, ValueError) as exc:
            source_errors.append({"source": _clean(source.get("id")), "url": source_url, "error": str(exc)})
            continue

        route = _lower(source.get("route"))
        source_context = " ".join(
            [
                _clean(source.get("company")),
                _clean(source.get("id")),
                page_title,
                source_url,
            ]
        )
        page_matches = _route_matches(route, f"{source_context} {page_text}", config)
        page_candidates = [Link(text=page_title or _clean(source.get("id")), url=resolved_url)] if page_matches else []

        for link in links:
            if not _job_like(link.url, link.text):
                continue
            anchor_context = f"{source_context} {link.text} {link.url}"
            matches = _route_matches(route, anchor_context, config)
            if route == "food" and not matches:
                # Food search URLs already provide the industry context; permit function-title matches.
                function_matches = _contains_any(anchor_context, list(config.get("food_function_terms") or []))
                if function_matches and any(term in source_url.lower() for term in ("meat", "food", "poultry")):
                    matches = function_matches
            if matches:
                page_candidates.append(link)

        for link in page_candidates:
            key = _candidate_key(link.url)
            if key in discovered:
                continue
            detail_title = link.text
            detail_text = ""
            detail_url = link.url
            try:
                if link.url == resolved_url:
                    detail_title = detail_title or page_title
                    detail_text = page_text
                else:
                    detail_url, detail_html = _fetch(session, link.url, timeout)
                    parsed_title, detail_text, _ = _parse(detail_html, detail_url)
                    detail_title = parsed_title or detail_title
            except (requests.RequestException, ValueError) as exc:
                detail_text = f"detail fetch unavailable: {exc}"

            combined = _clean(f"{source_context} {detail_title} {detail_text}")
            matches = _route_matches(route, combined, config)
            if not matches and route == "food":
                matches = _contains_any(combined, list(config.get("food_function_terms") or []))
            if not matches:
                continue

            decision, reasons, transport_risks, positives = _evaluate(combined, config)
            item = {
                "company": _clean(source.get("company")),
                "title": _clean(detail_title) or _clean(link.text) or "Untitled vacancy",
                "route": route.upper(),
                "official_source": bool(source.get("official")),
                "source_id": _clean(source.get("id")),
                "job_url": detail_url,
                "source_url": source_url,
                "date_hint": _date_hint(combined),
                "decision": decision,
                "matched_terms": sorted(set(matches)),
                "hard_gate_reasons": sorted(set(reasons)),
                "transport_risks": sorted(set(transport_risks)),
                "positive_signals": sorted(set(positives)),
                "fetched_at": fetched_at,
            }
            if decision.startswith("REJECT"):
                rejected.append(item)
            else:
                discovered[key] = item

    candidates = list(discovered.values())
    candidates.sort(
        key=lambda row: (
            row["decision"] != "KEEP",
            not row["official_source"],
            row["route"],
            row["company"],
            row["title"],
        )
    )
    candidates = candidates[: max(max_rows, 1)]
    for rank, item in enumerate(candidates, 1):
        item["rank"] = rank

    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "crawl_report.json").write_text(
        json.dumps(candidates, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output_dir / "rejected.json").write_text(
        json.dumps(rejected, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output_dir / "source_errors.json").write_text(
        json.dumps(source_errors, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    columns = [
        "rank",
        "company",
        "title",
        "route",
        "official_source",
        "date_hint",
        "decision",
        "job_url",
        "source_url",
        "matched_terms",
        "transport_risks",
        "positive_signals",
        "fetched_at",
    ]
    with (output_dir / "crawl_report.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for item in candidates:
            row = dict(item)
            for field in ("matched_terms", "transport_risks", "positive_signals"):
                row[field] = "; ".join(row.get(field) or [])
            writer.writerow(row)

    summary = {
        "run_label": config.get("run_label", "RUN50-AUG22-GRAIN-FOOD-20260731"),
        "selected_rows": len(candidates),
        "rejected_rows": len(rejected),
        "source_errors": len(source_errors),
        "keep_rows": sum(1 for row in candidates if row["decision"] == "KEEP"),
        "transport_hold_rows": sum(1 for row in candidates if row["decision"] == "HOLD-TRANSPORT"),
        "official_rows": sum(1 for row in candidates if row["official_source"]),
    }
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
