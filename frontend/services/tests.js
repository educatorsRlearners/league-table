// Test suites for the scoring logic and the services-layer contract.
// The contract suite is written against the DataSource / Api interfaces only —
// any adapter (toy today, Sheets later) must pass it unchanged.

import { normalise, scoreStudent, rankRows, gapToNext, normaliseWeights, displayName } from './scoring.js';
import { createApi, ApiError } from './api.js';
import { createToySource } from './mockSource.js';

const approx = (a, b, eps = 1e-9) => Math.abs(a - b) <= eps;

function suite(name) {
  const tests = [];
  return {
    name,
    tests,
    it(title, fn) { tests.push({ title, fn }); },
  };
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
    criteria: CRIT,
    weights: W,
  });
  // (100*25 + 80*20 + 60*25) / 70 = 78.571…
  assert(approx(r.score, (100 * 25 + 80 * 20 + 60 * 25) / 70, 1e-9), `got ${r.score}`);
});

scoringSuite.it('excludes a missing criterion and rescales the rest (not a zero)', () => {
  const r = scoreStudent({
    entries: [
      { criterion_key: 'homework', earned: 5, possible: 5 },
      { criterion_key: 'attendance', earned: 4, possible: 5 },
    ],
    criteria: CRIT,
    weights: W,
  });
  assert(approx(r.score, (100 * 25 + 80 * 20) / 45, 1e-9), `got ${r.score}`);
  assert(r.missingKeys.length === 1 && r.missingKeys[0] === 'project', 'project should be flagged missing');
  const zeroed = (100 * 25 + 80 * 20 + 0 * 25) / 70;
  assert(r.score > zeroed, 'missing data must not be scored as zero');
});

scoringSuite.it('breakdown parts add up exactly to the score shown', () => {
  const r = scoreStudent({
    entries: [
      { criterion_key: 'homework', earned: 3, possible: 5 },
      { criterion_key: 'attendance', earned: 5, possible: 5 },
      { criterion_key: 'project', earned: 71, possible: 100 },
    ],
    criteria: CRIT,
    weights: W,
  });
  const sum = r.parts.reduce((a, p) => a + p.points, 0);
  assert(approx(sum, r.score, 1e-9), `${sum} !== ${r.score}`);
  assert(approx(r.parts.reduce((a, p) => a + p.effectiveWeight, 0), 100, 1e-9), 'effective weights total 100');
});

scoringSuite.it('ties share a rank and the next place skips (1, 1, 3)', () => {
  const ranked = rankRows([
    { student_id: 'a', display_name: 'A', score: 80 },
    { student_id: 'b', display_name: 'B', score: 80 },
    { student_id: 'c', display_name: 'C', score: 70 },
  ]);
  assert(ranked.map((r) => r.rank).join(',') === '1,1,3', ranked.map((r) => r.rank).join(','));
  assert(ranked[0].tied && ranked[1].tied && !ranked[2].tied, 'both tied rows are marked');
});

scoringSuite.it('tie-breakers order the display without changing the shared rank', () => {
  const ranked = rankRows(
    [
      { student_id: 'a', display_name: 'A', score: 80, normalisedByKey: { attendance: 60 } },
      { student_id: 'b', display_name: 'B', score: 80, normalisedByKey: { attendance: 95 } },
    ],
    ['attendance'],
  );
  assert(ranked[0].student_id === 'b', 'higher attendance shows first');
  assert(ranked[0].rank === 1 && ranked[1].rank === 1, 'the rank is still shared');
});

scoringSuite.it('reports the gap to the place above', () => {
  const ranked = rankRows([
    { student_id: 'a', display_name: 'A', score: 90 },
    { student_id: 'b', display_name: 'B', score: 84.5 },
  ]);
  assert(gapToNext(ranked, 1) === 5.5, 'expected 5.5');
  assert(gapToNext(ranked, 0) === null, 'the leader has no gap above');
});

