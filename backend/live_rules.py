import re, json, os
try:
    import yaml
except Exception:
    yaml = None

SAFE_GLOBALS = {"__builtins__": {}}
_token_re = re.compile(r"[A-Za-z_][A-Za-z0-9_.]*")
_quoted_re = re.compile(r"(\'(?:[^'\\]|\\.)*\'|\"(?:[^\"\\]|\\.)*\")")

def _normalize_rules(raw):
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

def _normalize_literals_outside_quotes(s: str) -> str:
    parts = re.split(_quoted_re, s or "")
    for i in range(0, len(parts), 2):
        seg = parts[i]
        seg = re.sub(r"\btrue\b", "True", seg, flags=re.IGNORECASE)
        seg = re.sub(r"\bfalse\b", "False", seg, flags=re.IGNORECASE)
        seg = re.sub(r"\bnull\b", "None", seg, flags=re.IGNORECASE)
        seg = re.sub(r"\bnone\b", "None", seg, flags=re.IGNORECASE)
        parts[i] = seg
    return "".join(parts)

def _tokens_outside_quotes(s: str):
    parts = re.split(_quoted_re, s or "")
    unquoted = "".join(parts[::2])
    return set(_token_re.findall(unquoted))

def _replace_identifiers_outside_quotes(expr: str, facts: dict, reserved: set) -> str:
    parts = re.split(_quoted_re, expr or "")
    for i in range(0, len(parts), 2):
        seg = parts[i]
        tokens = set(_token_re.findall(seg))
        for t in sorted(tokens, key=len, reverse=True):
            if t in reserved:
                continue
            seg = re.sub(rf"\b{re.escape(t)}\b", f"facts.get('{t}')", seg)
        parts[i] = seg
    return "".join(parts)

def _eval_expr(expr: str, facts: dict) -> bool:
    if not expr:
        return False
    RESERVED = {"and", "or", "not", "True", "False", "None"}
    expr_py = _normalize_literals_outside_quotes(expr)
    expr_py = _replace_identifiers_outside_quotes(expr_py, facts, RESERVED)
    try:
        return bool(eval(expr_py, SAFE_GLOBALS, {"facts": facts}))
    except Exception:
        return False

def _render(tmpl: str, facts: dict) -> str:
    return re.sub(
        r"{{\s*([A-Za-z0-9_.]+)\s*}}",
        lambda m: str(facts.get(m.group(1), "")),
        tmpl or ""
    )

def evaluate_facts_document(facts_doc: dict, rules_path: str):
    facts = facts_to_map(facts_doc.get("facts"))
    hostname = (facts_doc.get("host") or {}).get("hostname", "") or facts_doc.get("hostname", "")
    collected_at = facts_doc.get("collected_at")
    rules = load_rules(rules_path)
    out = []
    RESERVED = {"and", "or", "not", "True", "False", "None"}

    for r in rules:
        expr_norm = _normalize_literals_outside_quotes(r["expr"])
        tokens = _tokens_outside_quotes(expr_norm)
        missing = [t for t in tokens if t not in RESERVED and facts.get(t) is None]
        if missing:
            continue
        ok = _eval_expr(r["expr"], facts)
        outcome = "Passed" if ok else "Failed"
        desc = _render(r["pass_text"] if ok else r["fail_text"], facts)
        out.append({
            "time": collected_at,
            "category": r["category"],
            "control": r["title"],
            "outcome": outcome,
            "account": hostname or "LocalPolicy",
            "description": desc,
            "host": hostname,
            "severity": r["severity"],
            "rule_id": r["id"],
            "remediation": r["remediation"],
        })
    return out
