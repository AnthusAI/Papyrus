#!/usr/bin/env python3
"""Score-combination simulation (Shipped ship-1f3d29, Papyrus PPY-0b2cbb / 1bf366).

Reads the editor scores of the 70 published Shipped items, simulates reader votes under five scenarios and compares
four ways of combining editor and reader scores. Fixed seed. Writes CSV and Markdown next to this file.
Nothing here touches production code or data.

    python3 sim.py [seed_dir]   # seed_dir: the Shipped item JSON files (track folders); default reads items.csv
"""

from __future__ import annotations

import csv
import glob
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
SEED_DIR = sys.argv[1] if __name__ == "__main__" and len(sys.argv) > 1 else None  # the Shipped item JSON files; without it items.csv beside this file. Importing (the plugin tests do) never reads argv
SEED = 20261022
DIMS = ["real", "useful", "notable", "novel"]
READER_MINIMUM = 5
EDITOR_WEIGHT = 0.5
SOCK_WEIGHT_TRUSTED = 1.0
SOCK_WEIGHT_NEW = 1 / 3  # limits.newAccountDivisor: a profile under 24 h counts for a third
Z = 1.645
RATE_SLOPE = 0.06  # upvote rate = 0.04 + slope * (true composite - 1): about 13% to 22% across the items

OPTIONS = [
    "A  linear w=0.5, min 5 (current)",
    "B  shrinkage k=5",
    "B  shrinkage k=10",
    "B  shrinkage k=20",
    "B  shrinkage k=40",
    "B  shrinkage k=20, reader share capped at 0.4",
    "C  Front (editor only)",
    "C  Readers tab (reader mean, own prior)",
    "D  Wilson on upvotes",
]
SHORT = {
    OPTIONS[0]: "A",
    OPTIONS[1]: "B5",
    OPTIONS[2]: "B10",
    OPTIONS[3]: "B20",
    OPTIONS[4]: "B40",
    OPTIONS[5]: "B20cap.4",
    OPTIONS[6]: "C-Front",
    OPTIONS[7]: "C-Readers",
    OPTIONS[8]: "D",
}
KEYS = [SHORT[o] for o in OPTIONS]


def load_items() -> tuple[list[str], np.ndarray, list[str]]:
    if SEED_DIR is None:
        with open(os.path.join(HERE, "items.csv")) as f:
            table = sorted(csv.DictReader(f), key=lambda r: r["slug"])
        return ([r["slug"] for r in table], np.array([[float(r[d]) for d in DIMS] for r in table]),
                [r["section"] for r in table])
    rows = [json.load(open(path)) for path in sorted(glob.glob(os.path.join(SEED_DIR, "*", "*.json")))]
    rows = [r for r in rows if "scores" in r]
    rows.sort(key=lambda r: r["slug"])
    slugs = [r["slug"] for r in rows]
    editor = np.array([[r["scores"][d] for d in DIMS] for r in rows], dtype=float)
    sections = [r["tags"][0] for r in rows]
    return slugs, editor, sections


SLUGS, EDITOR, SECTIONS = load_items()
N = len(SLUGS)
EDITOR_COMPOSITE = EDITOR.mean(axis=1)
EDITOR_ORDER = np.lexsort((np.arange(N), -EDITOR_COMPOSITE))  # best first
EDITOR_RANK = np.empty(N, dtype=int)
EDITOR_RANK[EDITOR_ORDER] = np.arange(1, N + 1)


# ---------------------------------------------------------------- state

def empty_state() -> dict:
    return {"sw": np.zeros((N, 4)), "nw": np.zeros((N, 4)), "ups": np.zeros(N), "views": np.zeros(N)}


def copy_state(s: dict) -> dict:
    return {k: v.copy() for k, v in s.items()}


def clip_rate(truth: np.ndarray) -> np.ndarray:
    composite = truth.mean(axis=1)
    return np.clip(0.04 + RATE_SLOPE * (composite - 1.0), 0.02, 0.9)


