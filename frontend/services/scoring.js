// Pure scoring logic. No I/O, no adapter detail — operates only on normalised
// model types (students, criteria, entries, commitments). Mirrors what the
// FastAPI service would run server-side.

export const ZERO_HOURS = { work: 0, childcare: 0, eldercare: 0 };

export function normalise(earned, possible) {
  if (possible == null || possible <= 0) return null;
  if (earned == null) return null;
  return (100 * earned) / possible;
}

/** Sum raw entries into { [criterionKey]: {earned, possible} } for a window. */
export function aggregate(entries) {
  const out = {};
  for (const e of entries) {
    if (e.earned == null || e.possible == null) continue;
    const slot = out[e.criterion_key] || (out[e.criterion_key] = { earned: 0, possible: 0 });
    slot.earned += e.earned;
    slot.possible += e.possible;
  }
  return out;
}

/**
 * Step 1 — weighted raw score for one student in one window.
 * Missing criteria are excluded and the remaining weights are rescaled,
 * so absence of data is never scored as zero.
 */
export function scoreStudent({ entries, criteria, weights }) {
  const agg = aggregate(entries);
  const present = criteria.filter((c) => {
    const a = agg[c.key];
    return a && a.possible > 0 && (weights[c.key] ?? 0) > 0;
  });
  const weightSum = present.reduce((s, c) => s + (weights[c.key] ?? 0), 0);

  const parts = criteria.map((c) => {
    const a = agg[c.key];
    const weight = weights[c.key] ?? 0;
    const missing = !(a && a.possible > 0);
    const normalised = missing ? null : normalise(a.earned, a.possible);
    const effectiveWeight = missing || weightSum === 0 ? 0 : (weight / weightSum) * 100;
    return {
      key: c.key,
      label: c.label,
      earned: missing ? null : a.earned,
      possible: missing ? null : a.possible,
      normalised,
      weight,
      effectiveWeight,
      points: missing ? 0 : (normalised * effectiveWeight) / 100,
      missing,
    };
  });

  const score = parts.reduce((s, p) => s + p.points, 0);
  return {
    score: weightSum === 0 ? null : score,
    parts,
    missingKeys: parts.filter((p) => p.missing && p.weight > 0).map((p) => p.key),
  };
}

/* ------------------------------------------------ commitment adjustment */

/** Which hours apply to a student in a given week. */
export function resolveHours({ baseline, weeklyUpdates = [], weekNumber }) {
  const approved = baseline && baseline.status === 'approved';
  if (!approved) {
    return { hours: { ...ZERO_HOURS }, source: baseline ? baseline.status : 'none' };
  }
  const update = weeklyUpdates.find((u) => u.week_number === weekNumber && !u.reversed_at);
  if (update) {
    return {
      hours: { work: update.work_hours, childcare: update.childcare_hours, eldercare: update.eldercare_hours },
      source: 'weekly',
    };
  }
  if (weekNumber >= (baseline.effective_from_week ?? 1)) {
    return {
      hours: { work: baseline.work_hours, childcare: baseline.childcare_hours, eldercare: baseline.eldercare_hours },
      source: 'baseline',
    };
  }
  return { hours: { ...ZERO_HOURS }, source: 'before-effective' };
}

/** Step 2a — H = Σ a_k · h_k */
export function weightedHours(hours = {}, typeWeights = {}) {
  return Object.keys(typeWeights).reduce((s, k) => s + (typeWeights[k] ?? 0) * (hours[k] ?? 0), 0);
}

/** Step 2b — f = min(1 + r·H, f_max) */
export function commitmentFactor(h, rate, cap) {
  return Math.min(1 + rate * h, cap);
}

/** Step 3 — adjusted = min(100, raw · f) */
export function adjust(raw, factor) {
  if (raw == null) return { adjusted: null, capped: false };
  const value = raw * factor;
  return { adjusted: Math.min(100, value), capped: value > 100 + 1e-9 };
}

/** Cumulative and rolling windows average the weekly adjusted scores. */
export function mean(values) {
  const nums = values.filter((v) => v != null);
  if (!nums.length) return null;
  return nums.reduce((a, b) => a + b, 0) / nums.length;
}

/* ------------------------------------------------------------- ranking */

const round1 = (n) => Math.round(n * 10) / 10;

/**
 * Assign competition ranks (1, 1, 3) on the adjusted score. Students tied on
 * adjusted score — including several at 100 — are ordered by the higher raw
 * score, then by the stated tie-breaker criteria; any still tied share a rank.
 */
export function rankRows(rows, tieBreakers = []) {
  const keyed = rows.map((r) => ({
    ...r,
    scoreRounded: r.score == null ? -1 : round1(r.score),
    rawRounded: r.raw == null ? -1 : round1(r.raw),
  }));
  keyed.sort((a, b) => {
    if (b.scoreRounded !== a.scoreRounded) return b.scoreRounded - a.scoreRounded;
    if (b.rawRounded !== a.rawRounded) return b.rawRounded - a.rawRounded;
    for (const key of tieBreakers) {
      const av = a.normalisedByKey?.[key] ?? -1;
      const bv = b.normalisedByKey?.[key] ?? -1;
      if (bv !== av) return bv - av;
    }
    return a.display_name.localeCompare(b.display_name);
  });

  let lastScore = null;
  let lastRank = 0;
  keyed.forEach((row, i) => {
    if (lastScore != null && row.scoreRounded === lastScore) {
      row.rank = lastRank;
      row.tied = true;
    } else {
      row.rank = i + 1;
      lastRank = row.rank;
      lastScore = row.scoreRounded;
      row.tied = false;
    }
  });
  for (let i = 0; i < keyed.length - 1; i++) {
    if (keyed[i + 1].rank === keyed[i].rank) keyed[i].tied = true;
  }
  return keyed;
}

/** Points a student needs to add to reach the rank above them (rounded scores, matching rank grouping). */
export function gapToNext(rows, index) {
  const rounded = (r) => (r.scoreRounded != null && r.scoreRounded >= 0 ? r.scoreRounded : round1(r.score));
  for (let i = index - 1; i >= 0; i--) {
    if (rows[i].rank < rows[index].rank) {
      const a = rounded(rows[i]);
      const b = rounded(rows[index]);
      if (a == null || b == null) return null;
      return Math.max(0, round1(a - b));
    }
  }
  return null;
}

export function gapToBelow(rows, index) {
  const rounded = (r) => (r.scoreRounded != null && r.scoreRounded >= 0 ? r.scoreRounded : round1(r.score));
  for (let i = index + 1; i < rows.length; i++) {
    if (rows[i].rank > rows[index].rank) {
      const a = rounded(rows[index]);
      const b = rounded(rows[i]);
      if (a == null || b == null) return null;
      return Math.max(0, round1(a - b));
    }
  }
  return null;
}

/** Normalise a weight map so the values total 100, preserving proportions. */
export function normaliseWeights(weights) {
  const keys = Object.keys(weights);
  const total = keys.reduce((s, k) => s + (weights[k] || 0), 0);
  if (total === 0) return Object.fromEntries(keys.map((k) => [k, 0]));
  return Object.fromEntries(keys.map((k) => [k, (weights[k] * 100) / total]));
}

export function displayName(student, mode) {
  if (mode === 'nickname') return student.nickname || student.display_name;
  if (mode === 'initials') {
    const bits = student.display_name.split(' ');
    return bits.length > 1 ? `${bits[0]} ${bits[bits.length - 1][0]}.` : bits[0];
  }
  return student.display_name;
}
