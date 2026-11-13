"""--review (D2): the terminal loop, with input, output and editor injected."""

from ea_briefing import review

ORIGINAL = {"id": "m1", "subject": "Lunch?", "body_text": "Are you free on Thursday?", "from_email": "a@x.test"}
ITEM = {"id": "m1", "subject": "Lunch?", "from_name": "Ana", "draft": "Hi Ana,\n\nThursday works.\n\nNora"}
SLOTS = [{"start": "2026-11-11T10:00:00+05:30", "end": "2026-11-11T10:30:00+05:30",
          "label": "Wed 11 Nov, 10:00–10:30 IST"}]


def reviewer(answers, editor=None, environ=None):
    answers = list(answers)
    shown = []
    prompts = []

    def input_fn(prompt=""):
        prompts.append(prompt)
        if not answers:
            raise EOFError
        return answers.pop(0)

    r = review.Reviewer(input_fn=input_fn, print_fn=shown.append, editor_fn=editor,
                        environ=environ if environ is not None else {})
    return r, shown, prompts


def test_save_returns_original_text():
    r, shown, prompts = reviewer(["s"])
    assert r(ITEM, ORIGINAL, SLOTS) == ("save", ITEM["draft"])
    assert review.PROMPT in prompts
    assert any("Thursday works." in line for line in shown)


def test_skip_and_reprompt_on_bad_answer():
    r, shown, _ = reviewer(["x", "k"])
    assert r(ITEM, ORIGINAL, SLOTS) == ("skip", "skipped in review")
    assert any("Please answer" in line for line in shown)


def test_quit_stops_all_later_drafts():
    r, _, prompts = reviewer(["q"])
    assert r(ITEM, ORIGINAL, SLOTS) == ("quit", None)
    n = len(prompts)
    assert r(ITEM, ORIGINAL, SLOTS) == ("quit", None)
    assert len(prompts) == n  # not asked again


def test_eof_means_quit():
    r, _, _ = reviewer([])
    assert r(ITEM, ORIGINAL, SLOTS) == ("quit", None)


def test_clean_edit_is_saved():
    r, _, _ = reviewer(["e"], editor=lambda text: "Hi Ana,\n\nWed 11 Nov, 10:00–10:30 IST suits me.\n\nNora\n")
    action, text = r(ITEM, ORIGINAL, SLOTS)
    assert action == "save" and text.endswith("Nora")


def test_edit_with_link_is_not_saved_and_says_why():
    r, shown, _ = reviewer(["e"], editor=lambda text: "See https://evil.test/pay")
    action, why = r(ITEM, ORIGINAL, SLOTS)
    assert action == "skip" and "link" in why
    assert any(line.startswith("Not saved:") for line in shown)


def test_edit_with_time_not_from_calendar_is_not_saved():
    r, shown, _ = reviewer(["e"], editor=lambda text: "How about 16:45 on Friday?")
    action, why = r(ITEM, ORIGINAL, SLOTS)
    assert action == "skip"
    assert "time not from your calendar" in why and "16:45" in why


def test_typed_editor_fallback_without_editor_env():
    r, _, _ = reviewer(["e", "Hi Ana,", "", "Thanks, see you then.", "Nora", "."])
    action, text = r(ITEM, ORIGINAL, SLOTS)
    assert action == "save"
    assert text == "Hi Ana,\n\nThanks, see you then.\nNora"


def test_empty_edit_skips():
    r, _, _ = reviewer(["e", "."])
    assert r(ITEM, ORIGINAL, SLOTS)[0] == "skip"


def test_external_editor_used_when_editor_set(monkeypatch):
    seen = {}

    def fake_external(command, text):
        seen["command"], seen["text"] = command, text
        return "Hi Ana,\n\nEdited.\n\nNora"

    monkeypatch.setattr(review, "external_editor", fake_external)
    r, _, _ = reviewer(["e"], environ={"EDITOR": "nano -w"})
    assert r(ITEM, ORIGINAL, SLOTS) == ("save", "Hi Ana,\n\nEdited.\n\nNora")
    assert seen == {"command": "nano -w", "text": ITEM["draft"]}


def test_terminal_escape_sequences_stripped_from_display():
    r, shown, _ = reviewer(["k"])
    r({**ITEM, "subject": "Hi\x1b]0;pwn\x07", "draft": "a\x1b[2Jb"}, ORIGINAL, SLOTS)
    assert all("\x1b" not in line and "\x07" not in line for line in shown)
