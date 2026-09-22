// The risk engine. Pure functions over normalised weekly data — no I/O, no
// adapter detail. Each signal is on or off against an instructor-set threshold,
// and the level is the count of signals on. Nothing here is a blended number
// anyone has to interpret, and every signal carries the data that triggered it.

export const SIGNAL_KEYS = [
  'downward_trend',
  'missed_engagement',
  'low_projected_grade',
  'heavy_commitments',
  'missing_data',
];

export const SIGNAL_LABELS = {
  downward_trend: 'Downward trend',
  missed_engagement: 'Missed or low engagement',
  low_projected_grade: 'Low projected grade',
  heavy_commitments: 'Heavy outside commitments',
  missing_data: 'Missing data',
};

export const DEFAULT_THRESHOLDS = {
  declineWeeks: 3,
  missedAssignments: 2,
  attendancePct: 70,
  participationPct: 50,
  projectedGrade: 60,
  commitmentHours: 20,
  missingWeeks: 2,
};

export const DEFAULT_ACTIVE = Object.fromEntries(SIGNAL_KEYS.map((k) => [k, true]));

export const LEVELS = ['Not flagged', 'Watch', 'At risk', 'High risk'];

/** A student's level is the count of distinct signals currently on. */
export function levelFor(count) {
  return count >= 3 ? 'High risk' : LEVELS[count] || 'Not flagged';
}

const pct = (earned, possible) => (possible > 0 ? (100 * earned) / possible : null);
const round1 = (n) => (n == null ? null : Math.round(n * 10) / 10);

/** How many weeks in a row the raw score fell, counting back from the latest. */
function declineRun(weekly) {
  const scored = weekly.filter((w) => w.raw != null);
  let run = 0;
  for (let i = scored.length - 1; i > 0; i--) {
    if (scored[i].raw < scored[i - 1].raw - 1e-9) run += 1;
    else break;
  }
  return run;
}

/** The longest run of consecutive weeks with no entries at all. */
function missingRun(weekly) {
  let best = 0;
  let run = 0;
  for (const w of weekly) {
    if (w.hasEntries) run = 0;
    else {
      run += 1;
      if (run > best) best = run;
    }
  }
  return best;
}

/** Weeks where an assignment was set but nothing was handed in. */
function missedAssignments(weekly) {
  return weekly.filter((w) => {
    const slot = w.byKey && w.byKey.homework;
    return slot && slot.possible > 0 && slot.earned === 0;
  }).length;
}

function weeksSet(weekly) {
  return weekly.filter((w) => w.byKey && w.byKey.homework && w.byKey.homework.possible > 0).length;
}

function totalsFor(weekly, key) {
  let earned = 0;
  let possible = 0;
  for (const w of weekly) {
    const slot = w.byKey && w.byKey[key];
    if (!slot) continue;
    earned += slot.earned;
    possible += slot.possible;
  }
  return { earned, possible };
}

/**
 * Evaluate the five signals for one student up to and including a week.
 *
 * weekly: [{ week_number, raw, hasEntries, byKey: { [criterionKey]: {earned, possible} } }]
 *         — already limited to weeks the student was enrolled for.
 * hours:  weighted commitment hours in the week being evaluated.
 */
