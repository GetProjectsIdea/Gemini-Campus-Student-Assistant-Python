from datetime import date, datetime, time

import pytest

from campus_assistant.timetable import Slot, Timetable, TimetableError, norm_day, parse_time
from conftest import IST, MONDAY_0940

CSV = """day,start,end,course,code,type,room,faculty,short
Mon,09:00,10:00,Database Management Systems,CS301,Lecture,LT-2,Dr A,DBMS
Mon,14:00,17:00,DBMS Lab,CS351,Lab,Lab 3,Ms P,DBMS
Tuesday,9:00 AM,10:00 AM,Computer Networks,CS303,Lecture,LT-1,Dr N,CN
wed,11:00,12:00,Operating Systems,CS302,Tutorial,R210,Prof I,OS
"""


@pytest.fixture
def tt():
    return Timetable.from_csv_text(CSV)


def test_load_sample(sample_dir):
    t = Timetable.load(sample_dir / "timetable.csv")
    assert len(t.slots) == 20
    assert t.clashes() == []


@pytest.mark.parametrize("value,expected", [("Monday", "Mon"), ("mon", "Mon"), ("THU", "Thu"),
                                            ("somvar", "Mon"), ("शुक्रवार", "Fri"), ("Sun", "Sun")])
def test_norm_day(value, expected):
    assert norm_day(value) == expected


def test_norm_day_bad():
    with pytest.raises(TimetableError):
        norm_day("Funday")


@pytest.mark.parametrize("value,expected", [("09:00", time(9)), ("9:30", time(9, 30)), ("2:00 PM", time(14)),
                                            ("2 pm", time(14)), ("14.15", time(14, 15)), ("0930", time(9, 30))])
def test_parse_time(value, expected):
    assert parse_time(value) == expected


def test_parse_time_bad():
    with pytest.raises(TimetableError):
        parse_time("noonish")


def test_slots_sorted_by_day_and_time(tt):
    assert [s.day for s in tt.slots] == ["Mon", "Mon", "Tue", "Wed"]


def test_12h_times_parsed(tt):
    tue = tt.day("tue")[0]
    assert tue.start == time(9) and tue.end == time(10)


def test_missing_column():
    with pytest.raises(TimetableError, match="missing column"):
        Timetable.from_csv_text("day,start,course\nMon,09:00,X")


def test_end_before_start_reports_line():
    with pytest.raises(TimetableError, match="line 2"):
        Timetable.from_csv_text("day,start,end,course\nMon,10:00,09:00,X")


def test_bad_day_reports_line():
    with pytest.raises(TimetableError, match="line 3"):
        Timetable.from_csv_text("day,start,end,course\nMon,09:00,10:00,X\nXyz,09:00,10:00,Y")


def test_blank_rows_skipped():
    t = Timetable.from_csv_text("day,start,end,course\nMon,09:00,10:00,X\n,,,\n")
    assert len(t.slots) == 1


def test_empty_course_rejected():
    with pytest.raises(TimetableError, match="course is empty"):
        Timetable.from_csv_text("day,start,end,course\nMon,09:00,10:00,")


def test_empty_file():
    with pytest.raises(TimetableError):
        Timetable.from_csv_text("")


def test_file_not_found(tmp_path):
    with pytest.raises(TimetableError, match="not found"):
        Timetable.load(tmp_path / "nope.csv")


def test_bom_is_ok(tmp_path):
    p = tmp_path / "t.csv"
    p.write_text("\ufeff" + CSV, encoding="utf-8")
    assert len(Timetable.load(p).slots) == 4


def test_current_and_next(tt):
    assert tt.current(MONDAY_0940).code == "CS301"
    slot, start = tt.next_class(MONDAY_0940)
    assert slot.code == "CS351" and start.hour == 14


def test_next_class_rolls_to_next_day(tt):
    evening = datetime(2026, 11, 23, 18, 0, tzinfo=IST)
    slot, start = tt.next_class(evening)
    assert slot.day == "Tue" and start.date() == date(2026, 11, 24)


def test_next_class_wraps_week(tt):
    friday = datetime(2026, 11, 27, 12, 0, tzinfo=IST)
    slot, start = tt.next_class(friday)
    assert slot.day == "Mon" and start.date() == date(2026, 11, 30)


def test_next_class_empty_timetable():
    assert Timetable([]).next_class(MONDAY_0940) is None


def test_free_slots(tt):
    free = tt.free_slots("Mon")
    assert free == [(time(10), time(14))]


def test_free_slots_min_minutes(tt):
    assert tt.free_slots("Wed", min_minutes=150) == [(time(12), time(17))]
    assert (time(9), time(11)) in tt.free_slots("Wed")


def test_free_whole_day_when_no_classes(tt):
    assert tt.free_slots("Sat") == [(time(9), time(17))]


def test_clashes_detected():
    t = Timetable.from_csv_text("day,start,end,course\nMon,09:00,10:30,A\nMon,10:00,11:00,B\nMon,11:00,12:00,C")
    cl = t.clashes()
    assert len(cl) == 1 and {cl[0][0].course, cl[0][1].course} == {"A", "B"}


def test_back_to_back_is_not_a_clash(sample_dir):
    t = Timetable.from_csv_text("day,start,end,course\nMon,09:00,10:00,A\nMon,10:00,11:00,B")
    assert t.clashes() == []


def test_weekly_hours(tt):
    h = tt.weekly_hours()
    assert h["CS351"] == 3 and list(h)[0] == "CS351"


def test_aliases():
    s = Slot("Mon", time(9), time(10), "Computer Networks", "CS303", short="CN/Networks")
    assert {"computer", "network", "networks", "cs303", "cn", "cn"} <= s.aliases


def test_match_prefers_lab(tt):
    m = tt.match("when is the DBMS lab?")
    assert [s.code for s in m] == ["CS351"]


def test_match_lecture_by_initials(tt):
    assert [s.code for s in tt.match("OS kab hai")] == ["CS302"]


def test_match_none(tt):
    assert tt.match("library timings") == []


def test_render_day_and_week(tt):
    assert "no classes" in tt.render_day("Sun")
    week = tt.render_week()
    assert week.startswith("Mon:") and "Wed:" in week and "Sat" not in week


def test_label():
    s = Slot("Mon", time(9), time(10), "DBMS", "CS301", "Lecture", "LT-2", "Dr A")
    assert s.label() == "09:00-10:00 | DBMS (CS301) | Lecture | LT-2 | Dr A"
    assert s.minutes == 60


def test_ics_export(tt):
    ics = tt.to_ics(date(2026, 11, 25), weeks=2, stamp=datetime(2026, 11, 25, 8, 0))
    assert ics.startswith("BEGIN:VCALENDAR\r\n") and ics.endswith("END:VCALENDAR\r\n")
    assert ics.count("BEGIN:VEVENT") == 8
    assert "DTSTART;TZID=Asia/Kolkata:20261123T090000" in ics   # Monday of that week
    assert "DTSTART;TZID=Asia/Kolkata:20261130T090000" in ics   # second week
    assert "LOCATION:Lab 3" in ics


def test_ics_escapes_commas():
    t = Timetable.from_csv_text('day,start,end,course,room\nMon,09:00,10:00,"Maths, III","Block A; R1"')
    ics = t.to_ics(date(2026, 11, 23))
    assert "SUMMARY:Maths\\, III" in ics and "LOCATION:Block A\\; R1" in ics