def honest_state(rng, truth: np.ndarray, n_mean: float, noise: float = 0.8, views_median: float = 120) -> dict:
    """Honest readers: counts ~ Poisson(n_mean), each rates all four dimensions around the truth, integer 1 to 5.
    Views are lognormal and independent of quality; the upvote rate rises with true quality (about 13% to 22%)."""
    s = empty_state()
    counts = rng.poisson(n_mean, size=N) if np.isscalar(n_mean) else rng.poisson(n_mean)
    for i in range(N):
        n = int(counts[i])
        if n:
            r = np.clip(np.rint(truth[i] + rng.normal(0, noise, size=(n, 4))), 1, 5)
            s["sw"][i] = r.sum(axis=0)
            s["nw"][i] = n
    views = np.maximum(1, np.rint(rng.lognormal(np.log(views_median), 0.8, size=N)))
    s["views"] = views
    s["ups"] = rng.binomial(views.astype(int), clip_rate(truth)).astype(float)
    return s


def add_socks(s: dict, target: int, m: float, rating: float, weight: float) -> dict:
    t = copy_state(s)
    if m <= 0:
        return t
    t["sw"][target] += m * weight * rating
    t["nw"][target] += m * weight
    t["ups"][target] += m * weight if rating >= 3 else 0
    t["views"][target] += m * weight
    return t


# ---------------------------------------------------------------- scoring

def reader_composite(s: dict) -> np.ndarray:
    with np.errstate(invalid="ignore", divide="ignore"):
        means = np.where(s["nw"] > 0, s["sw"] / s["nw"], np.nan)
        return np.nanmean(means, axis=1) if np.any(s["nw"] > 0) else np.full(N, np.nan)


def wilson(ups: np.ndarray, views: np.ndarray) -> np.ndarray:
    n = np.maximum(views, 1e-9)
    p = np.clip(ups / n, 0, 1)
    centre = p + Z * Z / (2 * n)
    spread = Z * np.sqrt((p * (1 - p) + Z * Z / (4 * n)) / n)
    return (centre - spread) / (1 + Z * Z / n)


def scores(s: dict, key: str) -> np.ndarray:
    """Base score before time decay (decay multiplies every option alike, see the write-up). nan = not ranked."""
    E = EDITOR
    Ec = E.mean(axis=1)
    nmax = s["nw"].max(axis=1)
    if key == "A":
        with np.errstate(invalid="ignore"):
            rc = np.array([np.nanmean(np.where(s["nw"][i] > 0, s["sw"][i] / np.maximum(s["nw"][i], 1e-9), np.nan))
                           if nmax[i] > 0 else np.nan for i in range(N)])
        blend = (nmax >= READER_MINIMUM) & ~np.isnan(rc)
        return np.where(blend, EDITOR_WEIGHT * Ec + (1 - EDITOR_WEIGHT) * np.nan_to_num(rc), Ec)
    if key == "B20cap.4":
        with np.errstate(invalid="ignore", divide="ignore"):
            mean = np.where(s["nw"] > 0, s["sw"] / np.maximum(s["nw"], 1e-9), E)
        share = np.minimum(s["nw"] / (20.0 + s["nw"]), 0.4)
        return (E + share * (mean - E)).mean(axis=1)
    if key.startswith("B"):
        k = float(key[1:])
        return ((k * E + s["sw"]) / (k + s["nw"])).mean(axis=1)
    if key == "C-Front":
        return Ec.copy()
    if key == "C-Readers":
        total_w = s["nw"].sum()
        g = (s["sw"].sum(axis=0) / np.maximum(s["nw"].sum(axis=0), 1e-9)) if total_w > 0 else np.full(4, 3.5)
        sc = ((10.0 * g + s["sw"]) / (10.0 + s["nw"])).mean(axis=1)
        return np.where(nmax > 0, sc, np.nan)
    if key == "D":
        lb = 1.0 + 4.0 * wilson(s["ups"], s["views"])
        return np.where(s["views"] >= 5, lb, np.nan)
    raise KeyError(key)


def ranks(sc: np.ndarray) -> np.ndarray:
    """1 = best. Unranked items sort after ranked ones, by editor composite, so every item has a rank."""
    key = np.where(np.isnan(sc), -1e9 + EDITOR_COMPOSITE, sc)
    order = np.lexsort((np.arange(N), -key))
    out = np.empty(N, dtype=int)
    out[order] = np.arange(1, N + 1)
    return out


def spearman(a: np.ndarray, b: np.ndarray) -> float:
    ra = np.argsort(np.argsort(a)).astype(float)
    rb = np.argsort(np.argsort(b)).astype(float)
    return float(np.corrcoef(ra, rb)[0, 1])


