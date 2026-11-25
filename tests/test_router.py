from datetime import date

import pytest

from campus_assistant import router
from conftest import MONDAY_0940


@pytest.mark.parametrize("q", ["What is my next class?", "kal kaunsi classes hai?", "aaj ki classes",
                               "show my timetable", "free slots on wednesday", "any clashes?",
                               "Thursday lab", "आज क्लास", "when is the OS lecture"])
def test_timetable_questions(q):
    assert router.is_timetable_question(q)


@pytest.mark.parametrize("q", ["Library timings on Saturday?", "What is BCNF?", "revaluation fee",
                               "hostel gate closing time", "placement eligibility"])
def test_not_timetable(q):
    assert not router.is_timetable_question(q)


@pytest.mark.parametrize("q,expected", [
    ("tomorrow", date(2026, 11, 24)), ("kal ki class", date(2026, 11, 24)), ("today", date(2026, 11, 23)),
    ("aaj", date(2026, 11, 23)), ("parso", date(2026, 11, 25)), ("on friday", date(2026, 11, 27)),
    ("monday classes", date(2026, 11, 23)), ("sunday", date(2026, 11, 29)), ("next class", None)])
def test_target_day(q, expected):
    assert router.target_day(q, MONDAY_0940) == expected


@pytest.mark.parametrize("q,intent", [("free slots", "free"), ("khali time", "free"), ("clashes", "clashes"),
                                      ("week timetable", "week"), ("next class", "next"),
                                      ("agla lecture", "next"), ("tuesday classes", "day")])
def test_timetable_intent(q, intent):
    assert router.timetable_intent(q) == intent


def test_notes_question():
    assert router.is_notes_question("summarise my DBMS notes")
    assert not router.is_notes_question("hostel gate time")


def test_asks_when():
    assert router.asks_when("OS kab hai")
    assert router.asks_when("where is the lab")
    assert not router.asks_when("what is BCNF")
