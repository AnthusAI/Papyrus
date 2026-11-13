"""Spike PPY-3f3aac: block-by-block translation of MoM Markdown twins, with rule checks and a bilingual judge.

Usage: python3 -I translate_spike.py SRC_DIR OUT_DIR LANG [LANG...]
Writes only under OUT_DIR. Reads OPENAI_API_KEY from the environment.
"""
import json
import re
import sys
import time
from pathlib import Path

from openai import OpenAI

MODEL = "gpt-6-luna"
PRICE_IN, PRICE_OUT, PRICE_CACHED = 0.10, 0.50, 0.01  # USD per million tokens, src/papyrus_content/data/model_prices.json
LANG_NAMES = {"es": "Spanish (neutral, for readers in Latin America and Spain)", "zh-Hans": "Simplified Chinese"}
GLOSSARY = [
    {"term": "Machines on Machines", "rule": "do not translate"},
    {"term": "Papyrus", "rule": "do not translate"},
    {"term": "AI agent", "es": "agente de IA", "zh-Hans": "AI 智能体"},
    {"term": "desk", "rule": "never translate the newsroom sense of 'desk'; use 'sección' / '栏目'"},
]
client = OpenAI()
usage_total = {"in": 0, "out": 0, "cached": 0}


def blocks_of(markdown: str) -> list[str]:
    """Split into blocks: paragraphs and headings separated by blank lines; a ::: container stays one block."""
    blocks, current, depth = [], [], 0
    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith(":::") and stripped != ":::":
            depth += 1
        elif stripped == ":::" and depth:
            depth -= 1
        if not stripped and depth == 0:
            if current:
                blocks.append("\n".join(current))
                current = []
            continue
        current.append(line)
    if current:
        blocks.append("\n".join(current))
    return blocks


def call(messages, want_json=True):
    for attempt in range(3):
        try:
            response = client.chat.completions.create(
                model=MODEL, messages=messages,
                response_format={"type": "json_object"} if want_json else None,
            )
            u = response.usage
            cached = getattr(getattr(u, "prompt_tokens_details", None), "cached_tokens", 0) or 0
            usage_total["in"] += u.prompt_tokens - cached
            usage_total["cached"] += cached
            usage_total["out"] += u.completion_tokens
            return response.choices[0].message.content, u
        except Exception as error:  # spike: report and retry, then fail loudly
            print("model error", error, file=sys.stderr)
            time.sleep(3 * (attempt + 1))
    raise SystemExit("model failed three times")


def cost(i, o, c=0):
    return (i * PRICE_IN + o * PRICE_OUT + c * PRICE_CACHED) / 1e6


TRANSLATE_SYSTEM = """You translate articles for Machines on Machines, an AI/ML publication, into {lang}.
Return JSON {{"blocks": [...]}} with exactly one translated string per input block, in order.
Rules:
- Keep Markus/Markdown syntax exactly: heading marks, list marks, directive names like ::image or :::note, attribute keys, citation keys like [@key], link targets (URLs), code and equations. Translate only human-readable text, including alt="..." and title="..." attribute values and link text.
- Keep names of people, organisations, products and places as written (transliterate into Chinese only where a standard Chinese name exists, keeping the original in parentheses on first use).
- Keep every number, date, unit and percentage exactly; convert nothing.
- Quotations: translate them, and append the marker {quote_marker} right after the closing quotation mark.
- Keep the publication's plain, precise voice; do not add, drop or soften claims; keep qualifiers ("may", "about", "reported").
- Glossary: {glossary}
"""
QUOTE_MARKER = {"es": "[traducción]", "zh-Hans": "[译文]"}

JUDGE_SYSTEM = """You are a bilingual fact-checking editor. Compare each source block with its {lang} translation.
Report only real problems: changed meaning, changed certainty or qualifiers, omitted or added facts, wrong numbers or names, mistranslated technical terms, broken markup, unnatural phrasing a native reader would stumble on.
Return JSON {{"findings": [{{"block": index, "severity": "high"|"medium"|"low", "kind": "...", "source": "...", "translation": "...", "explanation": "..."}}], "fluency_1_to_5": n, "fidelity_1_to_5": n}}."""

NUM = re.compile(r"\d+(?:[.,]\d+)*")
CITE = re.compile(r"\[@[^\]]+\]")
URL = re.compile(r"\]\(([^)]+)\)")


