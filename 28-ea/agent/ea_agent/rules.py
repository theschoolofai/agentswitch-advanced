"""Deterministic "no reply needed" rules, applied before the model so obvious machine mail never costs a model call.

A rule only ever hides mail, so each one needs positive evidence; anything odd or missing means "not skipped" and the
message goes to the model as before. Mail that trips the injection scan is never skipped here: a sender who can set
headers could otherwise dress a phishing mail up as a newsletter and keep it out of the briefing.
"""
import re
from email.utils import parseaddr

from .drafts import SCANNED_FIELDS, injection_flags, normalise

SENT_BY_YOU = "sent by you"
NO_REPLY = "no-reply sender"
NEWSLETTER = "newsletter"
AUTOMATED = "automated notification"

# Matched against the local part only (so "alice@noreply.example" is a person), as a whole token: the start or end of
# the local part or one of . _ + - on each side, so "noreply-billing", "billing.noreply" and "no-reply+bounce" match
# but "postmasterson" and "bouncer" do not. "_" and "." are accepted between words as well as "-" because senders
# write "do_not_reply" and "no.reply" as often as the hyphenated forms. The list stays this narrow on purpose: a rule
# hit hides the mail from the briefing, so a looser match ("info@", "notifications@", "support@") would hide mail a
# person may need to answer; anything not caught here still goes to the model.
_SEP = r"[._-]?"
NO_REPLY_LOCAL = re.compile(
    rf"(?:^|[._+-])(?:no{_SEP}reply|do{_SEP}not{_SEP}reply|mailer{_SEP}daemon|postmaster|bounces?)(?:$|[._+-])", re.I)
NEWSLETTER_CATEGORIES = {"news", "promotions", "newsletter"}
BULK_PRECEDENCE = {"bulk", "list", "junk"}

_FOLD = re.compile(r"\r?\n[ \t]+")
_HEADER = re.compile(r"^([!-9;-~]+)[ \t]*:(.*)$")  # RFC 5322 field name: printable ASCII except ":"
_COMMENT = re.compile(r"\([^()]*\)")


def _address(value) -> str:
    if not isinstance(value, str):
        return ""
    value = normalise(value).strip()
    if "<" in value:
        value = parseaddr(value)[1]
    return value.strip().lower()


def _local_part(address: str) -> str:
    return address.rsplit("@", 1)[0] if "@" in address else ""


def _is_set(value) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    return value is not None and value is not False


def _is_id(value) -> bool:
    """A real campaign id: a non-empty string or a non-zero number (0 and False are how unset ids often arrive)."""
    if isinstance(value, str):
        return bool(value.strip())
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value != 0


def headers(raw) -> dict[str, list[str]]:
    """Header fields of a raw header block, names lower-cased, folded lines joined, every occurrence kept. Stops at the
    first blank line so a body that slipped into the block cannot add headers. Anything that is not a string is no
    headers at all."""
    out: dict[str, list[str]] = {}
    if not isinstance(raw, str):
        return out
    for line in _FOLD.sub(" ", raw.replace("\r\n", "\n").replace("\r", "\n")).split("\n"):
        if not line.strip():
            if out:
                break
            continue
        m = _HEADER.match(line)
        if m:
            out.setdefault(m.group(1).lower(), []).append(m.group(2).strip())
    return out


def _token(value: str) -> str:
    """The keyword of a structured header value: comments and parameters dropped, lower-cased."""
    return _COMMENT.sub(" ", value).split(";", 1)[0].strip().lower()


def _automated(raw) -> bool:
    fields = headers(raw)
    # An empty Auto-Submitted is malformed rather than a claim of automation, so it does not count.
    if any(_token(v) not in ("", "no") for v in fields.get("auto-submitted", [])):
        return True
    return any(_token(v) in BULK_PRECEDENCE for v in fields.get("precedence", []))


def _rule(message: dict, own: set[str]) -> str | None:
    sender = _address(message.get("from_email"))
    if sender and sender in own:
        return SENT_BY_YOU
    if NO_REPLY_LOCAL.search(_local_part(sender)):
        return NO_REPLY
    category = message.get("split_category")
    if _is_set(message.get("list_unsubscribe")) or _is_id(message.get("campaign_recipient_id")) or \
            (isinstance(category, str) and category.strip().lower() in NEWSLETTER_CATEGORIES):
        return NEWSLETTER
    if _automated(message.get("raw_headers")):
        return AUTOMATED
    return None


def skip_reason(message: dict, own_addresses: set[str]) -> str | None:
    """Why this mail needs no reply, or None to let the model decide. First matching rule wins. Never raises."""
    try:
        if not isinstance(message, dict):
            return None
        reason = _rule(message, {_address(a) for a in own_addresses or () if _address(a)})
        if reason is None:
            return None
        scanned = "\n".join(str(message.get(k) or "") for k in SCANNED_FIELDS)
        return None if injection_flags(scanned) else reason
    except Exception:  # a rule that cannot decide must not hide mail
        return None
