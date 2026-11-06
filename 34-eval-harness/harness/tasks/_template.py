from harness import client as api

def run(env):
    passed, score = False, 0.0
    evidence = "verifier=TBD; outcome=fail; reason=not implemented"
    return {"passed": passed, "score": score, "evidence": evidence}

TASK = {"id": "suryodaya:example", "title": "Example task", "run": run}
