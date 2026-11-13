"""Assemble the three sections into one briefing per system and render it as Markdown."""
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from datetime import time as dtime

from . import collect, drafts, rrule, rules, slots as slots_mod
from .llm import TIME_LIMIT_MESSAGE


def _guard(fn, *args, **kw) -> dict:
    try:
        return fn(*args, **kw)
    except Exception as exc:
        return collect._error_section(exc)


FLAGGED = "possible_prompt_injection"
DRAFT_REVIEW = "draft_needs_review"


def _scanned(msg: dict) -> str:
    return "\n".join(str(msg.get(k) or "") for k in drafts.SCANNED_FIELDS)


def _injected(msg: dict) -> bool:
    try:
        return bool(drafts.injection_flags(_scanned(msg)))
    except Exception:
        return True  # if even the scan fails, treat the message as suspect


def _not_assessed(msg: dict, reason: str, error: str) -> dict:
    return {**msg, "needs_reply": None, "reason": reason, "draft": None, "flags": [FLAGGED] if _injected(msg) else [],
            "error": error}


def _save(client, me, item: dict, ctx: dict, review=None) -> dict:
    flags = item.get("flags") or []
    if FLAGGED in flags:
        return {"status": "skipped", "id": None, "error": "flagged message — review manually"}
    if DRAFT_REVIEW in flags:
        return {"status": "skipped", "id": None, "error": "draft needs review — not saved"}
    text = item["draft"]
    if review is not None:
        action, detail = review(item, item, ctx["slots"])
        if action == "quit":
            return {"status": "skipped", "id": None, "error": "review stopped"}
        if action != "save" or not isinstance(detail, str) or not detail.strip():
            return {"status": "skipped", "id": None, "error": str(detail or "skipped in review")}
        if detail != text:
            # The review checks edits too; checking again here keeps the rule independent of the review code.
            kinds = drafts.check_draft(detail, item, ctx["slots"])
            if kinds:
                return {"status": "skipped", "id": None,
                        "error": f"edited draft not saved: {drafts.review_reason(kinds)}"}
            item["draft"], item["draft_edited"], text = detail, True, detail
    return drafts.save_draft(client, me, item, text, mailbox_ids=ctx["mailbox_ids"], cache=ctx["cache"])


def _assess(me, msg: dict, llm, ctx: dict) -> dict:
    """The model part only: no platform calls, so several can run at once."""
    try:
        deadline = ctx["deadline"]
        # the model's own clock when it has one, so the deadline and the model agree on what time it is
        clock = getattr(llm, "clock", None) or time.monotonic
        if llm is not None and deadline is not None and clock() >= deadline:
            # Not even tried: the run is out of time. Never a guess, never "no reply needed".
            return _not_assessed(msg, TIME_LIMIT_MESSAGE, TIME_LIMIT_MESSAGE)
        item = {**msg, **drafts.triage(msg, me, llm, slots=ctx["slots"])}
        if item.get("error") == TIME_LIMIT_MESSAGE:
            item["reason"] = TIME_LIMIT_MESSAGE
        return item
    except Exception as exc:  # one odd message becomes an item with an error, not a lost briefing
        detail = f"{type(exc).__name__}: {exc}"[:200]
        return _not_assessed(msg, f"could not assess: {detail}", detail)


def _save_one(client, me, item: dict, ctx: dict, review=None) -> None:
    if item.get("needs_reply") is not True or not item.get("draft") or "draft_saved" in item:
        return
    try:
        item["draft_saved"] = _save(client, me, item, ctx, review)
    except Exception as exc:
        item["draft_saved"] = {"status": "error", "id": None, "error": f"{type(exc).__name__}: {exc}"[:200]}


def _skip(msg: dict, reason: str, by: str) -> dict:
    return {"id": msg.get("id"), "subject": msg.get("subject"), "from_name": msg.get("from_name"),
            "from_email": msg.get("from_email"), "reason": reason, "by": by}


def _anchor(now: datetime | None, day: date, tz) -> datetime:
    # Never offer a time that has passed: with --today in the past, slots still start after the real now; with a
    # future --today, they start after that day.
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return max(now.astimezone(tz), datetime.combine(day, dtime(0, 0), tzinfo=tz))


def _free_slots(client, me, tz, now: datetime) -> dict:
    try:
        out = slots_mod.free_slots(client, me, tz, now)
    except Exception as exc:  # the contract says never raises; a bug there must not cost the mail section
        return {"status": "error", "slots": [], "error": f"{type(exc).__name__}: {exc}"[:200]}
    if not isinstance(out, dict) or out.get("status") not in ("ok", "error"):
        return {"status": "error", "slots": [], "error": "free-time lookup returned an unexpected result"}
    return out