scoringSuite.it('rescales weights to total 100 while keeping proportions', () => {
  const w = normaliseWeights({ a: 10, b: 30 });
  assert(approx(w.a + w.b, 100), 'totals 100');
  assert(approx(w.b / w.a, 3), 'proportions kept');
});

scoringSuite.it('switches display names for the privacy toggle', () => {
  const s = { display_name: 'Amara Okonkwo', nickname: 'Ammo' };
  assert(displayName(s, 'full') === 'Amara Okonkwo');
  assert(displayName(s, 'initials') === 'Amara O.');
  assert(displayName(s, 'nickname') === 'Ammo');
});

/* ------------------------------------------------- DataSource contract */

const contractSuite = suite('DataSource contract (toy adapter)');

contractSuite.it('implements every read method in the interface', async () => {
  const src = createToySource();
  for (const m of ['listClasses', 'listStudents', 'listCriteria', 'listWeeks', 'getEntries']) {
    assert(typeof src[m] === 'function', `missing ${m}()`);
  }
});

contractSuite.it('returns 35 students, 10 weeks and 5 criteria', async () => {
  const src = createToySource();
  assert((await src.listStudents('c1')).length === 35, 'students');
  assert((await src.listWeeks('t1')).length === 10, 'weeks');
  assert((await src.listCriteria('c1')).length === 5, 'criteria');
});

contractSuite.it('is reproducible across instances (same seed, same data)', async () => {
  const a = await createToySource().getEntries({});
  const b = await createToySource().getEntries({});
  assert(a.length === b.length, 'entry counts differ');
  assert(a.every((e, i) => e.earned === b[i].earned), 'entries differ between runs');
});

contractSuite.it('every entry references a known student, week and criterion', async () => {
  const src = createToySource();
  const [students, weeks, criteria, entries] = await Promise.all([
    src.listStudents('c1'), src.listWeeks('t1'), src.listCriteria('c1'), src.getEntries({}),
  ]);
  const sids = new Set(students.map((s) => s.id));
  const wids = new Set(weeks.map((w) => w.id));
  const ckeys = new Set(criteria.map((c) => c.key));
  assert(entries.every((e) => sids.has(e.student_id) && wids.has(e.week_id) && ckeys.has(e.criterion_key)), 'dangling reference');
  assert(entries.every((e) => typeof e.earned === 'number' && e.earned >= 0 && e.earned <= e.possible), 'score out of bounds');
});

contractSuite.it('filters entries by week and criterion', async () => {
  const src = createToySource();
  const filtered = await src.getEntries({ weekIds: ['w3'], criterionKeys: ['homework'] });
  assert(filtered.length > 0, 'nothing returned');
  assert(filtered.every((e) => e.week_id === 'w3' && e.criterion_key === 'homework'), 'filter leaked');
});

contractSuite.it('carries the seeded edge cases (tie, missing entry, join mid-term)', async () => {
  const src = createToySource();
  const students = await src.listStudents('c1');
  const entries = await src.getEntries({});
  const rosa = students.find((s) => s.display_name === 'Rosa Ibarra');
  assert(!entries.some((e) => e.student_id === rosa.id && e.week_id === 'w7' && e.criterion_key === 'participation'), 'missing entry not seeded');
  const isla = students.find((s) => s.display_name === 'Isla Bennett');
  assert(!entries.some((e) => e.student_id === isla.id && ['w1', 'w2', 'w3'].includes(e.week_id)), 'mid-term joiner has early entries');
});

/* ---------------------------------------------------- services layer */

const apiSuite = suite('Services layer');
const makeApi = (opts = {}) => createApi({ source: createToySource(), latency: 'none', ...opts });