def topk(rank_vector: np.ndarray, k: int) -> set:
    return set(np.where(rank_vector <= k)[0])


def truth_from(delta: np.ndarray) -> np.ndarray:
    return np.clip(EDITOR + delta, 1, 5)


# ---------------------------------------------------------------- scenarios

def stability(rng, trials=200):
    """S1: honest readers who agree with editors (small per-item disagreement sd 0.3) plus rating noise sd 0.8.
    Two independent reader populations rate the same items; how much does the ranking move?"""
    rows = []
    stats = {k: {"split": [], "top10": [], "vs_editor": [], "vs_truth": []} for k in KEYS}
    for _ in range(trials):
        delta = rng.normal(0, 0.3, size=(N, 4))
        truth = truth_from(delta)
        s1, s2 = honest_state(rng, truth, 8), honest_state(rng, truth, 8)
        for k in KEYS:
            r1, r2 = ranks(scores(s1, k)), ranks(scores(s2, k))
            stats[k]["split"].append(spearman(-r1, -r2))
            stats[k]["top10"].append(len(topk(r1, 10) & topk(r2, 10)) / 10)
            stats[k]["vs_editor"].append(spearman(-r1, -EDITOR_RANK))
            stats[k]["vs_truth"].append(spearman(-r1, -ranks(truth.mean(axis=1))))
    for k in KEYS:
        v = stats[k]
        rows.append({"option": k, "split_spearman": np.mean(v["split"]), "top10_overlap": np.mean(v["top10"]),
                     "spearman_vs_editor": np.mean(v["vs_editor"]), "spearman_vs_truth": np.mean(v["vs_truth"])})
    return rows


def d_sensitivity(rng, trials=100):
    """How much of D's instability is my assumption about upvote rates? Split-half Spearman of D when readers see more
    items (views) and upvote rate depends more steeply on quality."""
    global RATE_SLOPE
    saved = RATE_SLOPE
    rows = []
    for views_median in (120, 500, 2000):
        for slope in (0.06, 0.15):
            RATE_SLOPE = slope
            vals, vs_editor = [], []
            for _ in range(trials):
                truth = truth_from(rng.normal(0, 0.3, size=(N, 4)))
                s1 = honest_state(rng, truth, 8, views_median=views_median)
                s2 = honest_state(rng, truth, 8, views_median=views_median)
                r1, r2 = ranks(scores(s1, "D")), ranks(scores(s2, "D"))
                vals.append(spearman(-r1, -r2))
                vs_editor.append(spearman(-r1, -EDITOR_RANK))
            rows.append({"median_views_per_item": views_median, "upvote_rate_slope": slope,
                         "D_split_spearman": np.mean(vals), "D_spearman_vs_editor": np.mean(vs_editor)})
    RATE_SLOPE = saved
    return rows


def brigade(rng, trials=40, cap=300):
    """S3: m sock accounts all give the target item 5 on every dimension and an upvote.
    Targets are the editor's rank-35 item (middle) and rank-10 item. Reports the median number of socks that
    puts the target in the top 5, the median rank at exactly 20 socks, and the same when socks count a third
    (new-account weight). Honest background: Poisson(8) ratings per item."""
    rows = []
    for target_rank in (35, 10):
        target = int(EDITOR_ORDER[target_rank - 1])
        for weight_name, weight in (("full weight", SOCK_WEIGHT_TRUSTED), ("1/3 weight (new account)", SOCK_WEIGHT_NEW)):
            need = {k: [] for k in KEYS}
            at20 = {k: [] for k in KEYS}
            gain = {k: [] for k in KEYS}
            for _ in range(trials):
                truth = truth_from(rng.normal(0, 0.3, size=(N, 4)))
                base = honest_state(rng, truth, 8)
                for k in KEYS:
                    found = None
                    s0 = scores(base, k)[target]
                    s20 = scores(add_socks(base, target, 20, 5.0, weight), k)[target]
                    gain[k].append(0.0 if np.isnan(s0) or np.isnan(s20) else s20 - s0)
                    for m in range(0, cap + 1):
                        r = ranks(scores(add_socks(base, target, m, 5.0, weight), k))[target]
                        if m == 20:
                            at20[k].append(r)
                        if found is None and r <= 5:
                            found = m
                        if found is not None and m >= 20:
                            break
                    need[k].append(found if found is not None else cap + 1)
            for k in KEYS:
                med = int(np.median(need[k]))
                rows.append({"target_editor_rank": target_rank, "sock_weight": weight_name, "option": k,
                             "socks_to_top5_median": f">{cap}" if med > cap else med,
                             "rank_at_20_socks_median": int(np.median(at20[k])),
                             "score_gain_at_20_socks": round(float(np.median(gain[k])), 2)})
    return rows