def _context(mail: dict, deadline=None) -> dict:
    free = mail.get("free_slots")
    slots = None
    if isinstance(free, dict) and free.get("status") == "ok":
        slots = [s for s in free.get("slots") or [] if isinstance(s, dict)]
    # one Drafts listing per run, shared by every message
    return {"slots": slots, "deadline": deadline, "mailbox_ids": mail.get("mailbox_ids"), "cache": {}}


def _triage_mail(client, me, mail: dict, llm, save_drafts: bool, deadline, now, day, tz, parallel: int) -> dict:
    own = {collect._lower(me.get("email"))} | {collect._lower(i.get("mailbox_email")) for i in mail["items"]}
    own.discard("")
    skipped, to_model = [], []
    for msg in mail["items"]:
        # A message that trips the injection scan is never skipped by a rule: headers are sender-controlled.
        reason = None if _injected(msg) else rules.skip_reason(msg, own)
        if reason:
            skipped.append(_skip(msg, reason, "rule"))
        else:
            to_model.append(msg)
    if to_model and llm is not None:
        mail["free_slots"] = _free_slots(client, me, tz, _anchor(now, day, tz))
    ctx = _context(mail, deadline)
    workers = max(1, min(int(parallel or 1), len(to_model)))
    if llm is not None and workers > 1:
        # Model calls take seconds each; a few at once keep the run inside its time limit. map() keeps mail order.
        with ThreadPoolExecutor(max_workers=workers) as pool:
            assessed = list(pool.map(lambda m: _assess(me, m, llm, ctx), to_model))
    else:
        assessed = [_assess(me, m, llm, ctx) for m in to_model]
    listed = []
    for msg, item in zip(to_model, assessed):
        # A flagged message stays visible whatever the model said: the model may have been talked out of it.
        if item.get("needs_reply") is False and FLAGGED not in (item.get("flags") or []):
            skipped.append(_skip(msg, item.get("reason") or "", "model"))
            continue
        listed.append(item)
    if save_drafts:
        for item in listed:  # saved one by one, in order: platform writes are never run in parallel
            _save_one(client, me, item, ctx)
    mail["items"] = listed
    mail["skipped"] = skipped
    mail["not_needing_reply"] = len(skipped)
    return mail


def review_drafts(client, me, b: dict, review) -> dict:
    """Offer each clean draft of a finished briefing to `review` and save what it approves. Runs after every model
    call is done, so the time spent reading drafts never counts against the model time limit."""
    mail = b.get("mail") or {}
    if mail.get("status") == "ok":
        ctx = _context(mail)
        for item in mail.get("items") or []:
            _save_one(client, me, item, ctx, review)
    b["drafts_saved"] = True
    b["reviewed"] = True
    return b


def build_briefing(client, me, day: date, tz, llm=None, save_drafts: bool = False, mail_cap: int = 25,
                   unread_only: bool = False, deadline: float | None = None, now: datetime | None = None,
                   review=None, model_parallel: int = 1) -> dict:
    """`review`: optional callable used instead of auto-save (see review.Reviewer); it is asked only after all mail
    has been triaged. `model_parallel`: how many model calls may run at once."""
    original_me = me if isinstance(me, dict) else {}
    me = original_me
    mail = _guard(collect.collect_mail, client, me, cap=mail_cap, day=day, tz=tz, unread_only=unread_only)
    # An invite may go to the mailbox address rather than the login address; both are "me" for meeting status.
    boxes = [i.get("mailbox_email") for i in mail.get("items") or [] if isinstance(i.get("mailbox_email"), str)]
    addresses = [a for a in dict.fromkeys([me.get("email"), *boxes]) if isinstance(a, str) and a]
    me = {**me, "addresses": addresses}
    reviewing = bool(save_drafts and review is not None)
    if mail.get("status") == "ok":
        mail = _guard(_triage_mail, client, me, mail, llm, save_drafts and not reviewing, deadline, now, day, tz,
                      model_parallel)
    warnings = [w for w in [getattr(client, "tz_note", None)] if isinstance(w, str) and w]
    items = mail.get("items") or []
    timed_out = [i for i in items if i.get("error") == TIME_LIMIT_MESSAGE]
    unassessed = [i for i in items if i.get("error") and i.get("error") != TIME_LIMIT_MESSAGE]
    if llm is not None and unassessed:
        # a dead or misconfigured model leaves every item "Not assessed"; that must not pass as a clean run
        warnings.append(f"{len(unassessed)} of {len(items)} emails could not be assessed by the model")
    if timed_out:
        warnings.append(f"{len(timed_out)} of {len(items)} emails not assessed: time limit reached")
    free = mail.get("free_slots")
    if isinstance(free, dict) and free.get("status") == "error":
        warnings.append(f"could not work out your free times ({free.get('error') or 'unknown error'}); "
                        "drafts offer no times")
    b = {
        "generated_for": {"name": me.get("name"), "email": me.get("email")},
        "date": day.isoformat(),
        "timezone": getattr(tz, "key", None) or str(tz),
        "tz_source": getattr(client, "tz_source", None),
        "instance": getattr(client, "instance", None),
        "mail": mail,
        "meetings": _guard(collect.collect_meetings, client, me, day, tz),
        "overdue": _guard(collect.collect_overdue, client, me, day),
        "drafts_saved": bool(save_drafts),
        "reviewed": False,
        "warnings": warnings,
    }
    return review_drafts(client, original_me, b, review) if reviewing else b


