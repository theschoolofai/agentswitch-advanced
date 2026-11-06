import os, sys, json, pkgutil, importlib

ENV_KEYS = ["AGENTSWITCH_BASE_URL","AGENTSWITCH_TOKEN","AGENTSWITCH_INSTANCE",
            "AGENTSWITCH_RUN_ID","OPENAI_BASE_URL","OPENAI_API_KEY","OPENAI_MODEL"]

def discover():
    import harness.tasks as pkg
    tasks = []
    for m in pkgutil.iter_modules(pkg.__path__):
        if m.name.startswith("_"):
            continue
        mod = importlib.import_module(f"harness.tasks.{m.name}")
        if hasattr(mod, "TASK"):
            tasks.append(mod.TASK)
    return sorted(tasks, key=lambda t: t["id"])

def run_one(task, env):
    try:
        r = task["run"](env) or {}
        return {"id": task["id"], "title": task["title"],
                "passed": bool(r.get("passed", False)),
                "score": float(r.get("score", 0.0)),
                "evidence": r.get("evidence", "")}
    except Exception as e:
        return {"id": task["id"], "title": task["title"], "passed": False, "score": 0.0,
                "evidence": f"infrastructure: {type(e).__name__}: {e}"}

def main():
    out = "results.json"
    if "--out" in sys.argv:
        out = sys.argv[sys.argv.index("--out")+1]
    env = {k: os.environ.get(k) for k in ENV_KEYS}
    inst = env.get("AGENTSWITCH_INSTANCE") or "unknown"
    tasks = discover()
    results = [run_one(t, env) for t in tasks]
    passed = sum(1 for t in results if t["passed"])
    json.dump({"tasks": results,
               "summary": f"{inst}: {passed}/{len(results)} tasks passed"},
              open(out, "w"), indent=2)
    print(f"wrote {out}: {passed}/{len(results)}")

if __name__ == "__main__":
    main()
