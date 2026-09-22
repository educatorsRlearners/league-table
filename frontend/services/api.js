// The services layer. EVERY backend call the UI makes goes through this module —
// nothing else in the app talks to a data source, and no scoring runs in the view.
//
// createApi({ source, store, latency, failRate }) returns an object shaped like
// the FastAPI service in the spec:
//
//   listClasses()                             GET /classes
//   getBootstrap(classId)                     GET /classes/{id}/weeks + /criteria + /settings
//   getRanking({...})                         GET /classes/{id}/ranking?week=&criteria=&window=
//   getExplanation({...})                     GET /classes/{id}/students/{sid}/explanation
//   getExplainer(classId)                     GET /classes/{id}/explainer
//   getCommitments({...})                     GET /me/commitments
//   getDigest()                               GET /instructor/digest
//   saveSettings(classId, patch)              PUT /classes/{id}/settings
//   refresh() / getStatus()                   cache controls + "last updated"
//
// Swapping `source` for a SheetsAdapter, or `store` for SqliteStore, changes
// nothing above this line.

import {
  scoreStudent, rankRows, gapToNext, gapToBelow, displayName, normaliseWeights,
  resolveHours, weightedHours, commitmentFactor, adjust, mean, ZERO_HOURS,
} from './scoring.js';
import { evaluateSignals, diffState } from './risk.js';

const CACHE_TTL_MS = 60000;
const REFRESH_COOLDOWN_MS = 10000;
const DEFAULT_ROLLING_N = 4;
const LEVEL_ORDER = ['Not flagged', 'Watch', 'At risk', 'High risk'];

export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const round1 = (n) => (n == null ? null : Math.round(n * 10) / 10);

