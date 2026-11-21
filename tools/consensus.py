"""Compute what holds everywhere, what holds with exceptions, and what nobody answers.

COMPUTED, NEVER WRITTEN BY HAND. A hand-written summary is a claim; it goes stale
silently the moment one entity changes, which is the exact failure this repo exists
to catch in other people's resources.

THE DENOMINATOR IS THE POINT. With 10 entities, "everyone agrees" frequently means
three assessed entities agree. Every band carries n/N, and any band computed on
fewer than MIN_CONFIDENT assessed entities is marked provisional. Reporting a
fraction without its denominator would manufacture precisely the false confidence
the rest of this project is built to expose.
"""
from __future__ import annotations
from collections import Counter

MIN_CONFIDENT = 4          # below this we decline to call it at all
STRONG = 0.75              # majority threshold for "holds, with exceptions"

# Band on STANCE, not on the fine-grained verdict. Eight entities that all permit
# an activity — four with conditions, four without — agree. Treating that as a
# "split" would report a distinction without a difference as disagreement.
STANCE = {
    "permitted": "allows", "permitted_with_conditions": "allows",
    "prohibited": "forbids", "discouraged": "discourages",
    "not_addressed": "silent",
}

PERM_RULE = {
    "permitted":                 "is permitted",
    "permitted_with_conditions": "is permitted under conditions",
    "prohibited":                "is prohibited",
    "discouraged":               "is discouraged",
    "not_addressed":             "is not addressed",
}
# Some axes do not describe something an author is allowed or forbidden to do.
# "Due process is permitted under conditions" is not a sentence a reader can
# use: a record there means the organisation states a safeguard. These axes get
# their own sentence, a count of who states it, never a majority rule.
RULE_OVERRIDE = {
    "due_process": ("At least one AI-specific safeguard (a review trigger, contact with "
                    "the author, or an appeal route) is stated by {count}"),
    "detection_screening": "Screening of submissions (including with AI tools) is stated by {count}",
    "audit_trail": ("Recording or supplying tool versions, prompts or session records is required "
                    "or encouraged by {count}"),
}
# Who the override counts: organisations whose stance allows the activity, except for
# audit_trail, where the question is whether a record must be kept or supplied.
OVERRIDE_COUNTS = {"audit_trail": lambda p: p.get("disclosure") in ("required", "encouraged")}


def count_phrase(n: int, m: int) -> str:
    if n == m:
        return f"all {m} assessed organisations" if m != 1 else "the one assessed organisation"
    return f"{n} of the {m} assessed organisations"

DISC_RULE = {
    "required":     "and must be declared",
    "encouraged":   "and declaration is encouraged",
    "not_required": "and needs no declaration",
    "not_addressed":"",
}


def in_comparison(e: dict) -> bool:
    """The population every computed claim counts: publishers, imprints and
    journals. A missing type means publisher. Classification-only records (a
    taxonomy, not a policy) and advisory bodies, funders and preprint servers
    stay in the records but do not vote. build.py uses the same test, so the
    advice and the consensus panel never count different populations."""
    return (e.get("policy_architecture") != "classification_only"
            and e.get("type", "publisher") in ("publisher", "imprint", "journal"))


