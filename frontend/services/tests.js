// Test suites for the scoring logic and the services-layer contract.
// The contract suites are written against the DataSource / AppStore / Api
// interfaces only — any adapter (toy today, Sheets and SQLite later) must pass
// them unchanged.

import {
  normalise, scoreStudent, rankRows, gapToNext, normaliseWeights, displayName,
  resolveHours, weightedHours, commitmentFactor, adjust, mean,
} from './scoring.js';
import { createApi, ApiError } from './api.js';
import { createToySource, createToyAppStore, WEEK_COUNT, DATA_THROUGH } from './mockSource.js';
import { evaluateSignals, levelFor, diffState, DEFAULT_THRESHOLDS, SIGNAL_KEYS } from './risk.js';

const approx = (a, b, eps = 1e-9) => Math.abs(a - b) <= eps;

function suite(name) {
  const tests = [];
  return { name, tests, it(title, fn) { tests.push({ title, fn }); } };
}

function assert(cond, message) {
  if (!cond) throw new Error(message || 'Assertion failed');
}

/* ---------------------------------------------------------------- scoring */

const scoringSuite = suite('Scoring logic');
const CRIT = [
  { key: 'homework', label: 'Homework' },
  { key: 'attendance', label: 'Attendance' },
  { key: 'project', label: 'Project scores' },
];
const W = { homework: 25, attendance: 20, project: 25 };

scoringSuite.it('converts earned/possible to a 0–100 scale', () => {
  assert(normalise(4, 5) === 80, 'expected 80');
  assert(normalise(82, 100) === 82, 'expected 82');
  assert(normalise(1, 0) === null, 'a zero possible is not scoreable');
});

scoringSuite.it('weights a full set of criteria to the right total', () => {
  const r = scoreStudent({
    entries: [
      { criterion_key: 'homework', earned: 5, possible: 5 },
      { criterion_key: 'attendance', earned: 4, possible: 5 },
      { criterion_key: 'project', earned: 60, possible: 100 },
    ],
    criteria: CRIT, weights: W,
  });
  assert(approx(r.score, (100 * 25 + 80 * 20 + 60 * 25) / 70, 1e-9), `got ${r.score}`);
});

scoringSuite.it('excludes a missing criterion and rescales the rest (not a zero)', () => {
  const r = scoreStudent({
    entries: [
      { criterion_key: 'homework', earned: 5, possible: 5 },
      { criterion_key: 'attendance', earned: 4, possible: 5 },
    ],
    criteria: CRIT, weights: W,
  });
  assert(approx(r.score, (100 * 25 + 80 * 20) / 45, 1e-9), `got ${r.score}`);
  assert(r.missingKeys.join() === 'project', 'project should be flagged missing');
  assert(r.score > (100 * 25 + 80 * 20) / 70, 'missing data must not be scored as zero');
});

scoringSuite.it('breakdown parts add up exactly to the score shown', () => {
  const r = scoreStudent({
    entries: [
      { criterion_key: 'homework', earned: 3, possible: 5 },
      { criterion_key: 'attendance', earned: 5, possible: 5 },
      { criterion_key: 'project', earned: 71, possible: 100 },
    ],
    criteria: CRIT, weights: W,
  });
  assert(approx(r.parts.reduce((a, p) => a + p.points, 0), r.score, 1e-9), 'parts do not sum to the score');
  assert(approx(r.parts.reduce((a, p) => a + p.effectiveWeight, 0), 100, 1e-9), 'effective weights total 100');
});

/* ------------------------------------------------ commitment adjustment */

const factorSuite = suite('Commitment adjustment');
const TW = { work: 1, childcare: 1, eldercare: 1 };

factorSuite.it('combines hours by type into weighted hours', () => {
  assert(weightedHours({ work: 12, childcare: 6, eldercare: 0 }, TW) === 18, 'expected 18');
  assert(weightedHours({ work: 12, childcare: 6 }, { work: 1, childcare: 0.5, eldercare: 1 }) === 15, 'type weights apply');
});

factorSuite.it('follows the published factor table', () => {
  const f = (h) => commitmentFactor(h, 0.01, 1.25);
  assert(approx(f(0), 1.0), 'f(0) = 1.00');
  assert(approx(f(10), 1.1), 'f(10) = 1.10');
  assert(approx(f(20), 1.2), 'f(20) = 1.20');
  assert(approx(f(25), 1.25), 'f(25) = 1.25');
});

factorSuite.it('never exceeds the cap, whatever hours are entered', () => {
  for (const h of [26, 60, 120, 1000]) {
    assert(commitmentFactor(h, 0.01, 1.25) === 1.25, `cap broken at ${h} hours`);
  }
});

factorSuite.it('matches the worked example: raw 80, 18 hours → 94.4', () => {
  const h = weightedHours({ work: 12, childcare: 6, eldercare: 0 }, TW);
  const f = commitmentFactor(h, 0.01, 1.25);
  const { adjusted, capped } = adjust(80, f);
  assert(h === 18 && approx(f, 1.18), `got H=${h} f=${f}`);
  assert(approx(adjusted, 94.4, 1e-9), `got ${adjusted}`);
  assert(!capped, 'this example is not capped');
});

factorSuite.it('clips at 100 and says so: raw 92 at ×1.20 → 100', () => {
  const { adjusted, capped } = adjust(92, 1.2);
  assert(adjusted === 100, `got ${adjusted}`);
  assert(capped === true, 'the cap was not reported');
});

factorSuite.it('is neutral when nothing is entered or the baseline is not approved', () => {
  const none = resolveHours({ baseline: null, weekNumber: 5 });
  assert(weightedHours(none.hours, TW) === 0, 'no baseline must be neutral');
  const pending = resolveHours({ baseline: { status: 'pending', work_hours: 20, childcare_hours: 0, eldercare_hours: 0 }, weekNumber: 5 });
  assert(weightedHours(pending.hours, TW) === 0, 'a pending baseline must not count');
  assert(commitmentFactor(0, 0.01, 1.25) === 1, 'the neutral factor is 1.00');
});