export function createApi({ source, store, latency = 'realistic', failRate = 0, now = () => Date.now() } = {}) {
  if (!source) throw new Error('createApi requires a DataSource');
  if (!store) throw new Error('createApi requires an AppStore');

  const caches = new Map();   // classId → snapshot
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

  async function load(classId, force = false) {
    const cached = caches.get(classId);
    if (!force && cached && now() - cached.at < CACHE_TTL_MS) return cached;
    let fresh;
    try {
      maybeFail();
      const [students, criteria, weeks, entries, baselines, weeklyUpdates, settings] = await Promise.all([
        source.listStudents(classId),
        source.listCriteria(classId),
        source.listWeeks('t1'),
        source.getEntries({ classId }),
        store.listBaselines(classId),
        store.listWeeklyUpdates(classId),
        store.getLeagueSettings(classId),
      ]);
      fresh = { at: now(), stale: false, classId, students, criteria, weeks, entries, baselines, weeklyUpdates, settings };
    } catch (err) {
      // Reliability rule: serve the last good snapshot rather than a blank screen.
      if (cached) {
        const staleSnap = { ...cached, stale: true };
        caches.set(classId, staleSnap);
        return staleSnap;
      }
      throw err;
    }
    const snap = { ...fresh, issues: dataCheck(fresh) };
    caches.set(classId, snap);
    return snap;
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

  /**
   * The table opens on the most recent *completed* week: the last recorded
   * week whose entry count is close to a full week's worth. The week in
   * progress is usually part-recorded, so it is not the landing week.
   */
  function latestCompleteWeek(snap) {
    const counts = new Map();
    for (const e of snap.entries) counts.set(e.week_id, (counts.get(e.week_id) || 0) + 1);
    if (!counts.size) return snap.weeks[0]?.id ?? null;
    const max = Math.max(...counts.values());
    const complete = snap.weeks.filter((w) => (counts.get(w.id) || 0) >= max * 0.8);
    const any = snap.weeks.filter((w) => counts.has(w.id));
    return (complete[complete.length - 1] || any[any.length - 1]).id;
  }

  /* ------------------------------------------------------------ risk */

  /** Weekly shape the risk engine needs: raw score, entry presence, totals by criterion. */
  function riskWeekly(snap, student, upToWeekNumber) {
    const criteria = snap.criteria;
    const defaults = Object.fromEntries(criteria.map((c) => [c.key, c.default_weight]));
    const w100 = normaliseWeights(snap.settings.weights || defaults);
    return snap.weeks
      .filter((w) => w.week_number >= (student.joined_week || 1) && w.week_number <= upToWeekNumber)
      .map((w) => {
        const entries = snap.entries.filter((e) => e.week_id === w.id && e.student_id === student.id);
        const byKey = {};
        for (const e of entries) {
          const slot = byKey[e.criterion_key] || (byKey[e.criterion_key] = { earned: 0, possible: 0 });
          slot.earned += e.earned;
          slot.possible += e.possible;
        }
        const result = entries.length ? scoreStudent({ entries, criteria, weights: w100 }) : null;
        return { week_number: w.week_number, raw: result ? result.score : null, hasEntries: entries.length > 0, byKey };
      });
  }

  function hoursAt(snap, student, weekNumber) {
    const baseline = snap.baselines.find((b) => b.student_id === student.id && b.status !== 'superseded') || null;
    const updates = snap.weeklyUpdates.filter((u) => u.student_id === student.id);
    const { hours } = resolveHours({ baseline, weeklyUpdates: updates, weekNumber });
    return weightedHours(hours, snap.settings.typeWeights);
  }

  function evaluationWeek(snap) {
    const id = latestCompleteWeek(snap);
    return (snap.weeks.find((w) => w.id === id) || snap.weeks[0]).week_number;
  }

  async function evaluateClass(classId, upToWeekNumber) {
    const snap = await load(classId);
    const rs = await store.getRiskSettings(classId);
    const week = upToWeekNumber ?? evaluationWeek(snap);
    return {
      week,
      settings: rs,
      rows: snap.students.map((s) => {
        const weekly = riskWeekly(snap, s, week);
        const ev = evaluateSignals({ weekly, hours: hoursAt(snap, s, week), thresholds: rs.thresholds, active: rs.active });
        return { student_id: s.id, display_name: s.display_name, week_number: week, ...ev };
      }),
    };
  }

  /** Which weeks a window covers: one, all to date, or the last N. */
  function windowWeeks(weeks, weekId, windowMode, rollingN = DEFAULT_ROLLING_N) {
    const idx = weeks.findIndex((w) => w.id === weekId);
    if (idx < 0) return [];
    if (windowMode === 'cumulative') return weeks.slice(0, idx + 1);
    if (windowMode === 'rolling') return weeks.slice(Math.max(0, idx + 1 - rollingN), idx + 1);
    return [weeks[idx]];
  }

  function resolvedWeights(snap, keys, override) {
    const defaults = Object.fromEntries(snap.criteria.map((c) => [c.key, c.default_weight]));
    const base = override || snap.settings.weights || defaults;
    return normaliseWeights(Object.fromEntries(keys.map((k) => [k, base[k] ?? 0])));
  }

  /**
   * Per-student, per-week: raw score → weighted hours → factor → adjusted,
   * capped at 100. Multi-week windows average the weekly adjusted scores, so
   * each week's factor and cap apply to that week only.
   */
  function studentWeeks(snap, student, wks, criteria, criteriaKeys, weights) {
    const baseline = snap.baselines.find((b) => b.student_id === student.id && b.status !== 'superseded') || null;
    const updates = snap.weeklyUpdates.filter((u) => u.student_id === student.id);
    const { typeWeights, rate, cap } = snap.settings;

    return wks
      .map((w) => {
        const entries = snap.entries.filter(
          (e) => e.week_id === w.id && e.student_id === student.id && criteriaKeys.includes(e.criterion_key),
        );
        if (!entries.length) return null;
        const result = scoreStudent({ entries, criteria, weights });
        if (result.score == null) return null;
        const { hours, source: hoursSource } = resolveHours({ baseline, weeklyUpdates: updates, weekNumber: w.week_number });
        const h = weightedHours(hours, typeWeights);
        const factor = commitmentFactor(h, rate, cap);
        const { adjusted, capped } = adjust(result.score, factor);
        return {
          week_id: w.id,
          week_number: w.week_number,
          raw: result.score,
          hours,
          hours_source: hoursSource,
          weighted_hours: h,
          factor,
          adjusted,
          capped,
          parts: result.parts,
          missingKeys: result.missingKeys,
        };
      })
      .filter(Boolean);
  }

  function buildRows(snap, { weekId, windowMode, rollingN, weights, criteriaKeys, nameMode }) {
    const criteria = snap.criteria.filter((c) => criteriaKeys.includes(c.key));
    const wks = windowWeeks(snap.weeks, weekId, windowMode, rollingN);
    const rows = [];
    for (const s of snap.students) {
      const weekRows = studentWeeks(snap, s, wks, criteria, criteriaKeys, weights);
      if (!weekRows.length) continue;
      const last = weekRows[weekRows.length - 1];
      const normalisedByKey = Object.fromEntries(last.parts.map((p) => [p.key, p.normalised ?? -1]));
      rows.push({
        student_id: s.id,
        display_name: displayName(s, nameMode),
        full_name: s.display_name,
        score: mean(weekRows.map((r) => r.adjusted)),
        raw: mean(weekRows.map((r) => r.raw)),
        factor: mean(weekRows.map((r) => r.factor)),
        weighted_hours: mean(weekRows.map((r) => r.weighted_hours)),
        capped: weekRows.some((r) => r.capped),
        hours_source: last.hours_source,
        weeks: weekRows,
        parts: last.parts,
        missingKeys: last.missingKeys,
        normalisedByKey,
      });
    }
    return rankRows(rows, snap.settings.tieBreakers || []);
  }

  /** A student may never receive another student's raw score, factor or hours. */
  function scopeRow(row, caller) {
    const publicRow = {
      student_id: row.student_id,
      display_name: row.display_name,
      score: row.score,
      rank: row.rank,
      tied: row.tied,
      rank_delta: row.rank_delta,
      gap_to_next: row.gap_to_next,
      gap_to_below: row.gap_to_below,
      missing: row.missing,
      is_self: row.is_self,
    };
    if (caller.role === 'instructor' || row.student_id === caller.studentId) {
      return { ...publicRow, raw: row.raw, factor: row.factor, weighted_hours: row.weighted_hours, capped: row.capped, hours_source: row.hours_source };
    }
    return publicRow;
  }

  return {
    describeSource() {
      return { kind: source.kind, label: source.label, demo: source.kind === 'toy', store: store.label };
    },

    /** GET /classes */
    async listClasses(instructorId = 'i1') {
      await delay(80, 180);
      return source.listClasses(instructorId);
    },

    async getBootstrap(classId = 'c1') {
      await delay(180, 420);
      const snap = await load(classId);
      const classes = await source.listClasses('i1');
      const defaults = Object.fromEntries(snap.criteria.map((c) => [c.key, c.default_weight]));
      return {
        klass: classes.find((c) => c.id === classId) || classes[0],
        classes,
        weeks: snap.weeks,
        criteria: snap.criteria,
        weights: snap.settings.weights || defaults,
        defaultWeights: defaults,
        settings: { typeWeights: snap.settings.typeWeights, rate: snap.settings.rate, cap: snap.settings.cap },
        tieBreakers: (snap.settings.tieBreakers || []).map((k) => (snap.criteria.find((c) => c.key === k) || { label: k }).label),
        accounts: source.listAccounts ? await source.listAccounts() : [],
        weeksWithData: [...new Set(snap.entries.map((e) => e.week_id))],
        latestCompleteWeekId: latestCompleteWeek(snap),
        source: this.describeSource(),
        lastUpdated: snap.at,
        issues: snap.issues || [],
        rollingN: DEFAULT_ROLLING_N,
      };
    },

    /** GET /classes/{id}/ranking?week=&criteria=&window= */
    async getRanking({
      classId = 'c1', weekId, windowMode = 'week', rollingN = DEFAULT_ROLLING_N,
      criteriaKeys, weights, nameMode = 'full', caller = { role: 'instructor' },
    }) {
      await delay(120, 320);
      const snap = await load(classId);
      if (caller.role === 'student' && caller.classId && caller.classId !== classId) {
        throw new ApiError('That class is not yours to read.', 403);
      }
      const keys = criteriaKeys && criteriaKeys.length ? criteriaKeys : snap.criteria.map((c) => c.key);
      const w = resolvedWeights(snap, keys, weights);
      const rows = buildRows(snap, { weekId, windowMode, rollingN, weights: w, criteriaKeys: keys, nameMode });

      // Rank movement compares adjusted ranks week to week.
      const idx = snap.weeks.findIndex((x) => x.id === weekId);
      let prevRank = new Map();
      if (idx > 0) {
        const prev = buildRows(snap, { weekId: snap.weeks[idx - 1].id, windowMode, rollingN, weights: w, criteriaKeys: keys, nameMode });
        prevRank = new Map(prev.map((r) => [r.student_id, r.rank]));
      }

      const decorated = rows.map((r, i) => scopeRow({
        ...r,
        rank_delta: prevRank.has(r.student_id) ? prevRank.get(r.student_id) - r.rank : null,
        missing: r.missingKeys,
        gap_to_next: gapToNext(rows, i),
        gap_to_below: gapToBelow(rows, i),
        is_self: caller.role === 'student' && caller.studentId === r.student_id,
      }, caller));

      return {
        classId, weekId, windowMode, rollingN,
        criteriaKeys: keys,
        weights: w,
        rows: decorated,
        weekCount: windowWeeks(snap.weeks, weekId, windowMode, rollingN).length,
        lastUpdated: snap.at,
        stale: !!snap.stale,
        issues: snap.issues || [],
      };
    },

    /** GET /classes/{id}/students/{sid}/explanation — role-checked server-side. */
    async getExplanation({
      classId = 'c1', studentId, weekId, windowMode = 'week', rollingN = DEFAULT_ROLLING_N,
      criteriaKeys, weights, nameMode = 'full', caller = { role: 'instructor' },
    }) {
      if (caller.role === 'student' && caller.studentId !== studentId) {
        throw new ApiError('A student may only open their own breakdown.', 403);
      }
      await delay(100, 240);
      const snap = await load(classId);
      const keys = criteriaKeys && criteriaKeys.length ? criteriaKeys : snap.criteria.map((c) => c.key);
      const w = resolvedWeights(snap, keys, weights);
      const rows = buildRows(snap, { weekId, windowMode, rollingN, weights: w, criteriaKeys: keys, nameMode });
      const i = rows.findIndex((r) => r.student_id === studentId);
      if (i < 0) throw new ApiError('No entries for that student in this window.', 404);
      const row = rows[i];
      const focus = row.weeks[row.weeks.length - 1];
      return {
        student_id: studentId,
        display_name: row.display_name,
        rank: row.rank,
        tied: row.tied,
        score: row.score,
        raw: row.raw,
        focusRaw: focus.raw,
        focusAdjusted: focus.adjusted,
        focusCapped: focus.capped,
        factor: row.factor,
        weighted_hours: row.weighted_hours,
        capped: row.capped,
        hours: focus.hours,
        hours_source: focus.hours_source,
        typeWeights: snap.settings.typeWeights,
        rate: snap.settings.rate,
        cap: snap.settings.cap,
        focusWeek: focus.week_number,
        parts: focus.parts,
        weeks: row.weeks.map((r) => ({
          week_number: r.week_number, raw: r.raw, weighted_hours: r.weighted_hours,
          factor: r.factor, adjusted: r.adjusted, capped: r.capped,
        })),
        gap_to_next: gapToNext(rows, i),
        gap_to_below: gapToBelow(rows, i),
        above: rows.slice(0, i).reverse().find((r) => r.rank < row.rank)?.display_name ?? null,
        weekId, windowMode,
      };
    },

    /** GET /classes/{id}/explainer — the formula and its current values, no personal data. */
    async getExplainer(classId = 'c1') {
      await delay(60, 140);
      const snap = await load(classId);
      const { typeWeights, rate, cap } = snap.settings;
      return {
        typeWeights, rate, cap,
        table: [0, 10, 20, 25].map((h) => ({ hours: h, factor: commitmentFactor(h, rate, cap) })),
        example: (() => {
          const hours = { work: 12, childcare: 6, eldercare: 0 };
          const h = weightedHours(hours, typeWeights);
          const factor = commitmentFactor(h, rate, cap);
          return { raw: 80, hours, weighted_hours: h, factor, adjusted: adjust(80, factor).adjusted };
        })(),
      };
    },

    /** GET /me/commitments — own hours, status and factor by week. */
    async getCommitments({ classId = 'c1', studentId, caller = { role: 'instructor' } }) {
      if (caller.role === 'student' && caller.studentId !== studentId) {
        throw new ApiError('A student may only read their own commitments.', 403);
      }
      await delay(80, 180);
      const snap = await load(classId);
      const { baseline, weeklyUpdates } = await store.getCommitments(classId, studentId);
      const { typeWeights, rate, cap } = snap.settings;
      return {
        studentId,
        baseline,
        weeklyUpdates,
        byWeek: snap.weeks.map((w) => {
          const { hours, source: src } = resolveHours({ baseline, weeklyUpdates, weekNumber: w.week_number });
          const h = weightedHours(hours, typeWeights);
          return { week_number: w.week_number, hours, source: src, weighted_hours: h, factor: commitmentFactor(h, rate, cap) };
        }),
      };
    },

    /**
     * GET /instructor/digest — across every class the instructor teaches.
     * "Newly flagged" is measured against what they saw last time; on a first
     * visit the previous week stands in, so the comparison is always real.
     */
    async getDigest(instructorId = 'i1') {
      await delay(200, 480);
      const classes = await source.listClasses(instructorId);
      const groups = [];
      for (const k of classes) {
        const current = await evaluateClass(k.id);
        const stored = await store.getRiskSnapshot(k.id);
        const prior = stored || (current.week > 1 ? await evaluateClass(k.id, current.week - 1) : { rows: [], week: null });
        const priorById = new Map(prior.rows.map((r) => [r.student_id, r]));
        const notes = await store.listNotes(k.id, null, instructorId);
        const noteCount = new Map();
        for (const n of notes) noteCount.set(n.student_id, (noteCount.get(n.student_id) || 0) + 1);

        groups.push({
          classId: k.id,
          className: k.name,
          week: current.week,
          comparedWith: prior.week,
          comparedWithStored: !!stored,
          rows: current.rows
            .map((r) => ({
              student_id: r.student_id,
              display_name: r.display_name,
              level: r.level,
              status: diffState(priorById.get(r.student_id), r),
              priorLevel: priorById.get(r.student_id)?.level ?? null,
              signals: r.signals.filter((s) => s.on).map((s) => s.label),
              notes: noteCount.get(r.student_id) || 0,
            }))
            .filter((r) => r.status !== 'quiet')
            .sort((a, b) => LEVEL_ORDER.indexOf(b.level) - LEVEL_ORDER.indexOf(a.level) || a.display_name.localeCompare(b.display_name)),
        });
        await store.saveRiskSnapshot(k.id, current);
      }
      return { instructorId, groups, computedAt: new Date(now()).toISOString() };
    },

    /** GET /classes/{id}/students/{sid}/risk — instructor, or the student for their own. */
    async getRiskRecord({ classId = 'c1', studentId, caller = { role: 'instructor' } }) {
      if (caller.role === 'student' && caller.studentId !== studentId) {
        throw new ApiError('A student may only open their own standing.', 403);
      }
      await delay(140, 340);
      const snap = await load(classId);
      const student = snap.students.find((s) => s.id === studentId);
      if (!student) throw new ApiError('No such student in this class.', 404);
      const rs = await store.getRiskSettings(classId);
      const week = evaluationWeek(snap);
      const weekly = riskWeekly(snap, student, week);
      const current = evaluateSignals({ weekly, hours: hoursAt(snap, student, week), thresholds: rs.thresholds, active: rs.active });

      // Level over the semester, so the instructor can see the direction of travel.
      const history = [];
      for (let w = Math.max(student.joined_week || 1, 2); w <= week; w++) {
        const ev = evaluateSignals({
          weekly: riskWeekly(snap, student, w),
          hours: hoursAt(snap, student, w),
          thresholds: rs.thresholds,
          active: rs.active,
        });
        history.push({ week_number: w, level: ev.level, count: ev.signals_on.length });
      }

      return {
        classId,
        className: (await source.listClasses('i1')).find((c) => c.id === classId)?.name ?? classId,
        student_id: studentId,
        display_name: student.display_name,
        week,
        level: current.level,
        oneAway: current.oneAway,
        signals: current.signals,
        metrics: current.metrics,
        thresholds: rs.thresholds,
        history,
        // Notes are instructor-private and never travel to a student.
        notes: caller.role === 'instructor' ? await store.listNotes(classId, studentId, caller.instructorId || 'i1') : [],
      };
    },

    /** POST /classes/{id}/students/{sid}/notes */
    async addNote({ classId = 'c1', studentId, body, caller = { role: 'instructor' } }) {
      if (caller.role !== 'instructor') throw new ApiError('Only an instructor can log outreach.', 403);
      if (!body || !body.trim()) throw new ApiError('A note needs some text.', 400);
      await delay(120, 260);
      return store.addNote({ classId, studentId, instructorId: caller.instructorId || 'i1', body: body.trim() });
    },

    /** GET /classes/{id}/risk-settings */
    async getRiskSettings(classId = 'c1') {
      await delay(60, 140);
      return store.getRiskSettings(classId);
    },

    /**
     * PUT /classes/{id}/risk-settings — recomputes going forward. History is
     * not rewritten: the stored snapshot keeps the levels in effect at the time.
     */
    async saveRiskSettings(classId, patch) {
      await delay(140, 300);
      return store.saveRiskSettings(classId, patch);
    },

    /** GET /me/standing — the student's own level and signals, nothing else. */
    async getMyStanding({ classId = 'c1', studentId, caller = { role: 'student' } }) {
      if (caller.role === 'student' && caller.studentId !== studentId) {
        throw new ApiError('A student may only read their own standing.', 403);
      }
      const record = await this.getRiskRecord({ classId, studentId, caller: { role: 'student', studentId } });
      return {
        student_id: record.student_id,
        display_name: record.display_name,
        week: record.week,
        level: record.level,
        signals: record.signals.filter((s) => s.on),
        metrics: record.metrics,
        help: 'Office hours are Tuesdays 2–4pm, and the advising team can be reached at advising@example.edu.',
      };
    },

    /** PUT /classes/{id}/settings — weights and adjustment parameters. */
    async saveSettings(classId, patch) {
      await delay(150, 300);
      const next = { ...patch };
      if (next.weights) next.weights = normaliseWeights(next.weights);
      const saved = await store.saveLeagueSettings(classId, next);
      const cached = caches.get(classId);
      if (cached) caches.set(classId, { ...cached, settings: saved });
      return saved;
    },

    async refresh(classId = 'c1') {
      const since = now() - lastRefreshAt;
      if (since < REFRESH_COOLDOWN_MS) {
        throw new ApiError(`Please wait ${Math.ceil((REFRESH_COOLDOWN_MS - since) / 1000)}s before refreshing again.`, 429);
      }
      lastRefreshAt = now();
      await delay(300, 700);
      const snap = await load(classId, true);
      return { lastUpdated: snap.at, issues: snap.issues || [], stale: !!snap.stale };
    },

    getStatus(classId = 'c1') {
      const c = caches.get(classId);
      return { lastUpdated: c?.at ?? null, stale: !!c?.stale, issues: c?.issues || [], source: this.describeSource() };
    },

    // Test / demo hooks — not part of the HTTP surface.
    __forceError(message) { forcedError = message; },
    __clearError() { forcedError = null; },
    __round1: round1,
    __ZERO_HOURS: ZERO_HOURS,
  };
}
