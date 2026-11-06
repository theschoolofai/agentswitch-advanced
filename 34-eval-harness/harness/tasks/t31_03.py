from harness import client as api

def run(env):
    return {"passed": False, "score": 0.0,
            "evidence": "verifier=TBD; outcome=fail; reason=awaiting tool catalogue"}

TASK = {"id": "suryodaya:t31_03", "title": "Seat 31 — Close fully-shipped orders", "run": run}
