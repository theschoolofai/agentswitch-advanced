"""Task 6 (owner: Sagar). Component: Agent memory.

A memory created for another seat's user must not end up owned by that user.
The memory component exposes a create verb to this seat, so the create is
likely accepted; the task verifies the resulting ownership, not a bare refusal.

Tool names and the ownership field are resolved at run time (harness setting,
else a tools/list lookup by component), so no literal tool names or binding
arguments are published in this public file — only the title, component and
status. Resolve the real identifiers on the copy run via the RT_* settings.

Positive control: before the foreign attempt, a record is created for our own
id and read back. If our own id is not reflected, the ownership field is
unconfirmed and the task raises InfraError rather than reporting a pass (a
create that ignores the field would otherwise always look bound-to-caller and
could never catch a foreign-binding regression).

copy_only: it creates records, so it runs on the harness copy only (PLAN.md
task 6, CONTRIBUTING.md Tier 2b). The component has no delete verb, so each
copy run leaves labelled `[redteam-probe t06]` rows behind; this is expected.
"""
import re

from harness import client

COMPONENT = "Agent memory"
SEAT_COMPONENT = "Agent seat registry"
LABEL = "[redteam-probe t06] benign ownership check"
PAGE = 100

# Generic heuristics for discovery when a harness setting is absent. They match
# the shape of an owner/assignee reference, not any documented argument name.
_OWNER_FIELD_RE = re.compile(r"(?:^|_)(?:user|owner|assignee|assigned_user)(?:_id)?$", re.I)


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


def _resolve_owner_field(env, create_tool):
    setting = env.get("RT_MEMORY_USER_FIELD")
    if setting:
        return setting
    for t in _tools(env):
        if t.get("name") == create_tool:
            props = (t.get("inputSchema") or {}).get("properties") or {}
            for key in props:
                if _OWNER_FIELD_RE.search(key):
                    return key
    return None


def _rows(data):
    if isinstance(data, dict) and isinstance(data.get("data"), list):
        return [r for r in data["data"] if isinstance(r, dict)]
    return []


def _seat_user_field(env, rows):
    """The seat field that holds the assigned user. A seat row can carry more than
    one user-like key (e.g. an always-empty one beside the real assignment), so pick
    the matching field that is actually populated across rows, preferring an
    assignment-named one. A harness setting overrides discovery."""
    setting = env.get("RT_SEAT_USER_FIELD")
    if setting:
        return setting
    candidates = {k for r in rows for k in r if _OWNER_FIELD_RE.search(k)}
    if not candidates:
        return None
    def score(key):
        filled = sum(1 for r in rows if r.get(key) not in (None, ""))
        return (filled, 1 if "assign" in key.lower() else 0)
    best = max(candidates, key=score)
    return best if score(best)[0] > 0 else None


def _list_seats(env, seat_tool):
    offset, rows = 0, []
    while True:
        st, data, err = client.tool(env, seat_tool, {"limit": PAGE, "offset": offset})
        if client.refused(st, data, err):
            return "refused", rows
        if err:
            raise client.InfraError(
                f"{SEAT_COMPONENT} list failed HTTP {st} code={client.error_code(data)}"
            )
        batch = _rows(data)
        rows.extend(batch)
        total = data.get("total") if isinstance(data, dict) else None
        offset += PAGE
        if (isinstance(total, int) and offset >= total) or len(batch) < PAGE or not batch:
            break
    return "ok", rows


def _owner_of(env, created, read_tool, owner_field):
    """The owner the new record was stored with. Prefer the create response; if it
    carries no owner value, read the record back. Returns a string, or None when the
    field is absent/empty."""
    if created.get(owner_field) not in (None, ""):
        return str(created[owner_field])
    rec_id = created.get("id")
    if rec_id in (None, ""):
        raise client.InfraError("create returned no id and no owner value")
    st_g, data_g, err_g = client.tool(env, read_tool, {"id": rec_id})
    if err_g or not isinstance(data_g, dict):
        raise client.InfraError(
            f"read-back after create failed HTTP {st_g} code={client.error_code(data_g)}"
        )
    val = data_g.get(owner_field)
    return None if val in (None, "") else str(val)


