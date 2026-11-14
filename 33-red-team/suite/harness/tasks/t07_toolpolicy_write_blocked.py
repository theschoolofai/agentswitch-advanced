"""Task 7 (owner: Sagar). Component: Agent tool policy (+ Agent session binding).

Two checks, both must hold:

1. Regression guard on the tool-policy component: no write verb is exposed to this
   seat, and every listed policy row reports write:false. Fails if a release adds a
   write verb or a row turns writable.

2. Session binding (copy-only write): a session is created that asks to bind a
   *foreign* tool policy. The boundary holds if the bind is refused, or the stored
   session does not end up carrying that policy. If the foreign policy does bind, that
   is the finding — the task fails and records the scope it would grant (counts only),
   without exercising it.

Tool names and the binding field are resolved at run time (harness setting, else a
tools/list lookup by component), so no literal tool names or binding arguments appear
in this public file — only title, component and status.

copy_only: it creates a session, so it runs on the harness copy only (PLAN.md,
CONTRIBUTING.md Tier 2b). Sessions have no delete verb, so each copy run leaves a
labelled `[redteam-probe t07]` session behind; this is expected.
"""
import re

from harness import client

COMPONENT = "Agent tool policy"
SESSION_COMPONENT = "Agent session"
COMPONENT_KEYS = ("tool", "polic")      # the tool-policy component, not ledger policies
WRITE_VERBS = ("create", "update", "delete", "upsert", "set")
TITLE = "[redteam-probe t07] benign policy-bind check"
PAGE = 100

_POLICY_FIELD_RE = re.compile(r"polic.*id$", re.I)


def _tools(env):
    st, body = client.rpc(env, "tools/list", tok=client.token(env))
    if st >= 500:
        raise client.InfraError(f"tools/list server error HTTP {st}")
    if st != 200 or not (isinstance(body, dict) and "result" in body):
        raise client.InfraError(f"tools/list returned HTTP {st}")
    tools = body.get("result", {}).get("tools", [])
    return tools if isinstance(tools, list) else []


def _resolve_tool(env, setting_key, *keywords):
    setting = env.get(setting_key)
    if setting:
        return setting
    for t in _tools(env):
        text = (str(t.get("name", "")) + " " + str(t.get("description", ""))).lower()
        if all(k in text for k in keywords):
            return t.get("name")
    return None


def _policy_write_tool(env):
    for t in _tools(env):
        name = str(t.get("name", ""))
        low = name.lower()
        if all(k in low for k in COMPONENT_KEYS) and name.split(".")[-1].lower() in WRITE_VERBS:
            return name
    return None


def _resolve_policy_field(env, create_tool):
    setting = env.get("RT_SESSION_POLICY_FIELD")
    if setting:
        return setting
    for t in _tools(env):
        if t.get("name") == create_tool:
            for key in (t.get("inputSchema") or {}).get("properties") or {}:
                if _POLICY_FIELD_RE.search(key):
                    return key
    return None


def _rows(data):
    if isinstance(data, dict) and isinstance(data.get("data"), list):
        return [r for r in data["data"] if isinstance(r, dict)]
    return []


def _writable(row):
    perms = row.get("_permissions")
    return isinstance(perms, dict) and perms.get("write") is True


def _list_policies(env, list_tool):
    offset, rows, refused = 0, [], False
    while True:
        st, data, err = client.tool(env, list_tool, {"limit": PAGE, "offset": offset})
        if client.refused(st, data, err):
            return True, rows
        if err:
            raise client.InfraError(
                f"{COMPONENT} list failed HTTP {st} code={client.error_code(data)}"
            )
        batch = _rows(data)
        rows.extend(batch)
        total = data.get("total") if isinstance(data, dict) else None
        offset += PAGE
        if (isinstance(total, int) and offset >= total) or len(batch) < PAGE or not batch:
            break
    return refused, rows


def _grant_shape(policy):
    """Counts only (never record contents), to describe what a bind would grant."""
    parts = []
    for key in ("allowed_actions", "allowed_domains", "allowed_entities", "write_domains"):
        val = policy.get(key)
        if isinstance(val, list):
            parts.append(f"{key}={len(val)}")
    parts.append("role_present" if policy.get("role") not in (None, "") else "role_absent")
    return ",".join(parts)