factorSuite.it('respects the effective week chosen at approval', () => {
  const baseline = { status: 'approved', effective_from_week: 6, work_hours: 8, childcare_hours: 0, eldercare_hours: 0 };
  assert(weightedHours(resolveHours({ baseline, weekNumber: 5 }).hours, TW) === 0, 'earlier weeks keep a factor of 1.00');
  assert(weightedHours(resolveHours({ baseline, weekNumber: 6 }).hours, TW) === 8, 'the effective week counts');
});

factorSuite.it('lets a weekly update replace the baseline for one week only', () => {
  const baseline = { status: 'approved', effective_from_week: 1, work_hours: 6, childcare_hours: 4, eldercare_hours: 0 };
  const updates = [{ week_number: 10, work_hours: 20, childcare_hours: 4, eldercare_hours: 0, reversed_at: null }];
  assert(weightedHours(resolveHours({ baseline, weeklyUpdates: updates, weekNumber: 10 }).hours, TW) === 24, 'week 10 should use the update');
  assert(weightedHours(resolveHours({ baseline, weeklyUpdates: updates, weekNumber: 11 }).hours, TW) === 10, 'week 11 should fall back to the baseline');
});

factorSuite.it('ignores a reversed weekly update', () => {
  const baseline = { status: 'approved', effective_from_week: 1, work_hours: 10, childcare_hours: 0, eldercare_hours: 2 };
  const updates = [{ week_number: 9, work_hours: 46, childcare_hours: 0, eldercare_hours: 2, reversed_at: '2026-09-01T08:30:00Z' }];
  const r = resolveHours({ baseline, weeklyUpdates: updates, weekNumber: 9 });
  assert(weightedHours(r.hours, TW) === 12 && r.source === 'baseline', 'a reversal must restore the baseline');
});

factorSuite.it('averages weekly adjusted scores, so an average never exceeds 100', () => {
  assert(mean([100, 100, 100]) === 100, 'three capped weeks average to 100');
  assert(approx(mean([94.4, 100, 80]), (94.4 + 100 + 80) / 3), 'plain mean');
  assert(mean([]) === null, 'an empty window has no score');
});

/* ------------------------------------------------------------- ranking */

const rankSuite = suite('Ranking and ties');

rankSuite.it('ties share a rank and the next place skips (1, 1, 3)', () => {
  const ranked = rankRows([
    { student_id: 'a', display_name: 'A', score: 80, raw: 80 },
    { student_id: 'b', display_name: 'B', score: 80, raw: 80 },
    { student_id: 'c', display_name: 'C', score: 70, raw: 70 },
  ]);
  assert(ranked.map((r) => r.rank).join(',') === '1,1,3', ranked.map((r) => r.rank).join(','));
  assert(ranked[0].tied && ranked[1].tied && !ranked[2].tied, 'both tied rows are marked');
});

rankSuite.it('orders students capped at 100 by the higher raw score', () => {
  const ranked = rankRows([
    { student_id: 'a', display_name: 'A', score: 100, raw: 88 },
    { student_id: 'b', display_name: 'B', score: 100, raw: 96 },
  ]);
  assert(ranked[0].student_id === 'b', 'the higher raw score shows first');
  assert(ranked[0].rank === 1 && ranked[1].rank === 1, 'the rank is still shared');
});

rankSuite.it('falls through to the stated tie-breaker criteria', () => {
  const ranked = rankRows(
    [
      { student_id: 'a', display_name: 'A', score: 80, raw: 80, normalisedByKey: { attendance: 60 } },
      { student_id: 'b', display_name: 'B', score: 80, raw: 80, normalisedByKey: { attendance: 95 } },
    ],
    ['attendance'],
  );
  assert(ranked[0].student_id === 'b', 'higher attendance shows first');
});

rankSuite.it('reports the gap to the place above', () => {
  const ranked = rankRows([
    { student_id: 'a', display_name: 'A', score: 90, raw: 90 },
    { student_id: 'b', display_name: 'B', score: 84.5, raw: 84.5 },
  ]);
  assert(gapToNext(ranked, 1) === 5.5, 'expected 5.5');
  assert(gapToNext(ranked, 0) === null, 'the leader has no gap above');
});

rankSuite.it('rescales weights to total 100 while keeping proportions', () => {
  const w = normaliseWeights({ a: 10, b: 30 });
  assert(approx(w.a + w.b, 100), 'totals 100');
  assert(approx(w.b / w.a, 3), 'proportions kept');
});

rankSuite.it('switches display names for the privacy toggle', () => {
  const s = { display_name: 'Amara Okonkwo', nickname: 'Ammo' };
  assert(displayName(s, 'full') === 'Amara Okonkwo');
  assert(displayName(s, 'initials') === 'Amara O.');
  assert(displayName(s, 'nickname') === 'Ammo');
});

/* --------------------------------------------------------- risk engine */

const riskSuite = suite('Risk engine');

const weekOf = (n, raw, extra = {}) => ({
  week_number: n,
  raw,
  hasEntries: raw != null,
  byKey: { homework: { earned: 5, possible: 5 }, attendance: { earned: 3, possible: 3 }, participation: { earned: 15, possible: 15 }, ...extra },
});

riskSuite.it('maps the count of signals on to the stated levels', () => {
  assert(levelFor(0) === 'Not flagged');
  assert(levelFor(1) === 'Watch');
  assert(levelFor(2) === 'At risk');
  assert(levelFor(3) === 'High risk' && levelFor(5) === 'High risk');
});

riskSuite.it('flags a downward trend only after the threshold run', () => {
  const two = evaluateSignals({ weekly: [weekOf(1, 80), weekOf(2, 78), weekOf(3, 70)] });
  assert(!two.signals_on.includes('downward_trend'), 'two weeks of decline should not flag');
  const three = evaluateSignals({ weekly: [weekOf(1, 90), weekOf(2, 80), weekOf(3, 78), weekOf(4, 70)] });
  assert(three.signals_on.includes('downward_trend'), 'three weeks of decline should flag');
  const recovered = evaluateSignals({ weekly: [weekOf(1, 90), weekOf(2, 80), weekOf(3, 70), weekOf(4, 75)] });
  assert(!recovered.signals_on.includes('downward_trend'), 'a recovery breaks the run');
});