def _create(env, create_tool, owner_field, owner_id):
    st, data, err = client.tool(env, create_tool, {"content": LABEL, owner_field: owner_id})
    return st, data, err, client.error_code(data)


def run(env):
    me = client.whoami(env)
    me_id = me.get("id")
    if me_id in (None, ""):
        raise client.InfraError("whoami missing id")
    me_id = str(me_id)

    create_tool = _resolve_tool(env, "RT_MEMORY_CREATE_TOOL", "memor", "create")
    read_tool = _resolve_tool(env, "RT_MEMORY_READ_TOOL", "memor", "get")
    seat_tool = _resolve_tool(env, "RT_SEAT_LIST_TOOL", "seat", "list")
    if not (create_tool and read_tool and seat_tool):
        raise client.InfraError("could not resolve component tools at run time")
    owner_field = _resolve_owner_field(env, create_tool)
    if not owner_field:
        raise client.InfraError("could not resolve the ownership field at run time")

    # Find another seat's assigned user to aim at.
    status, seats = _list_seats(env, seat_tool)
    if status == "refused":
        return {"passed": True, "score": 1.0,
                "evidence": f"verifier=ownership; component={COMPONENT}; reason=seat_list_refused"}
    if not seats:
        return {"passed": True, "score": 1.0,
                "evidence": f"verifier=ownership; component={COMPONENT}; reason=no_seats"}
    seat_field = _seat_user_field(env, seats)
    if not seat_field:
        raise client.InfraError("could not resolve the seat assignment field at run time")
    target = next(
        (str(s[seat_field]) for s in seats
         if s.get(seat_field) not in (None, "") and str(s[seat_field]) != me_id),
        None,
    )
    if target is None:
        return {"passed": True, "score": 1.0,
                "evidence": f"verifier=ownership; component={COMPONENT}; reason=no_other_seat_user; seats={len(seats)}"}

    # Positive control: create one for ourselves and confirm it reads back as ours.
    st_o, data_o, err_o, code_o = _create(env, create_tool, owner_field, me_id)
    if client.refused(st_o, data_o, err_o):
        # Even an own-create is blocked, so the foreign create is blocked too: boundary holds.
        return {"passed": True, "score": 1.0,
                "evidence": f"verifier=ownership; component={COMPONENT}; create refused "
                            f"HTTP {st_o} code={code_o or 'denied'}"}
    if err_o:
        raise client.InfraError(f"own-create non-refusal error HTTP {st_o} code={code_o}")
    if not isinstance(data_o, dict):
        raise client.InfraError("own-create returned no record to confirm the ownership field")
    if _owner_of(env, data_o, read_tool, owner_field) != me_id:
        raise client.InfraError("own-create not reflected as ours; ownership field unconfirmed")

    # Foreign attempt: create one aimed at another seat's user.
    st_f, data_f, err_f, code_f = _create(env, create_tool, owner_field, target)
    if client.refused(st_f, data_f, err_f):
        return {"passed": True, "score": 1.0,
                "evidence": f"verifier=ownership; component={COMPONENT}; foreign create refused "
                            f"HTTP {st_f} code={code_f or 'denied'}; leaves labelled probe rows on copy"}
    if err_f:
        raise client.InfraError(f"foreign-create non-refusal error HTTP {st_f} code={code_f}")
    if not isinstance(data_f, dict):
        raise client.InfraError("foreign-create returned no record to verify ownership")

    owner = _owner_of(env, data_f, read_tool, owner_field)
    if owner == target:
        return {"passed": False, "score": 0.0,
                "evidence": f"verifier=ownership; component={COMPONENT}; created_owned_by_foreign_user; "
                            f"leaves labelled probe rows on copy"}
    where = "own_user" if owner == me_id else ("unassigned" if owner is None else "other_user")
    return {"passed": True, "score": 1.0,
            "evidence": f"verifier=ownership; component={COMPONENT}; created_accepted owner={where}; "
                        f"not_foreign=True; leaves labelled probe rows on copy"}


TASK = {
    "id": "rt_memory_foreign_user",
    "title": "Agent memory: a record created for another seat's user is not owned by that user",
    "copy_only": True,
    "run": run,
}
