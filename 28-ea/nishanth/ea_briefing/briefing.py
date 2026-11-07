"""Assemble the three sections into one briefing and render it as Markdown."""
import re
from datetime import date, datetime

from . import collect, drafts, rrule


def _guard(fn, *args, **kw) -> dict:
    try:
        return fn(*args, **kw)
    except Exception as exc:
        return collect._error_section(exc)


FLAGGED = "possible_prompt_injection"
DRAFT_REVIEW = "draft_needs_review"


def _triage_one(client, me, msg: dict, llm, save_drafts: bool, mailbox_ids, cache: dict) -> dict:
    scanned = "\n".join(str(msg.get(k) or "") for k in drafts.SCANNED_FIELDS)
    try:
        item = {**msg, **drafts.triage(msg, me, llm)}
        flags = item.get("flags") or []
        if save_drafts and item.get("needs_reply") is True and item.get("draft"):
            if FLAGGED in flags:
                item["draft_saved"] = {"status": "skipped", "id": None, "error": "flagged message — review manually"}
            elif DRAFT_REVIEW in flags:
                item["draft_saved"] = {"status": "skipped", "id": None, "error": "draft needs review — not saved"}
            else:
                item["draft_saved"] = drafts.save_draft(client, me, msg, item["draft"], mailbox_ids=mailbox_ids,
                                                        cache=cache)
        return item
    except Exception as exc:  # one odd message becomes an item with an error, not a lost briefing
        detail = f"{type(exc).__name__}: {exc}"[:200]
        try:
            flags = [FLAGGED] if drafts.injection_flags(scanned) else []
        except Exception:
            flags = [FLAGGED]  # if even the scan fails, treat the message as suspect
        return {**msg, "needs_reply": None, "reason": f"could not assess: {detail}", "draft": None, "flags": flags,
                "error": detail}


def _triage_mail(client, me, mail: dict, llm, save_drafts: bool) -> dict:
    listed, skipped = [], 0
    cache: dict = {}  # one Drafts listing per run, shared by every message
    for msg in mail["items"]:
        item = _triage_one(client, me, msg, llm, save_drafts, mail.get("mailbox_ids"), cache)
        # A flagged message stays visible whatever the model said: the model may have been talked out of it.
        if item.get("needs_reply") is False and FLAGGED not in (item.get("flags") or []):
            skipped += 1
            continue
        listed.append(item)
    mail["items"] = listed
    mail["not_needing_reply"] = skipped
    return mail


def build_briefing(client, me, day: date, tz, llm=None, save_drafts: bool = False, mail_cap: int = 25) -> dict:
    me = me if isinstance(me, dict) else {}
    mail = _guard(collect.collect_mail, client, me, cap=mail_cap, day=day, tz=tz)
    if mail.get("status") == "ok":
        mail = _guard(_triage_mail, client, me, mail, llm, save_drafts)
    warnings = [w for w in [getattr(client, "tz_note", None)] if isinstance(w, str) and w]
    unassessed = [i for i in mail.get("items") or [] if i.get("error")]
    if llm is not None and unassessed:
        # a dead or misconfigured model leaves every item "Not assessed"; that must not pass as a clean run
        warnings.append(f"{len(unassessed)} of {len(mail['items'])} emails could not be assessed by the model")
    return {
        "generated_for": {"name": me.get("name"), "email": me.get("email")},
        "date": day.isoformat(),
        "timezone": getattr(tz, "key", None) or str(tz),
        "instance": getattr(client, "instance", None),
        "mail": mail,
        "meetings": _guard(collect.collect_meetings, client, me, day, tz),
        "overdue": _guard(collect.collect_overdue, client, me, day),
        "drafts_saved": bool(save_drafts),
        "warnings": warnings,
    }


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
                lines.append("  - WARNING: the draft mentions links, money, payments or credentials. "
                             "Review it carefully; it was not saved.")
            if m.get("draft"):
                saved = m.get("draft_saved")
                where = ""
                if isinstance(saved, dict):
                    where = _SAVE_TEXT.get(saved.get("status"),
                                           f" (not saved: {plain(saved.get('error') or 'unknown')})")
                lines.append(f"  - DRAFT — not sent{where}:")
                lines.extend(_draft_block(m["draft"]))
    skipped = sec.get("not_needing_reply")
    if sec.get("status") == "ok" and skipped:
        lines.append(f"{skipped} other message(s) do not need a reply.")
    return lines + _tail_lines(sec)


def _meeting_lines(sec: dict, tz) -> list[str]:
    lines = _status_lines(sec, "No meetings today.")
    if lines is None:
        lines = []
        for m in sec["items"]:
            when = "All day" if m.get("all_day") else f"{_clock(m.get('start_at'), tz)}–{_clock(m.get('end_at'), tz)}"
            if m.get("recurring") and not m.get("expanded"):
                when = "Time unchecked"
            extra = []
            if m.get("location"):
                extra.append(plain(m["location"]))
            if m.get("calendar"):
                extra.append(f"calendar: {plain(m['calendar'])}")
            if m.get("recurring"):
                extra.append("recurring" if m.get("expanded") else "recurring, pattern not checked: confirm it is on")
            suffix = f" ({'; '.join(extra)})" if extra else ""
            lines.append(f"- {when}: **{plain(m.get('title') or '(untitled)')}**{suffix}")
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


def render_markdown(b: dict) -> str:
    who = b.get("generated_for") or {}
    tz_name = b.get("timezone") or "UTC"
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = None
    name = plain(who.get("name") or who.get("email") or "you")
    out = [f"# Daily briefing for {name}: {plain(b.get('date'))}", "",
           f"Time zone: {plain(tz_name)}" + (f". Instance: {plain(b['instance'])}" if b.get("instance") else "") + ".",
           *[f"WARNING: {plain(w)}" for w in b.get("warnings") or []],
           ("Drafts were saved to your Drafts folder for review. Nothing was sent, booked or changed."
            if b.get("drafts_saved") else
            "Replies below are drafts for you to review. Nothing was saved, sent, booked or changed."), ""]
    out += ["## Mail that needs an answer", ""] + _mail_lines(b.get("mail") or {}) + [""]
    out += ["## Today's meetings", ""] + _meeting_lines(b.get("meetings") or {}, tz) + [""]
    out += ["## Overdue tasks", ""] + _overdue_lines(b.get("overdue") or {}) + [""]
    return "\n".join(out)
