from harness import client as api

def run(env):
    return {"passed": False, "score": 0.0,
            "evidence": "verifier=TBD; outcome=fail; reason=awaiting tool catalogue"}

TASK = {"id": "suryodaya:t31_02", "title": "Seat 31 — Flag sales orders missing a PO", "run": run}
