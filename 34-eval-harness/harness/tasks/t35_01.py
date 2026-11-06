from harness import client as api

def run(env):
    return {"passed": False, "score": 0.0,
            "evidence": "verifier=TBD; outcome=fail; reason=awaiting tool catalogue"}

TASK = {"id": "suryodaya:t35_01", "title": "Seat 35 — Deduplicate partner records by email", "run": run}
