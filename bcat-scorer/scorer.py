
from typing import Dict, List, Tuple
import math, json, os

def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))

def to100(v):
    try:
        v = float(v)
    except Exception:
        return None
    return clamp(v*100.0 if v <= 1.0 else v, 0.0, 100.0)

def inv100(v):
    v = to100(v)
    return None if v is None else (100.0 - v)

def minmax(v, vmin, vmax):
    try:
        v = float(v)
    except Exception:
        return None
    if vmin == vmax:
        return 0.0
    return clamp((v - vmin) / (vmax - vmin) * 100.0, 0.0, 100.0)

def talk_balance_score(ratio):
    try:
        r = float(ratio)
    except Exception:
        return None
    return clamp(100.0 - abs(r - 0.5) * 200.0, 0.0, 100.0)

def _avg(*vals):
    v = [float(x) for x in vals if x is not None]
    return sum(v)/len(v) if v else None

def _wavg(vals, weights):
    pts = [(float(v), float(w)) for v, w in zip(vals, weights) if v is not None]
    if not pts:
        return None
    sw = sum(w for _, w in pts)
    if sw <= 0:
        return None
    return sum(v*w for v, w in pts)/sw

def normalize_metrics(spiky: Dict) -> Dict[str, float]:
    out: Dict[str, float] = {}
    L = dict(spiky.get("language") or {})
    V = dict(spiky.get("vocal") or {})
    F = dict(spiky.get("facial") or {})
    I = dict(spiky.get("interaction") or {})
    H = dict(spiky.get("highlevel") or {})

    pos_classes = L.get("positivity_classes") or L.get("polarity") or (L.get("positivity") if isinstance(L.get("positivity"), dict) else None)
    if isinstance(pos_classes, dict):
        p   = float(pos_classes.get("positive", 0.0))
        neu = float(pos_classes.get("neutral", 0.0))
        neg = float(pos_classes.get("negative", 0.0))
        out["positivity"] = to100(p + 0.5*neu)
        out["negativity_inv"] = 100.0 - (neg * 100.0 if neg <= 1 else neg)
    elif "positivity" in L:
        out["positivity"] = to100(L.get("positivity"))

    obj = L.get("objectivity")
    if isinstance(obj, dict):
        out["objectivity"] = to100(obj.get("objective", 0))
    elif obj is not None:
        out["objectivity"] = to100(obj)

    if "filler_ratio" in L: out["filler_inv"] = inv100(L.get("filler_ratio"))
    if "avg_sentence_len" in L: out["avg_sentence_len_norm"] = minmax(L.get("avg_sentence_len"), 4.0, 25.0)
    if "patience" in L: out["patience_norm"] = minmax(L.get("patience"), 0.0, 180.0)
    if isinstance(L.get("keywords"), dict) and L["keywords"]:
        vals = [to100(v) for v in L["keywords"].values() if to100(v) is not None]
        if vals: out["kw_strength"] = sum(vals)/len(vals)
    if "lang_emo_curiosity" in L: out["lang_emo_curiosity"] = to100(L.get("lang_emo_curiosity"))

    if isinstance(L.get("question"), str):
        L["question"] = 1.0 if L["question"].lower().startswith("question") else 0.0
    if "question_ratio" not in L and "question" in L:
        try: qv = float(L["question"])
        except Exception: qv = 1.0 if bool(L["question"]) else 0.0
        L["question_ratio"] = qv
    if "question_ratio" in L: out["question_ratio"] = to100(L["question_ratio"])
    if isinstance(L.get("offensiveness"), str):
        L["offensiveness"] = 1.0 if L["offensiveness"].lower().startswith("offen") else 0.0
    if "offensiveness" in L: out["offensiveness_inv"] = inv100(L["offensiveness"])

    if isinstance(V.get("energy"), dict):
        ener = float(V["energy"].get("energetic", 0.0))
        mono = float(V["energy"].get("monotonic", 0.0))
        V["energy"] = ener if ener > 0 else (1.0 - mono)
    if "energy" in V:
        out["energy"] = to100(V["energy"] if V["energy"] <= 1 else V["energy"]/100.0)

    ve = V.get("emotions") or {}
    if isinstance(ve, dict) and ve:
        emo_pos = ve.get("happy", None)
        emo_neu = ve.get("neutral", None)
        emo_neg = (ve.get("sad", 0.0) or 0.0) + (ve.get("angry", 0.0) or 0.0)
        if emo_pos is not None: out["emo_pos"]     = to100(emo_pos)
        if emo_neu is not None: out["emo_neu"]     = to100(emo_neu)
        out["emo_neg_inv"] = inv100(emo_neg)

    att = F.get("attention") or {}
    if isinstance(att, dict) and att:
        att_att  = att.get("attentive", None)
        att_norm = att.get("normal", None)
        att_dist = att.get("distracted", None)
        att_val = None
        if att_att is not None or att_norm is not None:
            att_val = (att_att or 0.0) + 0.5*(att_norm or 0.0)
        if att_val is not None: out["attention_att"] = to100(att_val)
        if att_dist is not None: out["attention_dist_inv"] = inv100(att_dist)

    fe = F.get("emotions") or {}
    if isinstance(fe, dict) and fe:
        pos = fe.get("happy", None)
        neu = (fe.get("neutral", 0.0) or 0.0) + (fe.get("surprised", 0.0) or 0.0)
        dis = (fe.get("dissatisfied", 0.0) or 0.0) + (fe.get("annoyed", 0.0) or 0.0)
        if pos is not None: out["facial_emo_pos"] = to100(pos)
        out["facial_emo_neu"] = to100(neu)
        out["facial_emo_dis_inv"] = inv100(dis)

    if "talk_listen" in I: out["talk_balance"] = talk_balance_score(I["talk_listen"])
    if "speed_wpm" in I: out["speed_norm"] = minmax(I["speed_wpm"], 90.0, 180.0)

    if "action_items" in H: out["action_items"] = to100(H["action_items"])
    if "followup_questions" in H: out["followup_questions"] = to100(H["followup_questions"])

    return out

