// The services layer. EVERY backend call the UI makes goes through this module —
// nothing else in the app talks to a data source, and no scoring runs in the view.
//
// createApi({ source, latency, failRate }) returns an object shaped like the
// FastAPI service in the spec:
//
//   getBootstrap(classId)                     GET /classes/{id}/weeks + /criteria
//   getRanking({...})                         GET /classes/{id}/ranking
//   getExplanation({...})                     GET /classes/{id}/students/{sid}/explanation
//   saveWeights(classId, weights)             PUT /classes/{id}/weights
//   refresh() / getStatus()                   cache controls + "last updated"
//
// Swapping `source` for a SheetsAdapter changes nothing above this line.

import { scoreStudent, rankRows, gapToNext, gapToBelow, displayName, normaliseWeights } from './scoring.js';

const CACHE_TTL_MS = 60000;
const REFRESH_COOLDOWN_MS = 10000;

export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

export function createApi({ source, latency = 'realistic', failRate = 0, now = () => Date.now() } = {}) {
  if (!source) throw new Error('createApi requires a DataSource');

  let cache = null;            // { at, classes, students, criteria, weeks, entries }
  let savedWeights = null;     // app-owned settings, separate from read-only scores
  let lastRefreshAt = 0;
  let forcedError = null;

  const delay = async (min, max) => {
    if (latency === 'none') return;
    await sleep(min + Math.random() * (max - min));
  };

  const maybeFail = () => {
    if (forcedError) throw new ApiError(forcedError, 503);
    if (failRate > 0 && Math.random() < failRate) throw new ApiError('The data source did not respond.', 503);
  };

  async function load(force = false) {
    if (!force && cache && now() - cache.at < CACHE_TTL_MS) return cache;
    let fresh;
    try {
      maybeFail();
      const [classes, students, criteria, weeks, entries] = await Promise.all([
        source.listClasses(),
        source.listStudents('c1'),
        source.listCriteria('c1'),
        source.listWeeks('t1'),
        source.getEntries({ classId: 'c1' }),
      ]);
      fresh = { at: now(), stale: false, classes, students, criteria, weeks, entries };
    } catch (err) {
      // Reliability rule: serve the last good snapshot rather than a blank screen.
      if (cache) {
        cache = { ...cache, stale: true };
        return cache;
      }
      throw err;
    }
    cache = { ...fresh, issues: dataCheck(fresh) };
    return cache;
  }

  /** Validate the read instead of failing the whole table. */
  function dataCheck({ students, entries }) {
    const ids = new Set(students.map((s) => s.id));
    const issues = [];
    for (const e of entries) {
      if (!ids.has(e.student_id)) issues.push({ level: 'error', where: e.id, message: `Unknown student ID "${e.student_id}"` });
      else if (typeof e.earned !== 'number' || Number.isNaN(e.earned)) issues.push({ level: 'error', where: e.id, message: `Non-numeric score for ${e.student_id}` });
      else if (e.possible != null && e.earned > e.possible) issues.push({ level: 'warning', where: e.id, message: `${e.student_id}: ${e.earned} earned of ${e.possible} possible` });
    }
    return issues;
  }

  function weekIdsFor(weeks, weekId, windowMode) {
    const idx = weeks.findIndex((w) => w.id === weekId);
    if (idx < 0) return [];
    return windowMode === 'cumulative' ? weeks.slice(0, idx + 1).map((w) => w.id) : [weekId];
  }

  function buildRows(snap, { weekId, windowMode, weights, criteriaKeys, nameMode }) {
    const criteria = snap.criteria.filter((c) => criteriaKeys.includes(c.key));
    const ids = weekIdsFor(snap.weeks, weekId, windowMode);
    const byStudent = new Map();
    for (const e of snap.entries) {
      if (!ids.includes(e.week_id)) continue;
      if (!criteriaKeys.includes(e.criterion_key)) continue;
      if (!byStudent.has(e.student_id)) byStudent.set(e.student_id, []);
      byStudent.get(e.student_id).push(e);
    }
    const rows = snap.students
      .filter((s) => (byStudent.get(s.id) || []).length > 0)
      .map((s) => {
        const result = scoreStudent({ entries: byStudent.get(s.id), criteria, weights });
        const normalisedByKey = Object.fromEntries(result.parts.map((p) => [p.key, p.normalised ?? -1]));
        return {
          student_id: s.id,
          display_name: displayName(s, nameMode),
          full_name: s.display_name,
          score: result.score ?? 0,
          parts: result.parts,
          missingKeys: result.missingKeys,
          normalisedByKey,
        };
      });
    return rankRows(rows, ['attendance', 'homework']);
  }

  return {
    describeSource() {
      return { kind: source.kind, label: source.label, demo: source.kind === 'toy' };
    },

    async getBootstrap(classId = 'c1') {
      await delay(180, 420);
      const snap = await load();
      const criteria = snap.criteria;
      const weights = savedWeights || Object.fromEntries(criteria.map((c) => [c.key, c.default_weight]));
      return {
        klass: snap.classes.find((c) => c.id === classId) || snap.classes[0],
        weeks: snap.weeks,
        criteria,
        weights,
        accounts: source.listAccounts ? await source.listAccounts() : [],
        tieBreakers: ['Attendance', 'Homework'],
        source: this.describeSource(),
        lastUpdated: snap.at,
        issues: snap.issues || [],
      };
    },

    /** GET /classes/{id}/ranking?week=&criteria=&window= */
    async getRanking({ classId = 'c1', weekId, windowMode = 'week', criteriaKeys, weights, nameMode = 'full' }) {
      await delay(120, 320);
      const snap = await load();
      const keys = criteriaKeys && criteriaKeys.length ? criteriaKeys : snap.criteria.map((c) => c.key);
      const w = normaliseWeights(
        Object.fromEntries(keys.map((k) => [k, (weights || Object.fromEntries(snap.criteria.map((c) => [c.key, c.default_weight])))[k] ?? 0])),
      );
      const rows = buildRows(snap, { weekId, windowMode, weights: w, criteriaKeys: keys, nameMode });

      // Rank movement is measured against the previous week's table.
      const idx = snap.weeks.findIndex((x) => x.id === weekId);
      let prevRank = new Map();
      if (idx > 0) {
        const prev = buildRows(snap, { weekId: snap.weeks[idx - 1].id, windowMode, weights: w, criteriaKeys: keys, nameMode });
        prevRank = new Map(prev.map((r) => [r.student_id, r.rank]));
      }

      const decorated = rows.map((r, i) => ({
        student_id: r.student_id,
        display_name: r.display_name,
        score: r.score,
        rank: r.rank,
        tied: r.tied,
        rank_delta: prevRank.has(r.student_id) ? prevRank.get(r.student_id) - r.rank : null,
        missing: r.missingKeys,
        gap_to_next: gapToNext(rows, i),
        gap_to_below: gapToBelow(rows, i),
      }));

      return {
        classId,
        weekId,
        windowMode,
        criteriaKeys: keys,
        weights: w,
        rows: decorated,
        lastUpdated: snap.at,
        stale: !!snap.stale,
        issues: snap.issues || [],
      };
    },

    /** GET /classes/{id}/students/{sid}/explanation — role-checked server-side. */
    async getExplanation({ classId = 'c1', studentId, weekId, windowMode = 'week', criteriaKeys, weights, nameMode = 'full', caller = { role: 'teacher' } }) {
      if (caller.role === 'student' && caller.studentId !== studentId) {
        throw new ApiError('A student may only open their own breakdown.', 403);
      }
      await delay(100, 240);
      const snap = await load();
      const keys = criteriaKeys && criteriaKeys.length ? criteriaKeys : snap.criteria.map((c) => c.key);
      const w = normaliseWeights(
        Object.fromEntries(keys.map((k) => [k, (weights || Object.fromEntries(snap.criteria.map((c) => [c.key, c.default_weight])))[k] ?? 0])),
      );
      const rows = buildRows(snap, { weekId, windowMode, weights: w, criteriaKeys: keys, nameMode });
      const i = rows.findIndex((r) => r.student_id === studentId);
      if (i < 0) throw new ApiError('No entries for that student in this window.', 404);
      const row = rows[i];
      return {
        student_id: studentId,
        display_name: row.display_name,
        rank: row.rank,
        tied: row.tied,
        score: row.score,
        parts: row.parts,
        gap_to_next: gapToNext(rows, i),
        gap_to_below: gapToBelow(rows, i),
        above: i > 0 ? rows.find((r, j) => j < i && r.rank < row.rank)?.display_name ?? null : null,
        weekId,
        windowMode,
      };
    },

    /** PUT /classes/{id}/weights — app settings, not the read-only source. */
    async saveWeights(classId, weights) {
      await delay(150, 300);
      savedWeights = normaliseWeights(weights);
      return { classId, weights: savedWeights };
    },

    async refresh() {
      const since = now() - lastRefreshAt;
      if (since < REFRESH_COOLDOWN_MS) {
        throw new ApiError(`Please wait ${Math.ceil((REFRESH_COOLDOWN_MS - since) / 1000)}s before refreshing again.`, 429);
      }
      lastRefreshAt = now();
      await delay(300, 700);
      const snap = await load(true);
      return { lastUpdated: snap.at, issues: snap.issues || [], stale: !!snap.stale };
    },

    getStatus() {
      return { lastUpdated: cache?.at ?? null, stale: !!cache?.stale, issues: cache?.issues || [], source: this.describeSource() };
    },

    // Test / demo hooks — not part of the HTTP surface.
    __forceError(message) { forcedError = message; },
    __clearError() { forcedError = null; },
    __resetWeights() { savedWeights = null; },
  };
}