def rule_checks(src_blocks, tgt_blocks):
    findings = []
    if len(src_blocks) != len(tgt_blocks):
        findings.append({"kind": "block-count", "detail": f"{len(src_blocks)} vs {len(tgt_blocks)}"})
        return findings
    for index, (s, t) in enumerate(zip(src_blocks, tgt_blocks)):
        norm = lambda xs: sorted(x.replace(",", "").replace(".", "") for x in xs)
        if norm(NUM.findall(s)) != norm(NUM.findall(t)):
            findings.append({"kind": "numbers", "block": index, "source": NUM.findall(s), "translation": NUM.findall(t)})
        if sorted(CITE.findall(s)) != sorted(CITE.findall(t)):
            findings.append({"kind": "citations", "block": index})
        if sorted(URL.findall(s)) != sorted(URL.findall(t)):
            findings.append({"kind": "links", "block": index})
        for mark in ("::image", ":::note", ":::", "#"):
            if s.count(mark) != t.count(mark):
                findings.append({"kind": "markup", "block": index, "mark": mark})
                break
    return findings


def translate(path: Path, lang: str, out: Path):
    text = path.read_text()
    src = blocks_of(text)
    start = dict(usage_total)
    system = TRANSLATE_SYSTEM.format(lang=LANG_NAMES[lang], glossary=json.dumps(GLOSSARY, ensure_ascii=False),
                                     quote_marker=QUOTE_MARKER[lang])
    tgt = []
    batch = 12  # spike batching only; production translates changed blocks with neighbours as context
    for i in range(0, len(src), batch):
        chunk = src[i:i + batch]
        content, _ = call([{"role": "system", "content": system},
                           {"role": "user", "content": json.dumps({"blocks": chunk}, ensure_ascii=False)}])
        got = json.loads(content)["blocks"]
        if len(got) != len(chunk):
            raise SystemExit(f"{path.name} {lang}: block count {len(got)} != {len(chunk)}")
        tgt.extend(got)
    t_in, t_out, t_c = (usage_total[k] - start[k] for k in ("in", "out", "cached"))
    rules = rule_checks(src, tgt)
    pairs = [{"block": i, "source": s, "translation": t} for i, (s, t) in enumerate(zip(src, tgt))]
    jstart = dict(usage_total)
    content, _ = call([{"role": "system", "content": JUDGE_SYSTEM.format(lang=LANG_NAMES[lang])},
                       {"role": "user", "content": json.dumps(pairs, ensure_ascii=False)}])
    judge = json.loads(content)
    j_in, j_out, j_c = (usage_total[k] - jstart[k] for k in ("in", "out", "cached"))
    stem = f"{path.stem}.{lang}"
    (out / f"{stem}.md").write_text("\n\n".join(tgt) + "\n")
    record = {
        "story": path.stem, "lang": lang, "words": len(text.split()), "blocks": len(src),
        "translate": {"in": t_in, "out": t_out, "cached": t_c, "usd": cost(t_in, t_out, t_c)},
        "judge": {"in": j_in, "out": j_out, "cached": j_c, "usd": cost(j_in, j_out, j_c)},
        "rules": rules, "judgeResult": judge,
    }
    (out / f"{stem}.json").write_text(json.dumps(record, ensure_ascii=False, indent=1))
    print(stem, record["words"], "words", f"${record['translate']['usd'] + record['judge']['usd']:.4f}",
          "rules", len(rules), "judge", len(judge.get("findings", [])),
          "fluency", judge.get("fluency_1_to_5"), "fidelity", judge.get("fidelity_1_to_5"), flush=True)
    return record


def main():
    src_dir, out_dir, langs = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3:]
    out_dir.mkdir(parents=True, exist_ok=True)
    records = []
    for path in sorted(src_dir.glob("*.md")):
        for lang in langs:
            records.append(translate(path, lang, out_dir))
    (out_dir / "summary.json").write_text(json.dumps(
        {"usage": usage_total, "usd": cost(usage_total["in"], usage_total["out"], usage_total["cached"]),
         "records": [{k: r[k] for k in ("story", "lang", "words", "blocks", "translate", "judge")} for r in records]},
        indent=1))
    print("TOTAL", usage_total, f"${cost(usage_total['in'], usage_total['out'], usage_total['cached']):.4f}")


if __name__ == "__main__":
    main()