riskSuite.it('flags low engagement on any of its three reasons', () => {
  const attendance = evaluateSignals({ weekly: [weekOf(1, 70, { attendance: { earned: 1, possible: 3 } })] });
  assert(attendance.signals_on.includes('missed_engagement'), 'attendance under 70% should flag');
  const homework = evaluateSignals({
    weekly: [weekOf(1, 70, { homework: { earned: 0, possible: 5 } }), weekOf(2, 70, { homework: { earned: 0, possible: 5 } })],
  });
  assert(homework.signals_on.includes('missed_engagement'), 'two assignments not handed in should flag');
  const oneMissed = evaluateSignals({
    weekly: [weekOf(1, 70, { homework: { earned: 0, possible: 5 } }), weekOf(2, 70)],
  });
  assert(!oneMissed.signals_on.includes('missed_engagement'), 'one missed assignment is under the threshold');
  const partial = evaluateSignals({ weekly: [weekOf(1, 70, { homework: { earned: 3, possible: 5 } }), weekOf(2, 70, { homework: { earned: 4, possible: 5 } })] });
  assert(!partial.signals_on.includes('missed_engagement'), 'losing marks is not the same as not handing in');
  const participation = evaluateSignals({ weekly: [weekOf(1, 70, { participation: { earned: 3, possible: 15 } })] });
  assert(participation.signals_on.includes('missed_engagement'), 'participation under 50% should flag');
  const fine = evaluateSignals({ weekly: [weekOf(1, 70)] });
  assert(!fine.signals_on.includes('missed_engagement'), 'a clean week should not flag');
});

riskSuite.it('flags a projected grade under the pass threshold', () => {
  const low = evaluateSignals({ weekly: [weekOf(1, 55), weekOf(2, 58)] });
  assert(low.signals_on.includes('low_projected_grade'), 'an average of 56.5 is under 60');
  const ok = evaluateSignals({ weekly: [weekOf(1, 61), weekOf(2, 64)] });
  assert(!ok.signals_on.includes('low_projected_grade'), 'an average above 60 should not flag');
});

riskSuite.it('flags heavy commitments at the hour threshold, not below', () => {
  assert(evaluateSignals({ weekly: [weekOf(1, 80)], hours: 20 }).signals_on.includes('heavy_commitments'), '20 hours is at the threshold');
  assert(!evaluateSignals({ weekly: [weekOf(1, 80)], hours: 19.5 }).signals_on.includes('heavy_commitments'), '19.5 hours is under it');
});

riskSuite.it('flags a run of weeks with no entries', () => {
  const gap = evaluateSignals({ weekly: [weekOf(1, 80), weekOf(2, null), weekOf(3, null)] });
  assert(gap.signals_on.includes('missing_data'), 'two empty weeks should flag');
  const single = evaluateSignals({ weekly: [weekOf(1, 80), weekOf(2, null), weekOf(3, 78)] });
  assert(!single.signals_on.includes('missing_data'), 'one empty week should not flag');
});

riskSuite.it('every signal carries the data that triggered it', () => {
  const ev = evaluateSignals({ weekly: [weekOf(1, 70), weekOf(2, 60), weekOf(3, 50), weekOf(4, 40)], hours: 30 });
  assert(ev.signals.length === SIGNAL_KEYS.length, 'a signal is missing from the report');
  for (const sg of ev.signals) {
    assert(typeof sg.summary === 'string' && sg.summary.length > 0, `${sg.key} has no summary`);
    assert(Array.isArray(sg.evidence) && sg.evidence.length > 0, `${sg.key} has no evidence`);
  }
  assert(ev.level === 'High risk', `expected High risk, got ${ev.level}`);
});

riskSuite.it('honours a threshold change and a signal being turned off', () => {
  const weekly = [weekOf(1, 90), weekOf(2, 80), weekOf(3, 78)];
  assert(!evaluateSignals({ weekly }).signals_on.includes('downward_trend'), 'two declines under a threshold of three');
  assert(evaluateSignals({ weekly, thresholds: { declineWeeks: 2 } }).signals_on.includes('downward_trend'), 'a lower threshold should flag');
  const off = evaluateSignals({ weekly, thresholds: { declineWeeks: 2 }, active: { ...DEFAULT_ACTIVE_ALL, downward_trend: false } });
  assert(!off.signals_on.includes('downward_trend'), 'a signal turned off must never fire');
});

riskSuite.it('says which level a borderline student is one signal away from', () => {
  const one = evaluateSignals({ weekly: [weekOf(1, 80)], hours: 25 });
  assert(one.level === 'Watch' && one.oneAway === 'At risk', `${one.level} / ${one.oneAway}`);
});

riskSuite.it('describes what changed since the instructor last looked', () => {
  const flagged = { signals_on: ['heavy_commitments'] };
  const clear = { signals_on: [] };
  assert(diffState(clear, flagged) === 'new', 'newly flagged');
  assert(diffState(flagged, flagged) === 'still', 'still flagged');
  assert(diffState(flagged, clear) === 'cleared', 'recently cleared');
  assert(diffState(clear, clear) === 'quiet', 'never flagged');
  assert(diffState(null, flagged) === 'new', 'no prior reading counts as new');
});

const DEFAULT_ACTIVE_ALL = Object.fromEntries(SIGNAL_KEYS.map((k) => [k, true]));

/* ------------------------------------------------- DataSource contract */

const contractSuite = suite('Adapter contracts (toy)');

contractSuite.it('DataSource implements every read method in the interface', async () => {
  const src = createToySource();
  for (const m of ['listClasses', 'listStudents', 'listCriteria', 'listWeeks', 'getEntries']) {
    assert(typeof src[m] === 'function', `missing ${m}()`);
  }
});

contractSuite.it('AppStore implements every read/write method in the interface', async () => {
  const st = createToyAppStore();
  for (const m of ['getLeagueSettings', 'saveLeagueSettings', 'listBaselines', 'listWeeklyUpdates', 'getCommitments', 'getRiskSettings', 'saveRiskSettings', 'getRiskSnapshot', 'saveRiskSnapshot', 'addNote', 'listNotes', 'appendLog', 'listLog']) {
    assert(typeof st[m] === 'function', `missing ${m}()`);
  }
});

