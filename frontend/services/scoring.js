// Pure scoring logic. No I/O, no adapter detail — operates only on normalised
// model types (students, criteria, entries). Mirrors what the FastAPI service
// would run server-side.

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
 * Weighted score for one student.
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
      effective_weight: effectiveWeight,
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

const round1 = (n) => Math.round(n * 10) / 10;

/**
 * Assign competition ranks (1, 1, 3). Ties are decided for *display order only*
 * by the tie-breaker criteria, which never change the shared rank number.
 */
export function rankRows(rows, tieBreakers = []) {
  const keyed = rows.map((r) => ({ ...r, scoreRounded: r.score == null ? -1 : round1(r.score) }));
  keyed.sort((a, b) => {
    if (b.scoreRounded !== a.scoreRounded) return b.scoreRounded - a.scoreRounded;
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
  // mark the first member of a tie group as tied too
  for (let i = 0; i < keyed.length - 1; i++) {
    if (keyed[i + 1].rank === keyed[i].rank) keyed[i].tied = true;
  }
  return keyed;
}

/** The closest row with a better rank, skipping a tie partner; null at the top. */
export function nearestAbove(rows, index) {
  for (let i = index - 1; i >= 0; i--) {
    if (rows[i].rank < rows[index].rank) return rows[i];
  }
  return null;
}

/** Points a student needs to add to reach the rank above them. */
export function gapToNext(rows, index) {
  const above = nearestAbove(rows, index);
  return above ? Math.max(0, above.score - rows[index].score) : null;
}

export function gapToBelow(rows, index) {
  for (let i = index + 1; i < rows.length; i++) {
    if (rows[i].rank > rows[index].rank) return Math.max(0, rows[index].score - rows[i].score);
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
