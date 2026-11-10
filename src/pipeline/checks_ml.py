"""Checks for the ML layer (src/models/payee_classifier.py, src/models/grant_groups.py; sql/mart/60-61).

Registered by the last line of checks.py, which imports this module; on import `register()` wraps checks.phase5_payment_screen,
the last phase checks.run calls, so these checks run right after it with the same `check` and `one` helpers.
Sizes, no missing labels, the evaluation metrics present, and the leads well formed. Stop checks guard the tables'
shape; how good the labels are is reported (warn), never a reason to block a build.
"""
import sys
from pathlib import Path

import yaml

CFG = Path(__file__).resolve().parents[2] / "config" / "assumptions.yaml"


def _has(one, table):
    return one("SELECT count(*) FROM information_schema.tables WHERE table_schema = 'mart' AND table_name = ?", table) > 0


def phase5_ml(con, check, one):
    cfg = yaml.safe_load(CFG.read_text())
    if _has(one, "d_payee_class"):
        n, names = one("SELECT count(*) FROM mart.d_payee_class"), one("SELECT count(*) FROM mart.v_payee_class_input")
        nulls = one("""SELECT count(*) FROM mart.d_payee_class WHERE final_label IS NULL OR rule_class IS NULL OR model_label IS NULL
                       OR confidence IS NULL OR confidence < 0 OR confidence > 1 OR review_flag IS NULL""")
        bad = one("""SELECT count(*) FROM mart.d_payee_class WHERE final_label NOT IN ('business', 'government', 'nonprofit', 'individual/withheld', 'other')""")
        check("mart", "Payee classifier: one row per payee name, no missing or unknown label, confidence in [0, 1]",
              n == names and nulls == 0 and bad == 0 and n > 0, f"{n:,} rows for {names:,} payee names; {nulls} missing; {bad} unknown labels")
        need = {(m, k) for m in ("rules", "model", "combined") for k in ("accuracy", "macro_f1", "dollars_classified_share")}
        have = {(m, k) for m, k in con.execute("SELECT method, metric FROM mart.d_payee_class_eval WHERE class = 'all' AND value IS NOT NULL").fetchall()}
        ev = dict(con.execute("SELECT method || ':' || metric, value FROM mart.d_payee_class_eval WHERE class = 'all'").fetchall())
        labeled = ev.get("sample:labeled", 0)
        check("mart", "Payee classifier: evaluation metrics present for rules, model and combined; sample labeled",
              need <= have and labeled >= cfg["payee_classifier"]["eval_size"] and ev.get("sample:not_found", 1) == 0,
              f"{len(need & have)} of {len(need)} metrics; {int(labeled)} labeled names, {int(ev.get('sample:excluded_unsure', 0))} unsure (excluded), "
              f"{int(ev.get('sample:not_found', 0))} not found")
        shown = one("""SELECT count(*) FROM mart.d_payee_class c JOIN mart.v_payee_class_input i USING (payee_key)
                       WHERE c.payee <> i.payee AND c.payee <> 'Payee not named (may be an individual)'""")
        check("mart", "Payee classifier: a name is shown as paid or withheld, never altered", shown == 0, f"{shown} rows")
        promoted = bool(ev.get("decision:combined_promoted", 0))
        check("mart", "Payee classifier: macro F1 on the hand-labeled sample (rules / model / combined)", True,
              f"rules {ev.get('rules:macro_f1', 0):.3f}, model {ev.get('model:macro_f1', 0):.3f}, combined {ev.get('combined:macro_f1', 0):.3f}; "
              f"accuracy {ev.get('rules:accuracy', 0):.3f} / {ev.get('model:accuracy', 0):.3f} / {ev.get('combined:accuracy', 0):.3f}; "
              f"combined {'promoted' if promoted else 'not promoted: final_label = rule label'}; review queue {int(ev.get('model:review_queue', 0)):,}", "warn")
    if _has(one, "d_grant_groups"):
        g = cfg["grant_groups"]
        desc = one("SELECT count(DISTINCT description_key) FROM mart.v_grant_rows")
        mem = one("SELECT count(*) FROM mart.d_grant_group_members")
        orphan = one("SELECT count(*) FROM mart.d_grant_group_members m LEFT JOIN mart.d_grant_groups g USING (group_id) WHERE g.group_id IS NULL")
        dup = one("SELECT count(*) - count(DISTINCT group_id) FROM mart.d_grant_groups")
        nulls = one("SELECT count(*) FROM mart.d_grant_groups WHERE group_id IS NULL OR description IS NULL OR n_agencies < 1 OR overlap_lead IS NULL")
        check("mart", "Grant groups: every distinct description in exactly one group; group ids unique; no missing fields",
              mem == desc and orphan == 0 and dup == 0 and nulls == 0 and desc > 0,
              f"{desc:,} descriptions, {mem:,} members, {one('SELECT count(*) FROM mart.d_grant_groups'):,} groups; {orphan} orphans; {dup} duplicate ids; {nulls} missing")
        fy = g["lead_fy"]
        tie = one(f"SELECT abs((SELECT sum(amount_fy{fy}) FROM mart.d_grant_groups) - (SELECT coalesce(sum(amount), 0) FROM mart.v_grant_rows WHERE fiscal_year = {fy}))")
        badlead = one(f"SELECT count(*) FROM mart.d_grant_groups WHERE overlap_lead <> (n_agencies_fy{fy} >= {g['min_agencies']})")
        check("mart", f"Grant groups: FY{fy} dollars tie to the grants rows; leads are exactly the groups with {g['min_agencies']}+ grantor agencies in FY{fy}",
              tie < 0.01 and badlead == 0, f"gap ${tie:,.2f}; {badlead} mislabeled leads")
        s = con.execute("SELECT cosine_threshold, backend, groups, overlap_leads, lead_amount_fy FROM mart.d_grant_groups_sensitivity ORDER BY 1").fetchall()
        want = sorted({g["cosine_threshold"], *g["sensitivity"]})
        check("mart", "Grant groups: sensitivity reported at every threshold (leads are not savings)", [r[0] for r in s] == want,
              f"backend {s[0][1] if s else 'none'}; " + "; ".join(f"{t:.2f}: {n:,} groups, {k} leads (${a / 1e6:,.2f}M FY{fy} grants)" for t, _, n, k, a in s), "warn")


def register(checks):
    """Chain phase5_ml after checks.phase5_payment_screen (idempotent)."""
    orig = checks.phase5_payment_screen
    if getattr(orig, "_with_ml", False):
        return

    def phase5_payment_screen(con, check, one):
        orig(con, check, one)
        phase5_ml(con, check, one)
    phase5_payment_screen._with_ml = True
    phase5_payment_screen.__doc__ = orig.__doc__
    checks.phase5_payment_screen = phase5_payment_screen


if __package__ and f"{__package__}.checks" in sys.modules:  # imported by the last line of checks.py
    register(sys.modules[f"{__package__}.checks"])