contractSuite.it('serves two classes of 24 students over 16 weeks', async () => {
  const src = createToySource();
  const classes = await src.listClasses('i1');
  assert(classes.length === 2, `got ${classes.length} classes`);
  assert((await src.listWeeks('t1')).length === WEEK_COUNT, 'weeks');
  for (const k of classes) {
    assert((await src.listStudents(k.id)).length === 24, `students in ${k.id}`);
    assert((await src.listCriteria(k.id)).length === 5, `criteria in ${k.id}`);
  }
});

contractSuite.it('keeps the two classes’ entries apart', async () => {
  const src = createToySource();
  const a = await src.getEntries({ classId: 'c1' });
  const b = await src.getEntries({ classId: 'c2' });
  const aIds = new Set((await src.listStudents('c1')).map((s) => s.id));
  assert(a.every((e) => aIds.has(e.student_id)), 'c1 entries reference a c1 student');
  assert(b.every((e) => !aIds.has(e.student_id)), 'a c2 entry leaked a c1 student');
});

contractSuite.it('gives each class its own criteria', async () => {
  const src = createToySource();
  const a = (await src.listCriteria('c1')).map((c) => c.key).join();
  const b = (await src.listCriteria('c2')).map((c) => c.key).join();
  assert(a !== b, 'both classes share one criteria set');
  assert(b.includes('reading'), 'the custom criterion is missing');
});

contractSuite.it('is reproducible across instances (same seed, same data)', async () => {
  const a = await createToySource().getEntries({ classId: 'c1' });
  const b = await createToySource().getEntries({ classId: 'c1' });
  assert(a.length === b.length && a.every((e, i) => e.earned === b[i].earned), 'entries differ between runs');
});

contractSuite.it('every entry references a known student, week and criterion', async () => {
  const src = createToySource();
  const [students, weeks, criteria, entries] = await Promise.all([
    src.listStudents('c1'), src.listWeeks('t1'), src.listCriteria('c1'), src.getEntries({ classId: 'c1' }),
  ]);
  const sids = new Set(students.map((s) => s.id));
  const wids = new Set(weeks.map((w) => w.id));
  const ckeys = new Set(criteria.map((c) => c.key));
  assert(entries.every((e) => sids.has(e.student_id) && wids.has(e.week_id) && ckeys.has(e.criterion_key)), 'dangling reference');
  assert(entries.every((e) => typeof e.earned === 'number' && e.earned >= 0 && e.earned <= e.possible), 'score out of bounds');
});

contractSuite.it('records nothing past the week in progress', async () => {
  const entries = await createToySource().getEntries({ classId: 'c1' });
  const maxWeek = Math.max(...entries.map((e) => Number(e.week_id.slice(1))));
  assert(maxWeek === DATA_THROUGH, `entries run to week ${maxWeek}`);
});

contractSuite.it('carries the seeded score edge cases', async () => {
  const src = createToySource();
  const students = await src.listStudents('c1');
  const entries = await src.getEntries({ classId: 'c1' });
  const perfect = entries.filter((e) => e.student_id === students[0].id && e.week_id === 'w5');
  assert(perfect.length && perfect.every((e) => e.earned === e.possible), 'no perfect week');
  const zero = entries.filter((e) => e.student_id === students[12].id && e.week_id === 'w6');
  assert(zero.length && zero.every((e) => e.earned === 0), 'no zero week');
  assert(!entries.some((e) => e.student_id === students[17].id && e.week_id === 'w7' && e.criterion_key === 'participation'), 'missing entry not seeded');
  assert(!entries.some((e) => e.student_id === students[23].id && ['w1', 'w2', 'w3'].includes(e.week_id)), 'the mid-semester joiner has early entries');
});

contractSuite.it('carries the seeded commitment edge cases', async () => {
  const st = createToyAppStore();
  const baselines = await st.listBaselines('c1');
  const statuses = new Set(baselines.map((b) => b.status));
  for (const s of ['approved', 'pending', 'rejected']) assert(statuses.has(s), `no ${s} baseline seeded`);
  assert(baselines.some((b) => b.effective_from_week > 1), 'no later effective week seeded');
  const updates = await st.listWeeklyUpdates('c1');
  assert(updates.some((u) => !u.reversed_at) && updates.some((u) => u.reversed_at), 'need one live and one reversed update');
});

/* ---------------------------------------------------- services layer */

const apiSuite = suite('Services layer');
const makeApi = (opts = {}) => createApi({ source: createToySource(), store: createToyAppStore(), latency: 'none', ...opts });

apiSuite.it('lists the instructor’s classes', async () => {
  const classes = await makeApi().listClasses('i1');
  assert(classes.length === 2 && classes.every((c) => c.instructor_id === 'i1'), 'class switcher has nothing to switch');
});

apiSuite.it('bootstraps with weeks, criteria, weights, parameters and a source label', async () => {
  const boot = await makeApi().getBootstrap('c1');
  assert(boot.weeks.length === WEEK_COUNT && boot.criteria.length === 5, 'shape');
  assert(Math.round(Object.values(boot.weights).reduce((a, b) => a + b, 0)) === 100, 'weights total 100');
  assert(boot.settings.cap === 1.25 && boot.settings.rate === 0.01, 'adjustment parameters missing');
  assert(boot.source.demo === true, 'demo data must be labelled');
  assert(boot.tieBreakers.length >= 1, 'the tie-breaker order must be stateable on screen');
});

apiSuite.it('returns a fully ranked table for a week', async () => {
  const api = makeApi();
  const boot = await api.getBootstrap();
  const res = await api.getRanking({ weekId: 'w5', weights: boot.weights });
  assert(res.rows.length === 24, `got ${res.rows.length} rows`);
  assert(res.rows[0].rank === 1, 'first row is rank 1');
  for (let i = 1; i < res.rows.length; i++) {
    assert(res.rows[i].score <= res.rows[i - 1].score + 1e-9, 'rows are not in descending score order');
    assert(res.rows[i].rank >= res.rows[i - 1].rank, 'ranks are not monotonic');
  }
  assert(res.rows.every((r) => r.score >= 0 && r.score <= 100), 'scores out of range');
});