def brigade_down(rng, trials=40):
    """The same attack in reverse: 20 socks give the editor's number-one item 1 on every dimension and no upvote."""
    target = int(EDITOR_ORDER[0])
    out = {k: {w: [] for w in ("full", "third")} for k in KEYS}
    for _ in range(trials):
        truth = truth_from(rng.normal(0, 0.3, size=(N, 4)))
        base = honest_state(rng, truth, 8)
        for wn, w in (("full", 1.0), ("third", SOCK_WEIGHT_NEW)):
            for k in KEYS:
                t = copy_state(base)
                t["sw"][target] += 20 * w * 1.0
                t["nw"][target] += 20 * w
                t["views"][target] += 20 * w
                out[k][wn].append(ranks(scores(t, k))[target])
    return [{"option": k, "rank_of_top_item_after_20_downvote_socks_full": int(np.median(out[k]["full"])),
             "rank_after_20_socks_third_weight": int(np.median(out[k]["third"]))} for k in KEYS]


def disagreement(rng, trials=100, subset=10):
    """S2: honest readers disagree with the editor on a subset of 10 items by 1.5 points on every dimension (random
    sign). Sweep how many readers rate each item. Closure = how much of the gap between the editor composite
    and the readers' true composite the score moves, averaged over the subset (1 = fully follows readers)."""
    rows = []
    for n_honest in (2, 5, 10, 30):
        closure = {k: [] for k in KEYS}
        corr_truth = {k: [] for k in KEYS}
        corr_editor = {k: [] for k in KEYS}
        hit = {k: [] for k in KEYS}
        for _ in range(trials):
            idx = rng.choice(N, size=subset, replace=False)
            delta = rng.normal(0, 0.2, size=(N, 4))
            delta[idx] = rng.choice([-1.5, 1.5], size=(subset, 1))
            truth = truth_from(delta)
            s = honest_state(rng, truth, n_honest)
            tc = truth.mean(axis=1)
            gap = tc[idx] - EDITOR_COMPOSITE[idx]
            ok = np.abs(gap) > 0.3
            true_rank = ranks(tc)
            for k in KEYS:
                sc = scores(s, k)
                if k == "C-Readers":
                    shift = (sc[idx] - EDITOR_COMPOSITE[idx])
                else:
                    shift = np.where(np.isnan(sc[idx]), 0, sc[idx]) - EDITOR_COMPOSITE[idx] if k != "D" else np.zeros(subset)
                if k == "D":
                    closure[k].append(np.nan)
                elif k == "C-Front":
                    closure[k].append(0.0)
                elif ok.any():
                    closure[k].append(float(np.mean(shift[ok] / gap[ok])))
                r = ranks(sc)
                corr_truth[k].append(spearman(-r, -true_rank))
                corr_editor[k].append(spearman(-r, -EDITOR_RANK))
                hit[k].append(len(topk(r, 10) & topk(true_rank, 10)) / 10)
        for k in KEYS:
            rows.append({"honest_raters_per_item": n_honest, "option": k,
                         "gap_closure": ("n/a" if k == "D" else round(float(np.nanmean(closure[k])), 3)),
                         "spearman_vs_reader_truth": np.mean(corr_truth[k]),
                         "spearman_vs_editor": np.mean(corr_editor[k]),
                         "top10_hit_vs_truth": np.mean(hit[k])})
    return rows