export function evaluateSignals({ weekly, hours = 0, thresholds = DEFAULT_THRESHOLDS, active = DEFAULT_ACTIVE }) {
  const t = { ...DEFAULT_THRESHOLDS, ...thresholds };
  const scored = weekly.filter((w) => w.raw != null);

  const run = declineRun(weekly);
  const missed = missedAssignments(weekly);
  const setCount = weeksSet(weekly);
  const attendance = totalsFor(weekly, 'attendance');
  const attendancePct = pct(attendance.earned, attendance.possible);
  const participation = totalsFor(weekly, 'participation');
  const participationPct = pct(participation.earned, participation.possible);
  const projected = scored.length ? scored.reduce((a, w) => a + w.raw, 0) / scored.length : null;
  const gap = missingRun(weekly);

  const reasons = [
    attendancePct != null && attendancePct < t.attendancePct
      ? `attendance ${round1(attendancePct)}% is under ${t.attendancePct}%` : null,
    missed >= t.missedAssignments ? `${missed} assignments not handed in` : null,
    participationPct != null && participationPct < t.participationPct
      ? `participation ${round1(participationPct)}% is under ${t.participationPct}%` : null,
  ].filter(Boolean);

  const definitions = {
    downward_trend: {
      on: run >= t.declineWeeks,
      summary: run >= t.declineWeeks
        ? `The weighted score has fallen ${run} weeks running.`
        : `The score has fallen ${run} week${run === 1 ? '' : 's'} running; the threshold is ${t.declineWeeks}.`,
      evidence: scored.slice(-6).map((w) => ({ label: `Week ${w.week_number}`, value: String(round1(w.raw)) })),
    },
    missed_engagement: {
      on: reasons.length > 0,
      summary: reasons.length ? `Triggered by ${reasons.join('; ')}.` : 'Attendance, homework and participation are all above their thresholds.',
      evidence: [
        { label: 'Assignments not handed in', value: `${missed} of ${setCount}` },
        { label: 'Attendance to date', value: attendancePct == null ? '—' : `${round1(attendancePct)}%` },
        { label: 'Participation to date', value: participationPct == null ? '—' : `${round1(participationPct)}%` },
      ],
    },
    low_projected_grade: {
      on: projected != null && projected < t.projectedGrade,
      summary: projected == null
        ? 'No scores yet, so no projection.'
        : `The score to date averages ${round1(projected)}, against a pass threshold of ${t.projectedGrade}.`,
      evidence: [
        { label: 'Weeks counted', value: String(scored.length) },
        { label: 'Projected grade', value: projected == null ? '—' : String(round1(projected)) },
        { label: 'Pass threshold', value: String(t.projectedGrade) },
      ],
    },
    heavy_commitments: {
      on: hours >= t.commitmentHours,
      summary: hours >= t.commitmentHours
        ? `${round1(hours)} weighted hours of work and care a week, at or above the ${t.commitmentHours}-hour threshold.`
        : `${round1(hours)} weighted hours a week, under the ${t.commitmentHours}-hour threshold.`,
      evidence: [
        { label: 'Weighted hours this week', value: String(round1(hours)) },
        { label: 'Threshold', value: `${t.commitmentHours} hours` },
      ],
    },
    missing_data: {
      on: gap >= t.missingWeeks,
      summary: gap >= t.missingWeeks
        ? `${gap} consecutive weeks with no entries at all.`
        : `The longest gap is ${gap} week${gap === 1 ? '' : 's'}; the threshold is ${t.missingWeeks}.`,
      evidence: weekly.slice(-6).map((w) => ({ label: `Week ${w.week_number}`, value: w.hasEntries ? 'recorded' : 'no entries' })),
    },
  };

  const signals = SIGNAL_KEYS.map((key) => ({
    key,
    label: SIGNAL_LABELS[key],
    active: active[key] !== false,
    on: active[key] !== false && definitions[key].on,
    summary: definitions[key].summary,
    evidence: definitions[key].evidence,
  }));

  const on = signals.filter((s) => s.on);
  return {
    signals,
    signals_on: on.map((s) => s.key),
    level: levelFor(on.length),
    /** So a borderline student is visible rather than hidden by their level. */
    oneAway: on.length < 3 ? levelFor(on.length + 1) : null,
    metrics: {
      declineRun: run,
      missedAssignments: missed,
      attendancePct: round1(attendancePct),
      participationPct: round1(participationPct),
      projected: round1(projected),
      hours: round1(hours),
      missingRun: gap,
    },
  };
}

/** Compare two evaluations to say what changed since the instructor last looked. */
export function diffState(prior, current) {
  const was = prior ? prior.signals_on.length > 0 : false;
  const is = current.signals_on.length > 0;
  if (is && !was) return 'new';
  if (is && was) return 'still';
  if (!is && was) return 'cleared';
  return 'quiet';
}