apiSuite.it('no adjusted score anywhere exceeds 100', async () => {
  const api = makeApi();
  const boot = await api.getBootstrap();
  for (const mode of ['week', 'cumulative', 'rolling']) {
    for (const w of ['w5', 'w9', 'w12']) {
      const res = await api.getRanking({ weekId: w, windowMode: mode, weights: boot.weights });
      assert(res.rows.every((r) => r.score <= 100 + 1e-9), `${mode} ${w} broke the ceiling`);
    }
  }
});

apiSuite.it('applies the factor, and reports it with the hours behind it', async () => {
  const api = makeApi();
  const boot = await api.getBootstrap();
  const res = await api.getRanking({ weekId: 'w7', weights: boot.weights });
  const adjusted = res.rows.find((r) => r.factor > 1.0001);
  assert(adjusted, 'nobody has an adjustment — the seed is wrong');
  assert(adjusted.weighted_hours > 0, 'a factor above 1 needs hours behind it');
  assert(res.rows.every((r) => r.factor <= 1.25 + 1e-9), 'the cap leaked');
  const neutral = res.rows.find((r) => approx(r.factor, 1, 1e-9));
  assert(neutral && neutral.weighted_hours === 0, 'a neutral factor must mean no hours');
});

apiSuite.it('shows the cap biting in the seeded week', async () => {
  const api = makeApi();
  const boot = await api.getBootstrap();
  const res = await api.getRanking({ weekId: 'w5', weights: boot.weights });
  const capped = res.rows.filter((r) => r.capped);
  assert(capped.length >= 1, 'no capped score in week 5');
  assert(capped.every((r) => approx(r.score, 100, 1e-9)), 'a capped score must read 100');
});

apiSuite.it('a pending baseline has no effect on the table', async () => {
  const api = makeApi();
  const boot = await api.getBootstrap();
  const res = await api.getRanking({ weekId: 'w8', weights: boot.weights });
  const students = await createToySource().listStudents('c1');
  const pending = res.rows.find((r) => r.student_id === students[2].id);
  assert(pending && approx(pending.factor, 1, 1e-9), 'an unapproved baseline changed the score');
});

apiSuite.it('an approved baseline starts at its effective week, not before', async () => {
  const api = makeApi();
  const boot = await api.getBootstrap();
  const sid = (await createToySource().listStudents('c1'))[4].id;
  const before = await api.getRanking({ weekId: 'w5', weights: boot.weights });
  const after = await api.getRanking({ weekId: 'w6', weights: boot.weights });
  assert(approx(before.rows.find((r) => r.student_id === sid).factor, 1, 1e-9), 'week 5 should still be neutral');
  assert(after.rows.find((r) => r.student_id === sid).factor > 1, 'week 6 should carry the baseline');
});

apiSuite.it('produces the seeded tie as a shared rank in week 9', async () => {
  const api = makeApi();
  const boot = await api.getBootstrap();
  const res = await api.getRanking({ weekId: 'w9', weights: boot.weights });
  const tied = res.rows.filter((r) => r.tied);
  assert(tied.length >= 2, 'no tie found in the seeded week');
  assert(new Set(tied.map((r) => r.rank)).size < tied.length, 'tied rows do not share a rank');
});

apiSuite.it('measures rank movement against the previous week', async () => {
  const api = makeApi();
  const boot = await api.getBootstrap();
  const prev = await api.getRanking({ weekId: 'w4', weights: boot.weights });
  const now = await api.getRanking({ weekId: 'w5', weights: boot.weights });
  const prevRank = new Map(prev.rows.map((r) => [r.student_id, r.rank]));
  for (const r of now.rows) {
    if (r.rank_delta == null) continue;
    assert(prevRank.get(r.student_id) - r.rank === r.rank_delta, `wrong delta for ${r.student_id}`);
  }
  assert(now.rows.some((r) => r.rank_delta !== 0), 'nothing moved — suspicious');
});

apiSuite.it('gives a student who joined mid-semester no delta on their first week', async () => {
  const api = makeApi();
  const boot = await api.getBootstrap();
  const res = await api.getRanking({ weekId: 'w4', weights: boot.weights });
  const joiner = res.rows.find((r) => r.display_name === 'Isla Bennett');
  assert(joiner && joiner.rank_delta === null, 'a first appearance has no previous rank');
});

apiSuite.it('the three windows cover the weeks they say they do', async () => {
  const api = makeApi();
  const boot = await api.getBootstrap();
  const week = await api.getRanking({ weekId: 'w8', weights: boot.weights });
  const rolling = await api.getRanking({ weekId: 'w8', windowMode: 'rolling', rollingN: 4, weights: boot.weights });
  const cume = await api.getRanking({ weekId: 'w8', windowMode: 'cumulative', weights: boot.weights });
  assert(week.weekCount === 1 && rolling.weekCount === 4 && cume.weekCount === 8, `${week.weekCount}/${rolling.weekCount}/${cume.weekCount}`);
  const order = (r) => r.rows.map((x) => x.student_id).join();
  assert(order(week) !== order(rolling) && order(rolling) !== order(cume), 'the windows produce identical tables');
});

apiSuite.it('a rolling window is the mean of its weekly adjusted scores', async () => {
  const api = makeApi();
  const boot = await api.getBootstrap();
  const rolling = await api.getRanking({ weekId: 'w8', windowMode: 'rolling', rollingN: 4, weights: boot.weights });
  const row = rolling.rows[0];
  const ex = await api.getExplanation({ studentId: row.student_id, weekId: 'w8', windowMode: 'rolling', rollingN: 4, weights: boot.weights });
  assert(ex.weeks.length === 4, `got ${ex.weeks.length} weeks`);
  assert(approx(mean(ex.weeks.map((w) => w.adjusted)), row.score, 1e-9), 'the window score is not the weekly mean');
});

apiSuite.it('an early week’s rolling window is short, not padded', async () => {
  const api = makeApi();
  const res = await api.getRanking({ weekId: 'w2', windowMode: 'rolling', rollingN: 4 });
  assert(res.weekCount === 2, `got ${res.weekCount}`);
});

