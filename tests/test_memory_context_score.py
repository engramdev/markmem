"""
tests/test_memory_context_score.py — usage-based grading of memories.

grade() joins the access log x token cost x age and classes each memory: load-bearing
(used), fresh (too new to judge), dead-weight (old + never pulled + not indexed). These
tests pin the classification on a controlled tmp memory dir, plus a JSON-mode smoke run.
"""
from __future__ import annotations

import json
import os
import sys
import time


def _set_age(path, days):
    t = time.time() - days * 86400
    os.utime(path, (t, t))


def test_grade_classifies_by_usage_and_age(markmem_env, tmp_path, monkeypatch):
    from markmem.ops import memory_context_score as mcs

    mem = tmp_path / "mem"
    (mem / "metrics").mkdir(parents=True)
    (mem / "feedback_used.md").write_text("x" * 1000, encoding="utf-8")
    (mem / "feedback_dead.md").write_text("y" * 1000, encoding="utf-8")
    (mem / "feedback_fresh.md").write_text("z" * 1000, encoding="utf-8")
    _set_age(mem / "feedback_used.md", 40)   # old, but rescued by access count
    _set_age(mem / "feedback_dead.md", 40)   # old, never pulled, not indexed -> dead-weight
    _set_age(mem / "feedback_fresh.md", 1)   # too new to judge -> fresh

    alog = mem / "metrics" / "access_log.jsonl"
    alog.write_text(
        "\n".join(json.dumps({"file": "feedback_used.md", "ts": "2026-01-01T00:00:00+00:00"})
                  for _ in range(3)),
        encoding="utf-8")

    monkeypatch.setattr(mcs, "MEM", mem)
    monkeypatch.setattr(mcs, "ACCESS_LOG", alog)

    cls = {r["file"]: r["class"] for r in mcs.grade()}
    assert cls["feedback_used.md"] == "load-bearing"
    assert cls["feedback_dead.md"] == "dead-weight"
    assert cls["feedback_fresh.md"] == "fresh"


def test_grade_fail_open_without_access_log(markmem_env, tmp_path, monkeypatch):
    from markmem.ops import memory_context_score as mcs

    mem = tmp_path / "mem"
    mem.mkdir()
    (mem / "feedback_x.md").write_text("content", encoding="utf-8")
    monkeypatch.setattr(mcs, "MEM", mem)
    monkeypatch.setattr(mcs, "ACCESS_LOG", mem / "metrics" / "access_log.jsonl")  # absent

    rows = mcs.grade()  # must not raise
    assert len(rows) == 1 and rows[0]["accesses"] == 0


def test_main_json_runs(markmem_env, monkeypatch, capsys):
    from markmem.ops import memory_context_score as mcs

    monkeypatch.setattr(sys, "argv", ["memory-context-score", "--json"])
    assert mcs.main() == 0
    out = json.loads(capsys.readouterr().out)
    assert "summary" in out and "classes" in out["summary"]
