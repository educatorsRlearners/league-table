"""Ranking gaps use the same rounded scores as rank grouping."""

from app.scoring import gap_to_below, gap_to_next, rank_rows


def _rows():
    # Raw scores differ by a float-dust amount that vanishes at 1-decimal
    # precision, so both students share a rank; a third sits clearly below.
    return rank_rows(
        [
            {"student_id": "a", "display_name": "A", "score": 90.04, "raw": 80,
             "normalisedByKey": {}},
            {"student_id": "b", "display_name": "B", "score": 90.0, "raw": 70,
             "normalisedByKey": {}},
            {"student_id": "c", "display_name": "C", "score": 85.0, "raw": 60,
             "normalisedByKey": {}},
        ],
        [],
    )


def test_tied_rows_share_rank():
    rows = _rows()
    assert rows[0]["rank"] == rows[1]["rank"] == 1
    assert rows[0]["tied"] and rows[1]["tied"]
    assert rows[2]["rank"] == 3


def test_gaps_use_rounded_scores():
    rows = _rows()
    # Displayed scores are 90.0, 90.0 and 85.0, so the gap to rank 3 is
    # exactly 5.0 — not the raw float-dust difference (5.04).
    assert gap_to_below(rows, 0) == 5.0
    assert gap_to_below(rows, 1) == 5.0
    assert gap_to_next(rows, 2) == 5.0
    # Tied for first: there is no rank above to reach.
    assert gap_to_next(rows, 1) is None