def cold_start(rng, trials=200):
    """S4: every item has one or two ratings (about 15 views). Noise = how far the ranking and the score move away
    from the editor-only order, given readers who agree with the editor. Cliff = how far one item's rank jumps when its
    5th rating arrives (all other items editor-only)."""
    rows = []
    score_dev = {k: [] for k in KEYS}
    rank_dev = {k: [] for k in KEYS}
    s_vs_ed = {k: [] for k in KEYS}
    cliff_score = {k: [] for k in KEYS}
    cliff_rank = {k: [] for k in KEYS}
    for _ in range(trials):
        truth = truth_from(rng.normal(0, 0.3, size=(N, 4)))
        counts = rng.integers(1, 3, size=N)
        s = honest_state(rng, truth, counts.astype(float), views_median=15)
        s["nw"] = np.where(counts[:, None] > 0, counts[:, None], 0).astype(float)
        for k in KEYS:
            sc = scores(s, k)
            r = ranks(sc)
            if k in ("C-Readers",):
                base = ranks(EDITOR_COMPOSITE)
            else:
                base = EDITOR_RANK
            rank_dev[k].append(np.mean(np.abs(r - base)))
            ref = EDITOR_COMPOSITE if k != "D" else None
            if k == "D":
                score_dev[k].append(np.nan)
            else:
                score_dev[k].append(float(np.nanmean(np.abs(np.nan_to_num(sc, nan=3.5) - EDITOR_COMPOSITE))))
            s_vs_ed[k].append(spearman(-r, -EDITOR_RANK))
        item = int(rng.integers(0, N))
        stream = np.clip(np.rint(truth[item] + rng.normal(0, 0.8, size=(6, 4))), 1, 5)
        for k in KEYS:
            res = {}
            for n in (4, 5):
                t = empty_state()
                t["sw"][item] = stream[:n].sum(axis=0)
                t["nw"][item] = n
                t["views"][:] = 15
                t["ups"][:] = 2
                t["ups"][item] = max(1, round(15 * clip_rate(truth)[item]))
                sc = scores(t, k)
                res[n] = (sc[item], ranks(sc)[item])
            cliff_score[k].append(abs(res[5][0] - res[4][0]) if not np.isnan(res[5][0]) and not np.isnan(res[4][0]) else np.nan)
            cliff_rank[k].append(abs(res[5][1] - res[4][1]))
    for k in KEYS:
        rows.append({"option": k, "mean_abs_rank_shift_vs_editor": np.mean(rank_dev[k]),
                     "mean_abs_score_shift_vs_editor": ("n/a" if k == "D" else round(float(np.mean(score_dev[k])), 3)),
                     "spearman_vs_editor": np.mean(s_vs_ed[k]),
                     "rank_jump_when_5th_rating_arrives": np.nanmean(cliff_rank[k]),
                     "score_jump_when_5th_rating_arrives": ("n/a" if k == "D" else round(float(np.nanmean(cliff_score[k])), 3))})
    return rows


def hype(rng, trials=100):
    """S5: one popular-but-overhyped item (about 600 views, 60% upvote rate; readers rate Real and Useful 2, Notable 4.5,
    Novel 4). Two editor cases: the editor saw through it (Real 2.5, Useful 2.5) or was fooled (Real 4.5, Useful 4).
    Reports the item's median rank (of 70) and the reader hype gap."""
    rows = []
    target = int(EDITOR_ORDER[24])  # a mid-table slot to overwrite
    for case, ed in (("editor saw through it", [2.5, 2.5, 4.5, 4.0]), ("editor fooled", [4.5, 4.0, 4.5, 4.0])):
        res = {k: [] for k in KEYS}
        gaps = []
        global EDITOR, EDITOR_COMPOSITE
        saved = EDITOR.copy()
        EDITOR = EDITOR.copy()
        EDITOR[target] = ed
        EDITOR_COMPOSITE = EDITOR.mean(axis=1)
        for _ in range(trials):
            truth = truth_from(rng.normal(0, 0.3, size=(N, 4)))
            truth[target] = [2.0, 2.0, 4.5, 4.0]
            s = honest_state(rng, truth, 8)
            s["views"][target] = 600
            s["ups"][target] = rng.binomial(600, 0.6)
            for k in KEYS:
                res[k].append(ranks(scores(s, k))[target])
            m = s["sw"][target] / s["nw"][target]
            gaps.append((m[2] + m[3]) / 2 - (m[0] + m[1]) / 2)
        EDITOR = saved
        EDITOR_COMPOSITE = EDITOR.mean(axis=1)
        for k in KEYS:
            rows.append({"case": case, "option": k, "median_rank_of_overhyped_item": int(np.median(res[k])),
                         "reader_hype_gap_median": round(float(np.median(gaps)), 2)})
    return rows