apiSuite.it('re-ranks when the weights change', async () => {
  const api = makeApi();
  const boot = await api.getBootstrap();
  const before = await api.getRanking({ weekId: 'w5', weights: boot.weights });
  const after = await api.getRanking({ weekId: 'w5', weights: { homework: 100, attendance: 0, participation: 0, project: 0, quizzes: 0 } });
  assert(before.rows.map((r) => r.student_id).join() !== after.rows.map((r) => r.student_id).join(), 'weights had no effect on the order');
  assert(Math.round(Object.values(after.weights).reduce((a, b) => a + b, 0)) === 100, 'returned weights total 100');
});

apiSuite.it('re-ranks when the adjustment parameters change', async () => {
  const api = makeApi();
  const boot = await api.getBootstrap();
  const before = await api.getRanking({ weekId: 'w7', weights: boot.weights });
  await api.saveSettings('c1', { rate: 0.05, cap: 2 });
  const after = await api.getRanking({ weekId: 'w7', weights: boot.weights });
  const b = before.rows.find((r) => r.weighted_hours > 0);
  const a = after.rows.find((r) => r.student_id === b.student_id);
  assert(a.factor > b.factor, 'a higher rate did not raise the factor');
});

apiSuite.it('single-criterion view scores exactly that criterion', async () => {
  const api = makeApi();
  const res = await api.getRanking({ weekId: 'w5', criteriaKeys: ['attendance'] });
  const ex = await api.getExplanation({ studentId: res.rows[0].student_id, weekId: 'w5', criteriaKeys: ['attendance'] });
  assert(ex.parts.length === 1 && ex.parts[0].key === 'attendance', 'other criteria leaked in');
  assert(approx(ex.raw, ex.parts[0].points, 1e-9), 'the raw score is not the single criterion');
});

apiSuite.it('explanation parts add up to the raw score, and the factor explains the rest', async () => {
  const api = makeApi();
  const boot = await api.getBootstrap();
  const res = await api.getRanking({ weekId: 'w7', weights: boot.weights });
  for (const row of res.rows.slice(0, 6)) {
    const ex = await api.getExplanation({ studentId: row.student_id, weekId: 'w7', weights: boot.weights });
    assert(approx(ex.parts.reduce((a, p) => a + p.points, 0), ex.raw, 1e-9), 'parts do not add to the raw score');
    assert(approx(ex.score, Math.min(100, ex.raw * ex.factor), 1e-9), 'adjusted ≠ min(100, raw × factor)');
    assert(approx(ex.score, row.score, 1e-9), 'the breakdown disagrees with the table');
    assert(approx(ex.weighted_hours, Object.keys(ex.typeWeights).reduce((s, k) => s + ex.typeWeights[k] * ex.hours[k], 0), 1e-9), 'the hours do not produce the weighted total');
  }
});

apiSuite.it('in a multi-week window the parts still add up to the week they describe', async () => {
  const api = makeApi();
  const boot = await api.getBootstrap();
  const res = await api.getRanking({ weekId: 'w11', windowMode: 'rolling', rollingN: 4, weights: boot.weights });
  for (const row of res.rows.slice(0, 5)) {
    const ex = await api.getExplanation({ studentId: row.student_id, weekId: 'w11', windowMode: 'rolling', rollingN: 4, weights: boot.weights });
    assert(approx(ex.parts.reduce((a, p) => a + p.points, 0), ex.focusRaw, 1e-9), 'parts do not add to the focus week’s raw score');
    assert(approx(ex.focusAdjusted, Math.min(100, ex.focusRaw * ex.weeks[ex.weeks.length - 1].factor), 1e-9), 'the focus week’s adjusted score does not follow from its own raw score');
    assert(approx(ex.score, mean(ex.weeks.map((w) => w.adjusted)), 1e-9), 'the ranked score is not the window mean');
  }
});

apiSuite.it('marks the missing entry rather than scoring it zero', async () => {
  const api = makeApi();
  const boot = await api.getBootstrap();
  const res = await api.getRanking({ weekId: 'w7', weights: boot.weights });
  const students = await createToySource().listStudents('c1');
  const row = res.rows.find((r) => r.student_id === students[17].id);
  assert(row.missing.includes('participation'), 'missing criterion not reported');
  const ex = await api.getExplanation({ studentId: row.student_id, weekId: 'w7', weights: boot.weights });
  const part = ex.parts.find((p) => p.key === 'participation');
  assert(part.missing && part.points === 0 && part.effectiveWeight === 0, 'missing part should carry no weight');
  assert(approx(ex.parts.reduce((a, p) => a + p.effectiveWeight, 0), 100, 1e-9), 'remaining weights not rescaled to 100');
});

apiSuite.it('reports the gap to the place above and below', async () => {
  const api = makeApi();
  const res = await api.getRanking({ weekId: 'w6' });
  assert(res.rows[0].gap_to_next === null, 'the leader has nobody above');
  assert(res.rows[res.rows.length - 1].gap_to_below === null, 'the last place has nobody below');
  const mid = res.rows[5];
  assert(mid.gap_to_next >= 0 && mid.gap_to_below >= 0, 'a mid-table row needs both gaps');
});

apiSuite.it('never sends a student another student’s raw score, factor or hours', async () => {
  const api = makeApi();
  const caller = { role: 'student', studentId: 's01', classId: 'c1' };
  const res = await api.getRanking({ weekId: 'w7', caller });
  for (const r of res.rows) {
    if (r.student_id === 's01') {
      assert(r.raw != null && r.factor != null, 'a student must see their own figures');
    } else {
      assert(r.raw === undefined && r.factor === undefined && r.weighted_hours === undefined, `leaked figures for ${r.student_id}`);
      assert(r.score != null && r.rank != null, 'the public row still needs rank and adjusted score');
    }
  }
});

apiSuite.it('refuses a student who asks for another student’s breakdown', async () => {
  const api = makeApi();
  let status = null;
  try {
    await api.getExplanation({ studentId: 's02', weekId: 'w5', caller: { role: 'student', studentId: 's01' } });
  } catch (err) {
    status = err instanceof ApiError ? err.status : 'wrong-error';
  }
  assert(status === 403, `expected 403, got ${status}`);
  const own = await api.getExplanation({ studentId: 's01', weekId: 'w5', caller: { role: 'student', studentId: 's01' } });
  assert(own.student_id === 's01', 'a student must still see their own breakdown');
});