apiSuite.it('bootstraps with weeks, criteria, default weights and a source label', async () => {
  const boot = await makeApi().getBootstrap('c1');
  assert(boot.weeks.length === 10 && boot.criteria.length === 5, 'shape');
  assert(Math.round(Object.values(boot.weights).reduce((a, b) => a + b, 0)) === 100, 'weights total 100');
  assert(boot.source.demo === true, 'demo data must be labelled');
});

apiSuite.it('returns a fully ranked table for a week', async () => {
  const api = makeApi();
  const boot = await api.getBootstrap();
  const res = await api.getRanking({ weekId: 'w5', weights: boot.weights });
  assert(res.rows.length === 35, `got ${res.rows.length} rows`);
  assert(res.rows[0].rank === 1, 'first row is rank 1');
  for (let i = 1; i < res.rows.length; i++) {
    assert(res.rows[i].score <= res.rows[i - 1].score + 1e-9, 'rows are not in descending score order');
    assert(res.rows[i].rank >= res.rows[i - 1].rank, 'ranks are not monotonic');
  }
  assert(res.rows.every((r) => r.score >= 0 && r.score <= 100), 'scores out of range');
});

apiSuite.it('produces the seeded tie as a shared rank in week 9', async () => {
  const api = makeApi();
  const boot = await api.getBootstrap();
  const res = await api.getRanking({ weekId: 'w9', weights: boot.weights });
  const tied = res.rows.filter((r) => r.tied);
  assert(tied.length >= 2, 'no tie found in the seeded week');
  const ranks = tied.map((r) => r.rank);
  assert(new Set(ranks).size < ranks.length, 'tied rows do not share a rank');
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

apiSuite.it('gives a student who joined mid-term no delta on their first week', async () => {
  const api = makeApi();
  const boot = await api.getBootstrap();
  const res = await api.getRanking({ weekId: 'w4', weights: boot.weights });
  const joiner = res.rows.find((r) => r.display_name === 'Isla Bennett');
  assert(joiner && joiner.rank_delta === null, 'a first appearance has no previous rank');
});

apiSuite.it('cumulative window differs from the single week', async () => {
  const api = makeApi();
  const boot = await api.getBootstrap();
  const week = await api.getRanking({ weekId: 'w6', weights: boot.weights });
  const cume = await api.getRanking({ weekId: 'w6', windowMode: 'cumulative', weights: boot.weights });
  assert(cume.rows.length >= week.rows.length, 'cumulative should include at least as many students');
  assert(JSON.stringify(week.rows.map((r) => r.student_id)) !== JSON.stringify(cume.rows.map((r) => r.student_id)), 'cumulative order identical to the week');
});

apiSuite.it('re-ranks when the weights change', async () => {
  const api = makeApi();
  const boot = await api.getBootstrap();
  const before = await api.getRanking({ weekId: 'w5', weights: boot.weights });
  const after = await api.getRanking({ weekId: 'w5', weights: { homework: 100, attendance: 0, participation: 0, project: 0, quizzes: 0 } });
  const orderBefore = before.rows.map((r) => r.student_id).join(',');
  const orderAfter = after.rows.map((r) => r.student_id).join(',');
  assert(orderBefore !== orderAfter, 'weights had no effect on the order');
  assert(Math.round(Object.values(after.weights).reduce((a, b) => a + b, 0)) === 100, 'returned weights total 100');
});

apiSuite.it('single-criterion view scores exactly that criterion', async () => {
  const api = makeApi();
  const res = await api.getRanking({ weekId: 'w5', criteriaKeys: ['attendance'] });
  const ex = await api.getExplanation({ studentId: res.rows[0].student_id, weekId: 'w5', criteriaKeys: ['attendance'] });
  assert(ex.parts.length === 1 && ex.parts[0].key === 'attendance', 'other criteria leaked in');
  assert(approx(ex.score, ex.parts[0].points, 1e-9), 'score is not the single criterion');
});

apiSuite.it('explanation parts add up to the score on the table', async () => {
  const api = makeApi();
  const boot = await api.getBootstrap();
  const res = await api.getRanking({ weekId: 'w7', weights: boot.weights });
  for (const row of res.rows.slice(0, 5)) {
    const ex = await api.getExplanation({ studentId: row.student_id, weekId: 'w7', weights: boot.weights });
    const sum = ex.parts.reduce((a, p) => a + p.points, 0);
    assert(approx(sum, ex.score, 1e-9), `parts ${sum} !== score ${ex.score}`);
    assert(approx(ex.score, row.score, 1e-9), 'breakdown disagrees with the table');
  }
});

apiSuite.it('marks the missing entry rather than scoring it zero', async () => {
  const api = makeApi();
  const boot = await api.getBootstrap();
  const res = await api.getRanking({ weekId: 'w7', weights: boot.weights });
  const rosa = res.rows.find((r) => r.display_name === 'Rosa Ibarra');
  assert(rosa.missing.includes('participation'), 'missing criterion not reported');
  const ex = await api.getExplanation({ studentId: rosa.student_id, weekId: 'w7', weights: boot.weights });
  const part = ex.parts.find((p) => p.key === 'participation');
  assert(part.missing && part.points === 0 && part.effectiveWeight === 0, 'missing part should carry no weight');
  assert(approx(ex.parts.reduce((a, p) => a + p.effectiveWeight, 0), 100, 1e-9), 'remaining weights not rescaled to 100');
});

apiSuite.it('refuses a student who asks for another student\u2019s breakdown', async () => {
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

apiSuite.it('applies the privacy name mode server-side', async () => {
  const api = makeApi();
  const res = await api.getRanking({ weekId: 'w5', nameMode: 'initials' });
  assert(res.rows.every((r) => /^[^ ]+ [A-Z]\.$/.test(r.display_name)), `got ${res.rows[0].display_name}`);
});

apiSuite.it('saves weights as app settings and uses them as the default', async () => {
  const api = makeApi();
  await api.getBootstrap();
  await api.saveWeights('c1', { homework: 50, attendance: 10, participation: 10, project: 20, quizzes: 10 });
  const boot = await api.getBootstrap();
  assert(Math.round(boot.weights.homework) === 50, `got ${boot.weights.homework}`);
});

apiSuite.it('serves the last good snapshot when the source is unreachable', async () => {
  const api = makeApi();
  await api.getBootstrap();
  api.__forceError('Source unreachable');
  const refreshed = await api.refresh();
  assert(refreshed.stale === true, 'a failed refresh should report stale data');
  const res = await api.getRanking({ weekId: 'w5' });
  assert(res.rows.length === 35, 'the table went blank instead of serving the cache');
  assert(res.stale === true, 'the response is not marked stale');
  assert(typeof res.lastUpdated === 'number', 'no "last updated" time to show');
  api.__clearError();
});

apiSuite.it('rate-limits the refresh button to one every 10 seconds', async () => {
  const api = makeApi();
  await api.getBootstrap();
  await api.refresh();
  let status = null;
  try {
    await api.refresh();
  } catch (err) {
    status = err.status;
  }
  assert(status === 429, `expected 429, got ${status}`);
});

apiSuite.it('runs a data check and reports issues instead of failing', async () => {
  const api = makeApi();
  const boot = await api.getBootstrap();
  assert(Array.isArray(boot.issues), 'issues must always be a list');
  assert(boot.issues.length === 0, 'the seeded data should be clean');
});

apiSuite.it('ranks 35 students over 10 cumulative weeks well inside the budget', async () => {
  const api = makeApi();
  const boot = await api.getBootstrap();
  const t0 = performance.now();
  await api.getRanking({ weekId: 'w10', windowMode: 'cumulative', weights: boot.weights });
  const ms = performance.now() - t0;
  assert(ms < 500, `took ${ms.toFixed(0)}ms`);
});

export const SUITES = [scoringSuite, contractSuite, apiSuite];

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
