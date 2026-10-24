"""
tests/test_correction_synapse.py — the silent-edit -> correction-candidate flow.

correction_synapse snapshots files the assistant wrote at session end, then on the next
scan detects any the user silently changed and emits a human-review candidate (never a
memory). These tests cover the watchability filter and the full capture -> edit -> scan
-> emit -> prune cycle, isolated under the temp memory dir (autouse markmem_env).
"""
from __future__ import annotations

import json


def test_is_watchable_filters_secrets_tmp_and_binaries(markmem_env):
    from markmem.learn import correction_synapse as cs

    assert cs._is_watchable("/home/u/project/notes.md")      # ordinary text file
    assert not cs._is_watchable("/home/u/.ssh/id_rsa")       # secret path
    assert not cs._is_watchable("/tmp/scratch.md")           # volatile dir
    assert not cs._is_watchable("/home/u/app/photo.png")     # non-text extension
    assert not cs._is_watchable("")                          # empty / unknown


def test_capture_then_user_edit_emits_candidate(markmem_env, tmp_path, monkeypatch):
    from markmem.learn import correction_synapse as cs

    # tmp_path lives under /tmp, which SKIP_SUBSTRINGS excludes; drop the filter so the
    # flow itself is what's under test (the filter has its own test above).
    monkeypatch.setattr(cs, "SKIP_SUBSTRINGS", ())

    f = tmp_path / "note.md"
    f.write_text("assistant version\nline two\n", encoding="utf-8")
    transcript = tmp_path / "t.jsonl"
    transcript.write_text(
        json.dumps({"message": {"content": [
            {"type": "tool_use", "name": "Write", "input": {"file_path": str(f)}}]}}) + "\n",
        encoding="utf-8")

    assert cs.capture(str(transcript), "sess1234abcd") == 1   # one file snapshotted
    assert cs.scan() == 0                                      # unchanged -> no candidate

    f.write_text("user corrected version\nline two\n", encoding="utf-8")  # silent edit
    assert cs.scan() == 1                                      # change detected
    body = cs.CORRECTIONS.read_text(encoding="utf-8")
    assert "note.md" in body and "user corrected version" in body
    assert cs.scan() == 0                                      # candidate pruned after emit


def test_capture_is_fail_open_on_missing_transcript(markmem_env):
    from markmem.learn import correction_synapse as cs

    assert cs.capture("/does/not/exist.jsonl", "s") == 0
    assert cs.capture("", "s") == 0
