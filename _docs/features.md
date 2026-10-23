# Features

What League Table does, in full. The [README](../README.md) summarizes it.

- **Podium and ranked list** with score bars, movement since last week and the points to the place above. Switch between a single week, a cumulative average and a rolling average, pick criteria, and re-weight them.
- **Fair to outside commitments:** reported weekly hours of work, child care and elder care are combined into weighted hours and multiply the score by a capped factor (by default one point per weighted hour, at most ×1.25). Scores stop at 100.
- **Explainable scores:** open a breakdown to see each criterion's contribution, the raw score, weighted hours, the factor, the adjusted score and a note when it was capped at 100. Everyone can read the formula and current numbers in the explainer.
- **Private:** classmates see only the final adjusted score and rank, never another student's hours, factor or raw score. Students can only open their own breakdown, commitments and standing.
- **Fair to missing data:** a criterion with no entry is left out and the remaining weights are rescaled, so absence of data is never scored as zero.
- **Ties:** students level on adjusted score are ordered by raw score, then the configured tie-breakers; any still level share a rank (1, 1, 3).
- **Privacy toggle:** show full names, initials or nicknames in one click.
- **Risk digest:** the instructor sees newly, still and cleared flags across every class they teach, each traced to five evidence-backed signals (downward trend, missed engagement, low projected grade, heavy commitments, missing data). Step through any week with the same control used on the league table; each week is always compared against the one before it.
- **Outreach notes:** log private, timestamped notes on a student's risk record. Notes never travel to a student.
- **Student standing:** each student sees only their own level, the signals that are on, and where to get help — no ranks, no classmates, no notes.
- **Server-side rules:** scoring, the adjustment, ranking, risk and roles all run on the backend.
