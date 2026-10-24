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

const HIGHEST_LEVEL_INDEX = LEVELS.length - 1;
const DECLINE_TOLERANCE = 1e-9;   // float slack so equal scores are not counted as a fall
const TREND_WEEKS_SHOWN = 6;

/** A student's level is the count of distinct signals currently on, topping out at the highest level. */
export function levelFor(count) {
  return LEVELS[Math.min(count, HIGHEST_LEVEL_INDEX)] || 'Not flagged';
}

const pct = (earned, possible) => (possible > 0 ? (100 * earned) / possible : null);
const round1 = (n) => (n == null ? null : Math.round(n * 10) / 10);

/** How many weeks in a row the raw score fell, counting back from the latest. */
function declineRun(weekly) {
  const scored = weekly.filter((w) => w.raw != null);
  let run = 0;
  for (let i = scored.length - 1; i > 0; i--) {
    if (scored[i].raw < scored[i - 1].raw - DECLINE_TOLERANCE) run += 1;
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

/** The week's homework totals when an assignment was set that week, else null. */
const homeworkSet = (w) => (w.byKey?.homework?.possible > 0 ? w.byKey.homework : null);

/** Weeks where an assignment was set but nothing was handed in. */
function missedAssignments(weekly) {
  return weekly.filter((w) => homeworkSet(w)?.earned === 0).length;
}

function weeksSet(weekly) {
  return weekly.filter((w) => homeworkSet(w)).length;
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

/** Instructor-readable reasons the engagement signal fired. */
function engagementReasons({ missed, attendancePct, participationPct }, t) {
  return [
    attendancePct != null && attendancePct < t.attendancePct
      ? `attendance ${round1(attendancePct)}% is under ${t.attendancePct}%` : null,
    missed >= t.missedAssignments ? `${missed} assignments not handed in` : null,
    participationPct != null && participationPct < t.participationPct
      ? `participation ${round1(participationPct)}% is under ${t.participationPct}%` : null,
  ].filter(Boolean);
}

const percentLabel = (value) => (value == null ? '—' : `${round1(value)}%`);
const plural = (n, word) => `${n} ${word}${n === 1 ? '' : 's'}`;

/** Each signal: is it on, a plain-language summary, and the data behind it. */
const SIGNAL_DEFINITIONS = {
  downward_trend(m, t) {
    const on = m.run >= t.declineWeeks;
    return {
      on,
      summary: on
        ? `The weighted score has fallen ${m.run} weeks running.`
        : `The score has fallen ${plural(m.run, 'week')} running; the threshold is ${t.declineWeeks}.`,
      evidence: m.scored.slice(-TREND_WEEKS_SHOWN).map((w) => ({ label: `Week ${w.week_number}`, value: String(round1(w.raw)) })),
    };
  },

  missed_engagement(m, t) {
    const reasons = engagementReasons(m, t);
    return {
      on: reasons.length > 0,
      summary: reasons.length ? `Triggered by ${reasons.join('; ')}.` : 'Attendance, homework and participation are all above their thresholds.',
      evidence: [
        { label: 'Assignments not handed in', value: `${m.missed} of ${m.setCount}` },
        { label: 'Attendance to date', value: percentLabel(m.attendancePct) },
        { label: 'Participation to date', value: percentLabel(m.participationPct) },
      ],
    };
  },

  low_projected_grade(m, t) {
    return {
      on: m.projected != null && m.projected < t.projectedGrade,
      summary: m.projected == null
        ? 'No scores yet, so no projection.'
        : `The score to date averages ${round1(m.projected)}, against a pass threshold of ${t.projectedGrade}.`,
      evidence: [
        { label: 'Weeks counted', value: String(m.scored.length) },
        { label: 'Projected grade', value: m.projected == null ? '—' : String(round1(m.projected)) },
        { label: 'Pass threshold', value: String(t.projectedGrade) },
      ],
    };
  },

  heavy_commitments(m, t) {
    const on = m.hours >= t.commitmentHours;
    return {
      on,
      summary: on
        ? `${round1(m.hours)} weighted hours of work and care a week, at or above the ${t.commitmentHours}-hour threshold.`
        : `${round1(m.hours)} weighted hours a week, under the ${t.commitmentHours}-hour threshold.`,
      evidence: [
        { label: 'Weighted hours this week', value: String(round1(m.hours)) },
        { label: 'Threshold', value: `${t.commitmentHours} hours` },
      ],
    };
  },

  missing_data(m, t) {
    const on = m.gap >= t.missingWeeks;
    return {
      on,
      summary: on
        ? `${m.gap} consecutive weeks with no entries at all.`
        : `The longest gap is ${plural(m.gap, 'week')}; the threshold is ${t.missingWeeks}.`,
      evidence: m.weekly.slice(-TREND_WEEKS_SHOWN).map((w) => ({ label: `Week ${w.week_number}`, value: w.hasEntries ? 'recorded' : 'no entries' })),
    };
  },
};

/** The measurements every signal draws on, computed once per evaluation. */
function measure(weekly, hours) {
  const scored = weekly.filter((w) => w.raw != null);
  const attendance = totalsFor(weekly, 'attendance');
  const participation = totalsFor(weekly, 'participation');
  return {
    weekly,
    scored,
    hours,
    run: declineRun(weekly),
    missed: missedAssignments(weekly),
    setCount: weeksSet(weekly),
    attendancePct: pct(attendance.earned, attendance.possible),
    participationPct: pct(participation.earned, participation.possible),
    projected: scored.length ? scored.reduce((a, w) => a + w.raw, 0) / scored.length : null,
    gap: missingRun(weekly),
  };
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
  const m = measure(weekly, hours);

  const signals = SIGNAL_KEYS.map((key) => {
    const isActive = active[key] !== false;
    const definition = SIGNAL_DEFINITIONS[key](m, t);
    return {
      key,
      label: SIGNAL_LABELS[key],
      active: isActive,
      on: isActive && definition.on,
      summary: definition.summary,
      evidence: definition.evidence,
    };
  });

  const on = signals.filter((s) => s.on);
  return {
    signals,
    signals_on: on.map((s) => s.key),
    level: levelFor(on.length),
    /** So a borderline student is visible rather than hidden by their level. */
    oneAway: on.length < HIGHEST_LEVEL_INDEX ? levelFor(on.length + 1) : null,
    metrics: {
      declineRun: m.run,
      missedAssignments: m.missed,
      attendancePct: round1(m.attendancePct),
      participationPct: round1(m.participationPct),
      projected: round1(m.projected),
      hours: round1(hours),
      missingRun: m.gap,
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