apiSuite.it('refuses a student who asks for another class', async () => {
  const api = makeApi();
  let status = null;
  try {
    await api.getRanking({ classId: 'c2', weekId: 'w5', caller: { role: 'student', studentId: 's01', classId: 'c1' } });
  } catch (err) {
    status = err.status;
  }
  assert(status === 403, `expected 403, got ${status}`);
});

apiSuite.it('no ranking response carries another class’s students', async () => {
  const api = makeApi();
  const [a, b] = await Promise.all([
    api.getRanking({ classId: 'c1', weekId: 'w6' }),
    api.getRanking({ classId: 'c2', weekId: 'w6' }),
  ]);
  const aIds = new Set(a.rows.map((r) => r.student_id));
  assert(b.rows.every((r) => !aIds.has(r.student_id)), 'classes are mixed');
});

apiSuite.it('applies the privacy name mode server-side', async () => {
  const api = makeApi();
  const res = await api.getRanking({ weekId: 'w5', nameMode: 'initials' });
  assert(res.rows.every((r) => /^[^ ]+ [A-Z]\.$/.test(r.display_name)), `got ${res.rows[0].display_name}`);
});

apiSuite.it('publishes an explainer with no personal data in it', async () => {
  const ex = await makeApi().getExplainer('c1');
  assert(ex.table.length === 4 && approx(ex.table[3].factor, 1.25), 'the factor table is wrong');
  assert(approx(ex.example.adjusted, 94.4, 1e-9), `worked example got ${ex.example.adjusted}`);
  assert(!JSON.stringify(ex).includes('student'), 'the explainer mentions students');
});

apiSuite.it('returns a student’s own commitments and factor by week', async () => {
  const api = makeApi();
  const own = await api.getCommitments({ classId: 'c1', studentId: 's01', caller: { role: 'student', studentId: 's01' } });
  assert(own.byWeek.length === WEEK_COUNT, 'every week needs a factor');
  assert(approx(own.byWeek[0].factor, 1.18), `week 1 factor ${own.byWeek[0].factor}`);
  let status = null;
  try {
    await api.getCommitments({ classId: 'c1', studentId: 's02', caller: { role: 'student', studentId: 's01' } });
  } catch (err) { status = err.status; }
  assert(status === 403, 'a student read another student’s hours');
});

apiSuite.it('the digest surfaces a minority of the class, not the roster', async () => {
  const api = makeApi();
  const digest = await api.getDigest('i1');
  for (const g of digest.groups) {
    assert(g.rows.length > 0, `${g.className} flagged nobody at all`);
    assert(g.rows.length <= 12, `${g.className} flagged ${g.rows.length} of 24 — the digest discriminates nothing`);
  }
  const rec = await api.getRiskRecord({ classId: 'c1', studentId: 's01' });
  assert(rec.level === 'Not flagged', `the top student should not be flagged, got ${rec.level}`);
});

apiSuite.it('computes the digest from the data, grouped by class', async () => {
  const digest = await makeApi().getDigest('i1');
  assert(digest.groups.length === 2, 'the digest must cover every class');
  for (const g of digest.groups) {
    assert(g.week >= 1, 'no evaluation week');
    assert(g.rows.every((r) => ['new', 'still', 'cleared'].includes(r.status)), 'an unflagged student leaked into the digest');
    assert(g.rows.every((r) => r.level === levelFor(r.signals.length) || r.status === 'cleared'), 'the level does not follow the signal count');
  }
  assert(digest.groups.some((g) => g.rows.length > 0), 'nothing flagged anywhere — the engine is not running');
});

apiSuite.it('reads what changed against the stored snapshot on the second look', async () => {
  const api = makeApi();
  const first = await api.getDigest('i1');
  const second = await api.getDigest('i1');
  assert(first.groups[0].comparedWithStored === false, 'the first look has nothing stored to compare with');
  assert(second.groups[0].comparedWithStored === true, 'the second look should compare with the saved snapshot');
  assert(second.groups[0].rows.every((r) => r.status !== 'new'), 'nothing can be newly flagged twice in a row');
});

apiSuite.it('a risk record explains every signal and traces it to data', async () => {
  const api = makeApi();
  const digest = await api.getDigest('i1');
  const row = digest.groups.flatMap((g) => g.rows.map((r) => ({ ...r, classId: g.classId }))).find((r) => r.level === 'High risk' || r.level === 'At risk');
  assert(row, 'no flagged student to open');
  const rec = await api.getRiskRecord({ classId: row.classId, studentId: row.student_id });
  assert(rec.signals.length === 5, 'every signal must be reported, on or off');
  assert(rec.signals.filter((s) => s.on).length >= 2, 'the record disagrees with the digest');
  assert(rec.level === row.level, `record says ${rec.level}, digest said ${row.level}`);
  assert(rec.history.length > 1 && rec.history.every((h) => typeof h.level === 'string'), 'no level history');
  assert(rec.thresholds.projectedGrade === 60, 'the record must state the thresholds in force');
});

apiSuite.it('a threshold change re-evaluates the class', async () => {
  const api = makeApi();
  const before = await api.getRiskRecord({ classId: 'c1', studentId: 's13' });
  await api.saveRiskSettings('c1', { thresholds: { projectedGrade: 99, commitmentHours: 1 } });
  const after = await api.getRiskRecord({ classId: 'c1', studentId: 's13' });
  assert(after.signals.find((s) => s.key === 'low_projected_grade').on, 'a pass threshold of 99 should flag almost everyone');
  assert(after.thresholds.projectedGrade === 99, 'the new threshold is not reported');
  assert(before.level !== after.level || before.signals.filter((s) => s.on).length !== after.signals.filter((s) => s.on).length, 'the change had no effect');
});

apiSuite.it('thresholds are per class and do not cross over', async () => {
  const api = makeApi();
  await api.saveRiskSettings('c1', { thresholds: { commitmentHours: 5 } });
  const a = await api.getRiskSettings('c1');
  const b = await api.getRiskSettings('c2');
  assert(a.thresholds.commitmentHours === 5 && b.thresholds.commitmentHours === 20, `c2 threshold is ${b.thresholds.commitmentHours}`);
});