def draft_errors(b: dict) -> list[str]:
    mail = b.get("mail") or {}
    return [str((i.get("draft_saved") or {}).get("error")) for i in mail.get("items") or []
            if isinstance(i.get("draft_saved"), dict) and i["draft_saved"].get("status") == "error"]


_CONTROL = re.compile("[\\x00-\\x08\\x0b-\\x1f\\x7f-\\x9f]")
_MD_SPECIAL = re.compile(r"([\\`*_~|\[\]])")
_LINE_START = re.compile(r"^([#+-]|\d+(?=[.)]))")


def _clean(value, multiline: bool = False) -> str:
    text = str(value if value is not None else "")
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\t", "    ")
    if not multiline:
        text = " ".join(text.split("\n"))
    return drafts._INVISIBLE.sub("", _CONTROL.sub("", text))


def plain(value) -> str:
    """Untrusted text as inert Markdown: no control, zero-width or bidi characters; emphasis, code, table, link and
    HTML characters escaped, plus list or heading markers at the start. Other punctuation is left readable."""
    text = _MD_SPECIAL.sub(r"\\\1", _clean(value).strip())
    text = text.replace("<", "&lt;").replace(">", "&gt;")
    # "[x](y)" is already dead once the brackets are escaped; escaping the paren too keeps "](" out of the text.
    text = text.replace("\\](", "\\]\\(")
    # GFM turns bare URLs into links even without brackets; an escaped colon or dot is enough to stop that.
    text = text.replace("://", "\\://")
    text = re.sub(r"(?i)\bwww\.", lambda m: m.group(0)[:-1] + "\\.", text)
    m = _LINE_START.match(text)
    if m:
        # A leading "#", "-", "+" or "12." would become a heading or list item.
        text = ("\\" + text) if m.group(1) in "#+-" else text[:m.end()] + "\\" + text[m.end():]
    return text


def _word(value) -> str:
    # Status enums are shown as-is (intraword underscores do not format); anything else is escaped.
    text = str(value or "")
    return text if re.fullmatch(r"[a-z][a-z_]*", text) else plain(text)


def _draft_block(text: str) -> list[str]:
    """The draft as an indented quote under its list item, each line escaped so the draft cannot format itself."""
    lines = _clean(text, multiline=True).strip("\n").split("\n")
    return [f"    > {plain(ln)}" if ln.strip() else "    >" for ln in lines]


def _status_lines(sec: dict, empty: str) -> list[str] | None:
    status = sec.get("status")
    if status == "no_mailbox":
        return ["No mailbox is linked to this login yet."]
    if status == "error":
        return [f"Could not load: {plain(sec.get('error') or 'unknown error')}"]
    if status != "ok":
        return [f"Could not load: unexpected section status {plain(status)}"]
    if not sec.get("items"):
        return [empty]
    return None


def _tail_lines(sec: dict) -> list[str]:
    out = []
    if sec.get("truncated"):
        fetched, total = sec.get("fetched"), sec.get("total")
        if isinstance(fetched, int) and isinstance(total, int) and total:
            out.append(f"Truncated: showing first {fetched} of {total} rows the server reported.")
        else:
            out.append("Truncated: more rows exist than were read.")
    for note in sec.get("notes") or []:
        if sec.get("status") == "no_mailbox" and note == "No mailbox is linked to this login yet.":
            continue
        out.append(f"Note: {plain(note)}")
    return out