def compute(entities: list[dict], axes: dict, axes_raw: dict) -> dict:
    entities = [e for e in entities if in_comparison(e)]
    order = [a["key"] for a in axes_raw["activities"]] + [a["key"] for a in axes_raw["extended_axes"]]
    plain = {a["key"]: a.get("plain", a["key"])
             for a in axes_raw["activities"] + axes_raw["extended_axes"]}

    rows = []
    for k in order:
        recs = [(e, p) for e in entities
                for p in e.get("policies", []) if p["axis"] == k]
        n_assessed = len(recs)
        if n_assessed == 0:
            rows.append({"axis": k, "plain": plain[k], "title": axes[k]["title"],
                         "band": "unassessed", "n": 0, "total": len(entities),
                         "rule": None, "agree": 0, "dissenters": [], "silent": [],
                         "provisional": True,
                         "group": axes[k]["group"]})
            continue

        perms = Counter(p["permission"] for _, p in recs)
        stances = Counter(STANCE[p["permission"]] for _, p in recs)
        modal_stance, stance_n = stances.most_common(1)[0]
        agree = stance_n / n_assessed
        # Finest-grained modal verdict, used only to phrase the rule.
        modal = Counter(p["permission"] for _, p in recs
                        if STANCE[p["permission"]] == modal_stance).most_common(1)[0][0]

        # Disclosure consensus is computed only among entities that actually
        # permit the activity — asking "must you declare a prohibited act" is noise.
        allowing = [p for _, p in recs if p["permission"] in
                    ("permitted", "permitted_with_conditions")]
        disc_modal = None
        dc = Counter()
        if allowing:
            dc = Counter(p["disclosure"] for p in allowing)
            disc_modal = dc.most_common(1)[0][0]

        silent_everywhere = stances.get("silent", 0) == n_assessed

        if n_assessed < MIN_CONFIDENT:
            # Too few records to make any claim. Declining to call it is the
            # honest result; a "universal" rule resting on two entities is noise
            # dressed as a finding.
            band = "thin"
        elif silent_everywhere:
            band = "void"
        elif agree == 1.0:
            band = "universal"
        elif agree >= STRONG:
            band = "strong"
        else:
            band = "split"

        # Dissent is disagreement of STANCE, not of conditions. Silence is not
        # dissent: an organisation that says nothing has not taken the other
        # side, so it is listed separately and never as an exception.
        dissenters = sorted(e["name"] for e, p in recs
                            if STANCE[p["permission"]] not in (modal_stance, "silent"))
        silent = (sorted(e["name"] for e, p in recs if STANCE[p["permission"]] == "silent")
                  if modal_stance != "silent" else [])
        # Where everyone agrees on stance, note whether conditions differ.
        cond_split = (len({p["permission"] for _, p in recs
                           if STANCE[p["permission"]] == modal_stance}) > 1)

        # Tie detection: with an even split the "modal" verdict is decided by
        # entity filename order. Asserting one arbitrary half as THE rule is
        # worse than declining to state one.
        top = stances.most_common(2)
        tied = len(top) > 1 and top[0][1] == top[1][1]

        rule = None
        if band == "thin":
            pass                      # too few to call: no sentence at all
        elif k in RULE_OVERRIDE and not silent_everywhere:
            # A count makes no majority claim, so it holds even on a tie.
            if k in OVERRIDE_COUNTS:
                n_yes = sum(1 for _, p in recs if OVERRIDE_COUNTS[k](p))
            else:
                n_yes = stances.get("allows", 0)
            rule = RULE_OVERRIDE[k].format(count=count_phrase(n_yes, n_assessed))
        elif not silent_everywhere and not tied:
            rule = f"{plain[k]} {PERM_RULE[modal]}"
            # Only attach a disclosure clause when the modal stance ALLOWS the
            # activity. "Prohibited and must be declared" is not a sentence.
            if modal_stance == "allows" and len(dc) > 1:
                rule += " and disclosure requirements vary"
            elif modal_stance == "allows" and disc_modal and DISC_RULE[disc_modal]:
                rule += f" {DISC_RULE[disc_modal]}"

        # Where does the modal disclosure go, among those that require it?
        locs = Counter()
        for p in allowing:
            if p["disclosure"] not in ("required", "encouraged"):
                continue
            for l in (p.get("disclosure_location") or []):
                if l != "unspecified":
                    locs[l] += 1

        rows.append({
            "axis": k, "plain": plain[k], "title": axes[k]["title"], "band": band,
            "n": n_assessed, "total": len(entities), "rule": rule,
            "agree": round(agree, 2), "modal": modal, "disclosure": disc_modal,
            "disclosure_counts": dict(dc), "disclosure_varies": len(dc) > 1,
            "dissenters": dissenters, "silent": silent, "stance": modal_stance,
            "override": k in RULE_OVERRIDE,
            "conditions_vary": cond_split,
            "locations": [l for l, _ in locs.most_common(3)],
            "provisional": n_assessed < MIN_CONFIDENT, "tied": tied,
            "stance_counts": dict(stances),
            "group": axes[k]["group"],
        })

    return {
        "min_confident": MIN_CONFIDENT,
        "strong_threshold": STRONG,
        "rows": rows,
        "counts": Counter(r["band"] for r in rows),
    }
