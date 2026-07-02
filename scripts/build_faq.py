from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
INPUT_PATH = ROOT / "data" / "processed" / "avito_qa.jsonl"
FAQ_DIR = ROOT / "data" / "faq"
REVIEW_DIR = ROOT / "knowledge" / "review"

FAQ_FILES = {
    "sales": "sales.md",
    "delivery": "delivery.md",
    "payment": "payment.md",
    "support": "support.md",
    "elite_fs": "elite_fs.md",
    "hds_pro": "hds_pro.md",
    "active_target": "active_target.md",
}


def load_qa(path: Path = INPUT_PATH) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def clean_answer_text(text: str) -> str:
    text = text.replace("\u00a0", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def target_key_for_pair(pair: dict[str, Any]) -> str:
    product = str(pair.get("product") or "").lower()
    category = str(pair.get("category") or "").lower()
    question = str(pair.get("question") or "").lower()
    marker = f"{product} {category} {question}"
    if "active" in marker or "ат2" in marker:
        return "active_target"
    if "elite" in marker or "фс" in marker:
        return "elite_fs"
    if "hds" in marker or "pro" in marker or "про" in marker:
        return "hds_pro"
    if category in {"delivery", "payment", "support"}:
        return category
    return "sales"


def group_pairs(pairs: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped = {key: [] for key in FAQ_FILES}
    seen: set[tuple[str, str]] = set()
    for pair in pairs:
        question = clean_answer_text(str(pair.get("question") or ""))
        answer = clean_answer_text(str(pair.get("answer") or ""))
        if not question or not answer:
            continue
        dedupe_key = (question.lower(), answer.lower())
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        key = target_key_for_pair(pair)
        grouped[key].append({**pair, "question": question, "answer": answer})
    return grouped


def render_faq_markdown(title: str, pairs: list[dict[str, Any]]) -> str:
    lines = [
        "---",
        f"title: {title}",
        "source: avito_dialogs",
        "review_status: pending",
        "---",
        "",
        f"# {title}",
        "",
    ]
    if not pairs:
        lines.extend(
            [
                "## Черновик",
                "",
                "Пока нет подтвержденных вопросов и ответов для этого раздела.",
                "",
            ]
        )
        return "\n".join(lines).strip() + "\n"

    for pair in pairs:
        lines.extend(
            [
                f"## {pair['question']}",
                "",
                pair["answer"],
                "",
            ]
        )
    return "\n".join(lines).strip() + "\n"


def write_faq_files(grouped: dict[str, list[dict[str, Any]]]) -> list[Path]:
    FAQ_DIR.mkdir(parents=True, exist_ok=True)
    REVIEW_DIR.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    titles = {
        "sales": "FAQ: продажи",
        "delivery": "FAQ: доставка",
        "payment": "FAQ: оплата",
        "support": "FAQ: поддержка",
        "elite_fs": "FAQ: Lowrance Elite FS",
        "hds_pro": "FAQ: Lowrance HDS PRO",
        "active_target": "FAQ: ActiveTarget",
    }
    for key, filename in FAQ_FILES.items():
        content = render_faq_markdown(titles[key], grouped.get(key, []))
        for directory in (FAQ_DIR, REVIEW_DIR):
            path = directory / filename
            path.write_text(content, encoding="utf-8")
            written.append(path)
    return written


def main() -> int:
    pairs = load_qa()
    grouped = group_pairs(pairs)
    written = write_faq_files(grouped)
    print(f"Loaded QA pairs: {len(pairs)}")
    print(f"Written files: {len(written)}")
    print(f"Review directory: {REVIEW_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
