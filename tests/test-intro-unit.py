#!/usr/bin/env python3
"""Unit tests for the deterministic intro engine (Stage 5 intro rewrite).

These tests intentionally avoid FastAPI/DB and do not require any external services.
Run: python3 tests/test-intro-unit.py
"""

from __future__ import annotations

import os
import unittest
import importlib.util
from typing import Any, Dict, Tuple, Optional, cast


def _load_intro_engine():
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    path = os.path.join(repo_root, "api", "intro_engine.py")
    spec = importlib.util.spec_from_file_location("intro_engine", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load intro_engine")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[assignment]
    return mod


intro_engine = _load_intro_engine()

JsonDict = Dict[str, Any]


class IntroEngineTests(unittest.TestCase):
    def test_intro_stops_after_done_no_llm_call(self):
        called = {"n": 0}

        def llm_extract(field: str, user_text: str, bs: JsonDict, pq: str) -> Tuple[JsonDict, Optional[str], str]:
            called["n"] += 1
            raise AssertionError("llm_extract must not be called when ready_to_search=true")

        brief_state: JsonDict = {
            "ready_to_search": True,
            "intro": {"asked": 7, "current_field": "role_title"},
        }

        bs2, payload = intro_engine.intro_message(brief_state, "какой-то текст", "qa", llm_extract)

        self.assertEqual(called["n"], 0)
        self.assertTrue(bs2.get("ready_to_search"))
        self.assertEqual(payload.get("type"), "intro_done")

    def test_intro_max_10_questions_forces_done(self):
        # Drive the engine to ask 10 questions, then answer the 10th.
        bs: JsonDict = {}
        bs, payload = intro_engine.intro_start(bs)
        self.assertEqual(payload.get("type"), "intro_question")
        self.assertEqual(payload.get("progress", {}).get("asked"), 1)

        def llm_extract(field: str, user_text: str, bs_local: JsonDict, pq: str):
            # Always return a patch to fill the current field.
            return {field: f"value_for_{field}"}, None, "free_text"

        # We need to produce questions up to asked==10 (each intro_message returns next question).
        for i in range(1, intro_engine.MAX_INTRO_QUESTIONS):
            bs, payload = intro_engine.intro_message(bs, f"answer_{i}", "qa", llm_extract)
            self.assertIn(payload.get("type"), {"intro_question", "intro_done"})
            if payload.get("type") == "intro_done":
                break

        # At this point, engine should have asked MAX questions or finished earlier.
        intro = bs.get("intro")
        intro_dict: Dict[str, Any] = cast(Dict[str, Any], intro) if isinstance(intro, dict) else {}
        asked_raw: Any = intro_dict.get("asked", 0)
        asked = int(asked_raw) if isinstance(asked_raw, (int, float, str)) else 0
        self.assertLessEqual(asked, intro_engine.MAX_INTRO_QUESTIONS)

        # If not done yet, answer once more and assert forced done.
        if not bs.get("ready_to_search"):
            bs, payload = intro_engine.intro_message(bs, "final_answer", "qa", llm_extract)

        self.assertTrue(bs.get("ready_to_search"))
        self.assertEqual(payload.get("type"), "intro_done")

    def test_llm_extract_merges_patch_into_brief_state(self):
        called = {"n": 0}

        def llm_extract(field: str, user_text: str, bs_local: JsonDict, pq: str):
            called["n"] += 1
            if field == "salary_range":
                # Return a nested patch to ensure deep merge.
                return {"salary_range": {"max": 300000}}, None, "free_text"
            return {field: "CFO"}, None, "free_text"

        bs: JsonDict = {
            "salary_range": {"min": 200000},
            "intro": {"asked": 1, "current_field": "salary_range"},
        }

        bs2, payload = intro_engine.intro_message(bs, "300к", "finance", llm_extract)

        self.assertGreaterEqual(called["n"], 1)
        self.assertIsInstance(bs2.get("salary_range"), dict)
        self.assertEqual(bs2["salary_range"].get("min"), 200000)
        self.assertEqual(bs2["salary_range"].get("max"), 300000)
        self.assertIn(payload.get("type"), {"intro_question", "intro_done"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
