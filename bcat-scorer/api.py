
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from typing import Optional, Dict, List, Any
from scorer import score_one, score_all_patterns

app = FastAPI(title="BCAT Alignment Service (Auto Pattern Selection)")

class ScoreRequest(BaseModel):
    spiky: Dict[str, Any]
    pattern_id: Optional[int] = Field(default=None)
    pattern_name: Optional[str] = Field(default=None)
    bcat_pattern: Optional[List[str]] = Field(default=None)

@app.get("/health")
def health():
    return {"ok": True}

@app.post("/score")
def score(req: ScoreRequest):
    try:
        # If a pattern is provided, score that one; else auto-select across all 24.
        if req.pattern_id or req.pattern_name or req.bcat_pattern:
            # backward compatible: if a concrete order is given, just score once
            from scorer import load_patterns
            patterns = load_patterns()
            if req.bcat_pattern:
                order = req.bcat_pattern
            elif req.pattern_id and str(req.pattern_id) in patterns:
                order = patterns[str(req.pattern_id)]["order"]
            elif req.pattern_name:
                order = next((v["order"] for v in patterns.values() if v["name"].lower()==req.pattern_name.lower()), None)
                if order is None: raise ValueError("pattern_name not found")
            else:
                order = patterns["15"]["order"]
            res = score_one(req.spiky, order)
            return {"best": {"pattern":{"id": None, "name":"custom","order":order}, **res}, "all": {}}
        else:
            return score_all_patterns(req.spiky)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