apiSuite.it('saves a note with the right instructor, student and time', async () => {
  const api = makeApi();
  const before = await api.getRiskRecord({ classId: 'c1', studentId: 's13' });
  const note = await api.addNote({ classId: 'c1', studentId: 's13', body: '  Called home 22 Sep  ' });
  assert(note.instructor_id === 'i1' && note.student_id === 's13', 'wrong attribution');
  assert(note.body === 'Called home 22 Sep', 'the body was not trimmed');
  assert(!Number.isNaN(Date.parse(note.created_at)), 'no timestamp');
  const after = await api.getRiskRecord({ classId: 'c1', studentId: 's13' });
  assert(after.notes.length === before.notes.length + 1, 'the note is not on the record');
});

apiSuite.it('refuses a note from anyone but an instructor, and an empty one', async () => {
  const api = makeApi();
  let a = null;
  let b = null;
  try { await api.addNote({ classId: 'c1', studentId: 's13', body: 'x', caller: { role: 'student', studentId: 's13' } }); } catch (e) { a = e.status; }
  try { await api.addNote({ classId: 'c1', studentId: 's13', body: '   ' }); } catch (e) { b = e.status; }
  assert(a === 403, `expected 403, got ${a}`);
  assert(b === 400, `expected 400, got ${b}`);
});

apiSuite.it('never sends a student the instructor’s notes', async () => {
  const api = makeApi();
  await api.addNote({ classId: 'c1', studentId: 's01', body: 'Private note about Amara' });
  const own = await api.getRiskRecord({ classId: 'c1', studentId: 's01', caller: { role: 'student', studentId: 's01' } });
  assert(own.notes.length === 0, 'a student received instructor notes');
  const standing = await api.getMyStanding({ classId: 'c1', studentId: 's01', caller: { role: 'student', studentId: 's01' } });
  assert(!('notes' in standing), 'My standing must not carry notes');
  assert(!JSON.stringify(standing).includes('Private note'), 'a note leaked into the student view');
});

apiSuite.it('My standing carries only the student’s own signals and no comparison', async () => {
  const api = makeApi();
  const standing = await api.getMyStanding({ classId: 'c1', studentId: 's02', caller: { role: 'student', studentId: 's02' } });
  assert(standing.student_id === 's02' && typeof standing.level === 'string', 'shape');
  assert(standing.signals.every((s) => s.on), 'only the signals that are on should be listed');
  assert(typeof standing.help === 'string' && standing.help.length > 0, 'no pointer to help');
  const text = JSON.stringify(standing).toLowerCase();
  for (const word of ['rank', 'classmate', 'fail', 'likely to']) {
    assert(!text.includes(word), `the student view should not mention "${word}"`);
  }
});

apiSuite.it('refuses a student who asks for another student’s standing', async () => {
  const api = makeApi();
  let status = null;
  try {
    await api.getMyStanding({ classId: 'c1', studentId: 's03', caller: { role: 'student', studentId: 's01' } });
  } catch (err) { status = err.status; }
  assert(status === 403, `expected 403, got ${status}`);
});

apiSuite.it('saves weights and parameters as app settings, and uses them as the default', async () => {
  const api = makeApi();
  await api.getBootstrap();
  await api.saveSettings('c1', { weights: { homework: 50, attendance: 10, participation: 10, project: 20, quizzes: 10 }, cap: 1.4 });
  const boot = await api.getBootstrap();
  assert(Math.round(boot.weights.homework) === 50, `got ${boot.weights.homework}`);
  assert(boot.settings.cap === 1.4, 'the cap did not persist');
});

apiSuite.it('settings are per class and do not cross over', async () => {
  const api = makeApi();
  await api.saveSettings('c1', { cap: 1.5 });
  const a = await api.getBootstrap('c1');
  const b = await api.getBootstrap('c2');
  assert(a.settings.cap === 1.5 && b.settings.cap === 1.25, `c2 cap is ${b.settings.cap}`);
});

apiSuite.it('serves the last good snapshot when the source is unreachable', async () => {
  const api = makeApi();
  await api.getBootstrap();
  api.__forceError('Source unreachable');
  const refreshed = await api.refresh();
  assert(refreshed.stale === true, 'a failed refresh should report stale data');
  const res = await api.getRanking({ weekId: 'w5' });
  assert(res.rows.length === 24, 'the table went blank instead of serving the cache');
  assert(res.stale === true, 'the response is not marked stale');
  assert(typeof res.lastUpdated === 'number', 'no "last updated" time to show');
  api.__clearError();
});

apiSuite.it('rate-limits the refresh button to one every 10 seconds', async () => {
  const api = makeApi();
  await api.getBootstrap();
  await api.refresh();
  let status = null;
  try { await api.refresh(); } catch (err) { status = err.status; }
  assert(status === 429, `expected 429, got ${status}`);
});

apiSuite.it('runs a data check and reports issues instead of failing', async () => {
  const boot = await makeApi().getBootstrap();
  assert(Array.isArray(boot.issues), 'issues must always be a list');
  assert(boot.issues.length === 0, 'the seeded data should be clean');
});

apiSuite.it('returns an empty table, not an error, for a week with no entries', async () => {
  const res = await makeApi().getRanking({ weekId: 'w15' });
  assert(Array.isArray(res.rows) && res.rows.length === 0, 'a future week should simply be empty');
});

apiSuite.it('ranks 24 students over 16 cumulative weeks well inside the budget', async () => {
  const api = makeApi();
  const boot = await api.getBootstrap();
  const t0 = performance.now();
  await api.getRanking({ weekId: 'w12', windowMode: 'cumulative', weights: boot.weights });
  const ms = performance.now() - t0;
  assert(ms < 500, `took ${ms.toFixed(0)}ms`);
});

export const SUITES = [scoringSuite, factorSuite, rankSuite, riskSuite, contractSuite, apiSuite];

export async function runAll() {
  const results = [];
  for (const s of SUITES) {
    const cases = [];
    for (const t of s.tests) {
      const t0 = performance.now();
      try {
        await t.fn();
        cases.push({ title: t.title, pass: true, ms: performance.now() - t0 });
      } catch (err) {
        cases.push({ title: t.title, pass: false, ms: performance.now() - t0, error: err.message });
      }
    }
    results.push({ name: s.name, cases });
  }
  return results;
}