def rising(rng, trials=100, cap=300):
    """Rising counts upvotes in a 6-hour window (current rule: raw count). Window views ~ Poisson(views / 28).
    Socks needed for a mid-table item to enter the top 5 of Rising: raw count, Wilson lower bound on the window,
    each at full weight and at a third."""
    out = {}
    for name in ("raw count (current)", "Wilson on window"):
        for wn, w in (("full", 1.0), ("third", SOCK_WEIGHT_TRUSTED / 3)):
            need = []
            for _ in range(trials):
                truth = truth_from(rng.normal(0, 0.3, size=(N, 4)))
                views = np.maximum(1, np.rint(rng.lognormal(np.log(120), 0.8, size=N)))
                wv = rng.poisson(views / 28.0).astype(float)
                wu = rng.binomial(wv.astype(int), clip_rate(truth)).astype(float)
                target = int(rng.integers(0, N))
                found = cap + 1
                for m in range(cap + 1):
                    u, v = wu.copy(), wv.copy()
                    u[target] += m * w
                    v[target] += m * w
                    sc = u if name.startswith("raw") else np.where(v >= 3, wilson(u, v), -1)
                    rank = 1 + int(np.sum(sc > sc[target]))
                    if rank <= 5:
                        found = m
                        break
                need.append(found)
            out[(name, wn)] = int(np.median(need))
    return [{"rising_rule": a, "sock_weight": b, "socks_to_top5_median": (f">{cap}" if v > cap else v)} for (a, b), v in out.items()]


# ---------------------------------------------------------------- output

def write_csv(name: str, rows: list[dict]):
    with open(os.path.join(HERE, name), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        for r in rows:
            w.writerow({k: (round(v, 3) if isinstance(v, float) else v) for k, v in r.items()})


def md_table(rows: list[dict]) -> str:
    cols = list(rows[0].keys())
    lines = ["| " + " | ".join(cols) + " |", "|" + "|".join("---" for _ in cols) + "|"]
    for r in rows:
        lines.append("| " + " | ".join(str(round(r[c], 3) if isinstance(r[c], float) else r[c]) for c in cols) + " |")
    return "\n".join(lines)


def main():
    rng = np.random.default_rng(SEED)
    with open(os.path.join(HERE, "items.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["slug", "section", *DIMS, "editor_composite", "editor_rank"])
        for i in range(N):
            w.writerow([SLUGS[i], SECTIONS[i], *EDITOR[i], round(EDITOR_COMPOSITE[i], 3), EDITOR_RANK[i]])
    results = {
        "stability": stability(rng),
        "disagreement": disagreement(rng),
        "d_sensitivity": d_sensitivity(rng),
        "brigade": brigade(rng),
        "brigade_down": brigade_down(rng),
        "cold_start": cold_start(rng),
        "overhyped": hype(rng),
        "rising": rising(rng),
    }
    titles = {
        "stability": "S1. Rank stability (honest readers who agree with editors, about 8 ratings per item, 200 trials)",
        "disagreement": "S2. Responsiveness to genuine disagreement (10 items where readers differ by 1.5; 100 trials)",
        "d_sensitivity": "S1b. Sensitivity of option D to the assumed upvote behaviour",
        "brigade": "S3. Brigade: socks giving 5 on every dimension plus an upvote (40 trials)",
        "brigade_down": "S3b. Reverse brigade: 20 socks give the editor's top item 1 on every dimension",
        "cold_start": "S4. Cold start: one or two ratings per item (200 trials)",
        "overhyped": "S5. Popular but overhyped item (100 trials)",
        "rising": "Rising: socks to reach the top 5 of the 6-hour window (100 trials)",
    }
    md = [f"# Score combination simulation output\n\nSeed {SEED}. {N} real Shipped items; editor composite mean "
          f"{EDITOR_COMPOSITE.mean():.2f}, sd {EDITOR_COMPOSITE.std():.2f}, range {EDITOR_COMPOSITE.min():.2f} to "
          f"{EDITOR_COMPOSITE.max():.2f}. Scores are base scores before time decay.\n"]
    for key, rows in results.items():
        write_csv(f"results_{key}.csv", rows)
        md.append(f"\n## {titles[key]}\n\n" + md_table(rows) + "\n")
    with open(os.path.join(HERE, "results.md"), "w") as f:
        f.write("\n".join(md))
    print("\n".join(md))


if __name__ == "__main__":
    main()
