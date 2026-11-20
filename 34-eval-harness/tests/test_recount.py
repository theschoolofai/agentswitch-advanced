from __future__ import annotations

from typing import Any, cast

import pytest

from eval_harness.graders import Verdict
from eval_harness.recount import recount
from eval_harness.trial import TrialRecord


def _record(
    reported: dict[str, Any] | None,
    population: dict[str, Any] | None = None,
) -> TrialRecord:
    return cast(
        TrialRecord,
        type(
            "_Stub",
            (),
            {
                "agent": type("_Agent", (), {"reported": reported})(),
                "population": population if population is not None else {"dummy": True},
            },
        )(),
    )


def _answer(ids: list[str] | str, key: str = "orders_not_invoiced") -> dict[str, Any]:
    return {"claim": "done", "answer": {key: ids}}


def _install_rules(
    monkeypatch: pytest.MonkeyPatch,
    pair: tuple[set[str] | None, set[str] | None] | None,
) -> None:
    from eval_harness import rules as rules_mod

    monkeypatch.setattr(rules_mod, "expected_ids", lambda *a: pair)


def test_no_agent_result_revises(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_rules(monkeypatch, ({"A", "B"}, {"A", "B"}))
    r = recount(_record(None), {"answer": "orders_not_invoiced"})
    assert r.verdict is Verdict.REVISE


def test_empty_reported_revises(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_rules(monkeypatch, ({"A", "B"}, {"A", "B"}))
    r = recount(_record({}), {"answer": "orders_not_invoiced"})
    assert r.verdict is Verdict.REVISE


def test_clean_before_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_rules(monkeypatch, ({"A", "B"}, {"A"}))
    r = recount(_record(_answer(["A", "B"])), {"answer": "orders_not_invoiced"})
    assert r.verdict is Verdict.APPROVE


def test_clean_after_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_rules(monkeypatch, ({"A"}, {"A", "B"}))
    r = recount(_record(_answer(["A", "B"])), {"answer": "orders_not_invoiced"})
    assert r.verdict is Verdict.APPROVE


def test_empty_is_real_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_rules(monkeypatch, (set(), set()))
    r = recount(_record(_answer([])), {"answer": "orders_not_invoiced"})
    assert r.verdict is Verdict.APPROVE


def test_wrong_ids_revises(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_rules(monkeypatch, ({"A", "B"}, {"A", "B"}))
    r = recount(_record(_answer(["A"])), {"answer": "orders_not_invoiced"})
    assert r.verdict is Verdict.REVISE


def test_string_answer_revises(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_rules(monkeypatch, ({"A", "B"}, {"A", "B"}))
    r = recount(_record(_answer("AB")), {"answer": "orders_not_invoiced"})
    assert r.verdict is Verdict.REVISE


def test_no_population_unevaluated(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_rules(monkeypatch, None)
    r = recount(_record(_answer(["A"])), {"answer": "orders_not_invoiced"})
    assert r.verdict is Verdict.UNEVALUATED


def test_population_read_failed_unevaluated(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_rules(monkeypatch, (None, None))
    r = recount(_record(_answer(["A"])), {"answer": "orders_not_invoiced"})
    assert r.verdict is Verdict.UNEVALUATED


def test_one_side_read_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_rules(monkeypatch, (None, {"A", "B"}))
    r = recount(_record(_answer(["A", "B"])), {"answer": "orders_not_invoiced"})
    assert r.verdict is Verdict.APPROVE


def test_missing_answer_key_revises(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_rules(monkeypatch, ({"A"}, {"A"}))
    r = recount(_record(_answer(["A"], key="other_key")), {"answer": "orders_not_invoiced"})
    assert r.verdict is Verdict.REVISE


def test_no_answer_key_param_unevaluated(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_rules(monkeypatch, ({"A"}, {"A"}))
    r = recount(_record(_answer(["A"])), {})
    assert r.verdict is Verdict.UNEVALUATED