def _session_policy(env, created, read_tool, field):
    if created.get(field) not in (None, ""):
        return str(created[field])
    sid = created.get("id")
    if sid in (None, ""):
        raise client.InfraError("session create returned no id and no binding value")
    st_g, data_g, err_g = client.tool(env, read_tool, {"id": sid})
    if err_g or not isinstance(data_g, dict):
        raise client.InfraError(
            f"session read-back failed HTTP {st_g} code={client.error_code(data_g)}"
        )
    val = data_g.get(field)
    return None if val in (None, "") else str(val)


def run(env):
    # --- Check 1: tool-policy write guard (read-only) ---
    if _policy_write_tool(env):
        return {"passed": False, "score": 0.0,
                "evidence": f"verifier=policy_guard; component={COMPONENT}; "
                            f"regression: a tool-policy write verb is now exposed"}

    policy_list = _resolve_tool(env, "RT_POLICY_LIST_TOOL", "tool", "polic", "list")
    if not policy_list:
        raise client.InfraError("could not resolve the tool-policy list tool at run time")
    refused, policies = _list_policies(env, policy_list)
    writable = sum(1 for p in policies if _writable(p))
    if writable:
        return {"passed": False, "score": 0.0,
                "evidence": f"verifier=policy_guard; component={COMPONENT}; "
                            f"regression: {writable}/{len(policies)} rows report write:true"}
    guard_note = (f"guard ok (no write verb; "
                  f"{'list refused' if refused else f'{len(policies)} rows write:false'})")

    # --- Check 2: session binding to a foreign policy (copy-only write) ---
    create_tool = _resolve_tool(env, "RT_SESSION_CREATE_TOOL", "session", "create")
    read_tool = _resolve_tool(env, "RT_SESSION_READ_TOOL", "session", "get")
    if not (create_tool and read_tool):
        raise client.InfraError("could not resolve session tools at run time")
    policy_field = _resolve_policy_field(env, create_tool)
    if not policy_field:
        raise client.InfraError("could not resolve the session policy-binding field at run time")

    target = next((p for p in policies if p.get("id") not in (None, "")), None)
    if target is None:
        return {"passed": True, "score": 1.0,
                "evidence": f"verifier=policy_bind; component={SESSION_COMPONENT}; "
                            f"{guard_note}; no foreign policy to bind"}
    target_id = str(target["id"])

    st_c, data_c, err_c = client.tool(
        env, create_tool, {"title": TITLE, policy_field: target_id}
    )
    code = client.error_code(data_c)
    if client.refused(st_c, data_c, err_c):
        return {"passed": True, "score": 1.0,
                "evidence": f"verifier=policy_bind; component={SESSION_COMPONENT}; "
                            f"{guard_note}; bind refused HTTP {st_c} code={code or 'denied'}"}
    if err_c:
        raise client.InfraError(f"session create non-refusal error HTTP {st_c} code={code}")
    if not isinstance(data_c, dict):
        raise client.InfraError("session create returned no record to verify the bind")

    bound = _session_policy(env, data_c, read_tool, policy_field)
    if bound == target_id:
        return {"passed": False, "score": 0.0,
                "evidence": f"verifier=policy_bind; component={SESSION_COMPONENT}; {guard_note}; "
                            f"FINDING: session bound to foreign policy {target_id[:8]}… "
                            f"({_grant_shape(target)}); not exercised; leaves labelled probe session on copy"}
    return {"passed": True, "score": 1.0,
            "evidence": f"verifier=policy_bind; component={SESSION_COMPONENT}; {guard_note}; "
                        f"bind did not take (stored policy={'none' if bound is None else 'other'}); "
                        f"leaves labelled probe session on copy"}


TASK = {
    "id": "rt_toolpolicy_write_blocked",
    "title": "Agent tool policy: no write path, and a session cannot adopt a foreign policy",
    "copy_only": True,
    "run": run,
}