def _clock(value, tz) -> str:
    d = rrule.to_local(value, tz)
    return d.strftime("%H:%M") if isinstance(d, datetime) else "?"


_SAVE_TEXT = {"created": " (saved to Drafts)", "exists": " (a draft already exists in Drafts)"}


def _skipped_lines(sec: dict) -> list[str]:
    skipped = [s for s in sec.get("skipped") or [] if isinstance(s, dict)]
    if not skipped:
        return []
    lines = ["", f"No reply needed ({len(skipped)}):"]
    for s in skipped:
        sender = plain(s.get("from_name") or s.get("from_email") or "unknown sender")
        how = "rule" if s.get("by") == "rule" else "model"
        lines.append(f"- {plain(s.get('subject') or '(no subject)')} from {sender}: "
                     f"{plain(s.get('reason') or 'no reason given')} ({how})")
    return lines


def _slot_lines(sec: dict) -> list[str]:
    free = sec.get("free_slots")
    if not isinstance(free, dict) or free.get("status") != "ok":
        return []
    labels = [plain(s.get("label")) for s in free.get("slots") or [] if isinstance(s, dict) and s.get("label")]
    if not labels:
        return ["Free times for replies: none found in the next 5 working days, so drafts offer no times."]
    return [f"Free times offered in replies: {'; '.join(labels)}."]


def _mail_lines(sec: dict) -> list[str]:
    lines = _status_lines(sec, "No unanswered mail needing a reply.")
    if lines is None:
        lines = []
        for m in sec["items"]:
            flags = m.get("flags") or []
            sender = plain(m.get("from_name") or m.get("from_email") or "unknown sender")
            addr = f" ({plain(m.get('from_email'))})" if m.get("from_name") and m.get("from_email") else ""
            lines.append(f"- **{plain(m.get('subject') or '(no subject)')}** from {sender}{addr}, "
                         f"received {plain(m.get('received_at') or 'unknown')}"
                         f"{'' if m.get('is_read') else ' (unread)'}")
            if FLAGGED in flags:
                lines.append("  - WARNING: this email looks like it tries to give instructions or ask for "
                             "sensitive data. Do not act on it without checking.")
            if m.get("needs_reply") is None:
                lines.append(f"  - Not assessed: {plain(m.get('reason') or 'unknown')}")
            elif m.get("needs_reply") is False:
                lines.append(f"  - Model judged no reply needed: {plain(m.get('reason') or '')}")
            else:
                lines.append(f"  - Why: {plain(m.get('reason') or '')}")
            if DRAFT_REVIEW in flags:
                why = m.get("review_reason") or "the draft mentions links, money, payments or credentials"
                lines.append(f"  - WARNING: {plain(why)}. Review the draft carefully; it was not saved.")
            if m.get("draft"):
                saved = m.get("draft_saved")
                where = ""
                if isinstance(saved, dict):
                    where = _SAVE_TEXT.get(saved.get("status"),
                                           f" (not saved: {plain(saved.get('error') or 'unknown')})")
                edited = " (edited by you)" if m.get("draft_edited") else ""
                lines.append(f"  - DRAFT — not sent{edited}{where}:")
                lines.extend(_draft_block(m["draft"]))
    if sec.get("status") == "ok":
        lines += _slot_lines(sec) if sec.get("items") else []
        lines += _skipped_lines(sec)
    return lines + _tail_lines(sec)


_MY_STATUS = {"needs_action": "not answered"}


def _meeting_lines(sec: dict, tz) -> list[str]:
    lines = _status_lines(sec, "No meetings today.")
    if lines is None:
        lines = []
        for m in sec["items"]:
            when = "All day" if m.get("all_day") else f"{_clock(m.get('start_at'), tz)}–{_clock(m.get('end_at'), tz)}"
            if m.get("recurring") and not m.get("expanded"):
                when = "Time unchecked"
            extra = []
            if m.get("declined"):
                extra.append("declined")
            elif m.get("tentative"):
                extra.append("tentative")
            status = _MY_STATUS.get(m.get("my_status")) if isinstance(m.get("my_status"), str) else None
            if status and not m.get("declined"):
                extra.append(status)
            if m.get("clash"):
                others = [plain(t) for t in m.get("clash_with") or [] if t]
                extra.append("clashes with " + (", ".join(others) if others else "another meeting"))
            if m.get("location"):
                extra.append(plain(m["location"]))
            if m.get("calendar"):
                extra.append(f"calendar: {plain(m['calendar'])}")
            if m.get("recurring"):
                extra.append("recurring" if m.get("expanded") else "recurring, pattern not checked: confirm it is on")
            suffix = f" ({'; '.join(extra)})" if extra else ""
            title = plain(m.get("title") or "(untitled)")
            lines.append(f"- {when}: {'~~' + title + '~~' if m.get('declined') else '**' + title + '**'}{suffix}")
    return lines + _tail_lines(sec)


