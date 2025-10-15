import re, json, os

# Try YAML if available; otherwise allow JSON rules files
try:
    import yaml  # type: ignore
except Exception:
    yaml = None

SAFE_GLOBALS = {"__builtins__": {}}

# Only match identifier-like tokens (facts IDs), not numbers or operators
_token_re = re.compile(r"[A-Za-z_][A-Za-z0-9_.]*")

# backend/live_rules.py

def _normalize_rules(raw):
    """
    Normalizes rules to a common shape used downstream.
    Back-compat:
      - condition: prefers 'when', falls back to 'expr'
      - text: prefers 'pass'/'fail', falls back to 'pass_text'/'fail_text'
      - category defaults 'Security'; severity defaults 'medium'
      - cc_sfr: carried through if present (supports cc_sfr / ccSfr / cc-sfr)
    """
    rules = []
    for r in (raw or []):
        rules.append({
            "id":          (r.get("id") or r.get("control") or r.get("title")),
            "title":       (r.get("title") or r.get("control") or ""),
            "category":    (r.get("category") or "Security"),
            "severity":    (r.get("severity") or "medium"),
            "expr":        (r.get("when") or r.get("expr") or ""),
            "pass_text":   (r.get("pass") or r.get("pass_text") or "Passed"),
            "fail_text":   (r.get("fail") or r.get("fail_text") or "Failed"),
            "remediation": (r.get("remediation") or ""),
            "cc_sfr":      (r.get("cc_sfr") or r.get("ccSfr") or r.get("cc-sfr") or ""),
        })
    return rules


def load_rules(path: str):
    ext = os.path.splitext(path)[1].lower()
    if ext in (".yml", ".yaml"):
        if yaml is None:
            raise RuntimeError("Rules file is YAML but PyYAML is not installed. Install 'pyyaml' or use a JSON rules file.")
        with open(path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or []
        return _normalize_rules(raw)
    else:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f) or []
        return _normalize_rules(raw)

def facts_to_map(facts_list):
    m = {}
    for f in facts_list or []:
        m[f.get("id")] = f.get("value")
    return m

def _eval_expr(expr: str, facts: dict) -> bool:
    """
    Replace only identifier tokens (e.g., win.password.min_length) with facts.get('...').
    Leave numbers (14), booleans (True/False), and operators (and/or/not) untouched.
    """
    if not expr:
        return False

    RESERVED = {"and", "or", "not", "True", "False", "None"}

    expr_py = expr
    tokens = set(_token_re.findall(expr))
    for t in sorted(tokens, key=len, reverse=True):
        if t in RESERVED:
            continue
        expr_py = re.sub(rf"\b{re.escape(t)}\b", f"facts.get('{t}')", expr_py)

    try:
        return bool(eval(expr_py, SAFE_GLOBALS, {"facts": facts}))
    except Exception:
        return False

def _render(tmpl: str, facts: dict) -> str:
    # Replace {{fact.id}} placeholders using facts map
    return re.sub(
        r"{{\s*([A-Za-z0-9_.]+)\s*}}",
        lambda m: str(facts.get(m.group(1), "")),
        tmpl or ""
    )

def evaluate_facts_document(facts_doc: dict, rules_path: str):
    """
    facts_doc:
      { collector, host:{hostname}, collected_at, facts:[{id,type,value}, ...] }
    returns a list of derived events:
      [{time,category,control,outcome,account,description,host}, ...]
    """
    facts = facts_to_map(facts_doc.get("facts"))
    hostname = (facts_doc.get("host") or {}).get("hostname", "") or facts_doc.get("hostname", "")
    collected_at = facts_doc.get("collected_at")
    rules = load_rules(rules_path)

    out = []
    for r in rules:
        ok = _eval_expr(r["expr"], facts)
        outcome = "Passed" if ok else "Failed"
        desc = _render(r["pass_text"] if ok else r["fail_text"], facts)

        out.append({
            "time": collected_at,
            "category": r["category"],     # used by UI
            "control": r["title"],
            "outcome": outcome,
            "account": hostname or "LocalPolicy",
            "description": desc,
            "host": hostname,
            # severity is normalized and available if/when you add a column/UI usage
            "severity": r["severity"],
            "rule_id": r["id"],
            "remediation": r["remediation"],
        })
    return out