def build_curated_metrics(norm: Dict[str, float]) -> Dict[str, float]:
    cur = {}
    cur["objectivity"] = norm.get("objectivity")
    cur["clarity_conciseness"] = _avg(norm.get("filler_inv"), norm.get("avg_sentence_len_norm"))
    cur["energy"] = norm.get("energy")
    cur["decision_orientation"] = norm.get("action_items")
    cur["followup_questions"] = norm.get("followup_questions")
    cur["novelty_ideation"] = _avg(norm.get("kw_strength"), norm.get("lang_emo_curiosity"))
    cur["attention_listening"] = _wavg([norm.get("attention_att"), norm.get("attention_dist_inv")], [0.7, 0.3])
    cur["talk_balance"] = norm.get("talk_balance")
    cur["patience"] = norm.get("patience_norm")
    cur["positivity_tone"] = _avg(norm.get("positivity"), norm.get("emo_pos"), norm.get("emo_neg_inv"))
    return {k: float(v) for k, v in cur.items() if v is not None}

def load_weights() -> Dict[str, Dict[str, float]]:
    here = os.path.dirname(__file__)
    with open(os.path.join(here, "config", "weights.json")) as f:
        return json.load(f)

def load_multipliers() -> Dict[str, float]:
    here = os.path.dirname(__file__)
    with open(os.path.join(here, "config", "multipliers.json")) as f:
        return json.load(f)

def load_patterns() -> Dict[str, Dict[str, object]]:
    here = os.path.dirname(__file__)
    with open(os.path.join(here, "config", "patterns.json")) as f:
        return json.load(f)

def base_factors(curated: Dict[str, float]) -> Dict[str, float]:
    W = load_weights()
    bases = {"Precision": 0.0, "Resolve": 0.0, "Innovation": 0.0, "Harmony": 0.0}
    for m, s in curated.items():
        if m not in W: continue
        row = W[m]; total = sum(row.values()) or 1.0
        for f, w in row.items():
            bases[f] += float(s) * (float(w)/total)
    for k in bases: bases[k] = clamp(bases[k], 0.0, 100.0)
    return bases

def apply_pattern(bases: Dict[str, float], order: List[str]) -> Dict[str, float]:
    multipliers = load_multipliers()
    pmap = {order[0]:"primary", order[1]:"secondary", order[2]:"tertiary", order[3]:"quaternary"}
    out = {}
    for f, base in bases.items():
        mult = multipliers.get(pmap.get(f, "quaternary"), 1.0)
        out[f] = clamp(base * mult, 0.0, 100.0)
    return out

def cosine_alignment(scores: Dict[str, float], order: List[str]) -> float:
    multipliers = load_multipliers()
    tvec = [multipliers["primary"], multipliers["secondary"], multipliers["tertiary"], multipliers["quaternary"]]
    tnorm = math.sqrt(sum(x*x for x in tvec)) or 1.0
    tvec = [x/tnorm for x in tvec]
    svec = [scores[order[0]], scores[order[1]], scores[order[2]], scores[order[3]]]
    snorm = math.sqrt(sum(x*x for x in svec)) or 1.0
    dot = sum(a*b for a,b in zip(svec, tvec))
    sim = dot/(snorm*1.0)
    return clamp(sim*100.0, 0.0, 100.0)

def score_one(spiky: Dict, order: List[str]) -> Dict:
    s_norm = normalize_metrics(spiky)
    s_cur = build_curated_metrics(s_norm)
    bases = base_factors(s_cur)
    scores = apply_pattern(bases, order)
    align = cosine_alignment(scores, order)
    return {
        "factors": {k.lower(): round(v, 2) for k, v in scores.items()},
        "alignment_pct": round(align, 2),
        "normalized_metrics": {"curated": s_cur, "raw": s_norm}
    }

def score_all_patterns(spiky: Dict):
    patterns = load_patterns()
    best = None
    all_scores = {}
    for pid, pinfo in patterns.items():
        res = score_one(spiky, pinfo["order"])
        all_scores[pid] = {**res, "pattern": {"id": int(pid), "name": pinfo["name"], "order": pinfo["order"]}}
        if (best is None) or (res["alignment_pct"] > best["alignment_pct"]):
            best = {**all_scores[pid]}
    return {"best": best, "all": all_scores}