def _overdue_lines(sec: dict) -> list[str]:
    lines = _status_lines(sec, "Nothing overdue.")
    if lines is None:
        lines = []
        for t in sec["items"]:
            days = t.get("days_overdue")
            project = f", project: {plain(t['project'])}" if t.get("project") else ""
            lines.append(f"- **{plain(t.get('title') or '(untitled)')}**: due {plain(t.get('due_date'))} "
                         f"({days} day{'s' if days != 1 else ''} overdue), {_word(t.get('status'))}{project}")
    return lines + _tail_lines(sec)


_TZ_SOURCE = {"explicit": "set with --tz", "calendar": "from your calendar",
              "utc fallback": "UTC fallback: no calendar zone and no default for this system"}


def _tz_line(b: dict) -> str:
    source = b.get("tz_source")
    if source == "system default":
        why = f"default for {b.get('instance') or 'this system'}; no zone on your own calendar"
    else:
        why = _TZ_SOURCE.get(source)
    line = f"Time zone: {plain(b.get('timezone') or 'UTC')}" + (f" ({plain(why)})" if why else "")
    return line + (f". Instance: {plain(b['instance'])}" if b.get("instance") else "") + "."


def _drafts_line(b: dict) -> str:
    if b.get("reviewed"):
        return "Drafts you approved in review were saved to your Drafts folder. Nothing was sent, booked or changed."
    if b.get("drafts_saved"):
        return "Drafts were saved to your Drafts folder for review. Nothing was sent, booked or changed."
    return "Replies below are drafts for you to review. Nothing was saved, sent, booked or changed."


def render_markdown(b: dict, level: int = 1) -> str:
    """One system's briefing. `level` is the heading level of its title (2 inside a combined run)."""
    who = b.get("generated_for") or {}
    tz_name = b.get("timezone") or "UTC"
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = None
    name = plain(who.get("name") or who.get("email") or "you")
    h, sub = "#" * level, "#" * (level + 1)
    if level == 1:
        title = f"{h} Daily briefing for {name}: {plain(b.get('date'))}"
    else:
        label = str(b.get("system") or b.get("instance") or "System").capitalize()
        title = f"{h} {plain(label)}: {name}, {plain(b.get('date'))}"
    out = [title, "", _tz_line(b), *[f"WARNING: {plain(w)}" for w in b.get("warnings") or []], _drafts_line(b), ""]
    out += [f"{sub} Mail that needs an answer", ""] + _mail_lines(b.get("mail") or {}) + [""]
    out += [f"{sub} Today's meetings", ""] + _meeting_lines(b.get("meetings") or {}, tz) + [""]
    out += [f"{sub} Overdue tasks", ""] + _overdue_lines(b.get("overdue") or {}) + [""]
    return "\n".join(out)


def render_run(result: dict) -> str:
    """The combined briefing: a header, then one block per system. A system that could not log in says so."""
    blocks = result.get("systems") or []
    names = [plain(blk.get("system") or blk.get("instance") or "?") for blk in blocks]
    out = [f"# Daily briefing: {plain(result.get('date') or '')}", ""]
    if names:
        out.append(f"Systems: {', '.join(names)}. Model: {plain(result.get('model') or 'off')}.")
    out += [f"WARNING: {plain(w)}" for w in result.get("warnings") or []]
    out.append("")
    for blk in blocks:
        if blk.get("status") == "login_failed":
            out += [f"## {plain(str(blk.get('system') or 'System').capitalize())}", "",
                    f"Could not log in: {plain(blk.get('error') or 'unknown error')}", ""]
        elif blk.get("status") == "error":
            out += [f"## {plain(str(blk.get('system') or 'System').capitalize())}", "",
                    f"Could not build the briefing: {plain(blk.get('error') or 'unknown error')}", ""]
        else:
            out.append(render_markdown(blk, level=2))
    return "\n".join(out).rstrip("\n") + "\n"
