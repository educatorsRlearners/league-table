// Toy adapters — seeded and reproducible.
//
//   createToySource()   → DataSource   (read-only scores, per class)
//   createToyAppStore() → AppStore     (league settings, commitments, log, risk)
//
// Both honour the same contracts as the real adapters (SheetsAdapter /
// SqliteStore) so swapping them changes no code above the services layer.
// No real student data ever lives here.

import { DEFAULT_THRESHOLDS, DEFAULT_ACTIVE } from './risk.js';

function mulberry32(seed) {
  let a = seed >>> 0;
  return function () {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export const CLASSES = [
  { id: 'c1', instructor_id: 'i1', external_id: 'univ:PHYS-204-A', name: 'PHYS 204 · Mechanics', term_id: 't1', sheet_id: 'sheet-phys204' },
  { id: 'c2', instructor_id: 'i1', external_id: 'univ:DATA-118-B', name: 'DATA 118 · Intro to Data', term_id: 't1', sheet_id: 'sheet-data118' },
];

const NAMES = {
  c1: [
    'Amara Okonkwo', 'Ben Halvorsen', 'Cleo Marchetti', 'Dara Whitfield', 'Elif Demir',
    'Farid Nasser', 'Greta Lindqvist', 'Hugo Ferreira', 'Imani Blake', 'Jonas Reuter',
    'Kiara Mensah', 'Liam Donoghue', 'Mira Chandra', 'Nils Aaltonen', 'Odette Laurent',
    'Pablo Guerrero', 'Quinn Alderton', 'Rosa Ibarra', 'Samir Haddad', 'Tessa Vermeulen',
    'Ugo Bianchi', 'Vera Novak', 'Wes Carmichael', 'Isla Bennett',
  ],
  c2: [
    'Adaeze Nwosu', 'Bruno Kessler', 'Camila Duarte', 'Dmitri Volkov', 'Esme Fairbairn',
    'Felix Adeyemi', 'Gaia Russo', 'Henrik Solberg', 'Ines Cabrera', 'Joon-ho Park',
    'Kavya Raman', 'Lucien Berger', 'Maeve Dolan', 'Noor Rashid', 'Otto Lindgren',
    'Priya Venkat', 'Rafael Costa', 'Saoirse Kelleher', 'Tomas Oravec', 'Ula Sienkiewicz',
    'Viktor Petrov', 'Wren Abbott', 'Yara El-Amin', 'Zoltan Varga',
  ],
};

const NICKNAMES = {
  'Amara Okonkwo': 'Ammo', 'Ben Halvorsen': 'Benno', 'Cleo Marchetti': 'Clee',
  'Wes Carmichael': 'Wez', 'Isla Bennett': 'Izzy', 'Liam Donoghue': 'Donny',
  'Adaeze Nwosu': 'Ada', 'Joon-ho Park': 'JP', 'Saoirse Kelleher': 'Sersh',
  'Zoltan Varga': 'Zolt', 'Wren Abbott': 'Wrennie',
};

const CRITERIA = {
  c1: [
    { key: 'homework', label: 'Homework', unit: 'tasks on time', default_weight: 25, possible: 5, everyWeek: true },
    { key: 'attendance', label: 'Attendance', unit: 'sessions', default_weight: 20, possible: 3, everyWeek: true },
    { key: 'participation', label: 'Participation', unit: 'points', default_weight: 20, possible: 15, everyWeek: true },
    { key: 'project', label: 'Project scores', unit: 'marks', default_weight: 25, weeks: [3, 7, 11, 15], possible: 100 },
    { key: 'quizzes', label: 'Quizzes', unit: 'marks', default_weight: 10, possible: 20, everyWeek: true },
  ],
  // A second class with its own criteria, including a custom one.
  c2: [
    { key: 'homework', label: 'Problem sets', unit: 'sets on time', default_weight: 30, possible: 4, everyWeek: true },
    { key: 'attendance', label: 'Attendance', unit: 'sessions', default_weight: 15, possible: 2, everyWeek: true },
    { key: 'participation', label: 'Participation', unit: 'points', default_weight: 15, possible: 10, everyWeek: true },
    { key: 'project', label: 'Project scores', unit: 'marks', default_weight: 25, weeks: [5, 10, 15], possible: 100 },
    { key: 'reading', label: 'Reading log', unit: 'entries', default_weight: 15, possible: 3, everyWeek: true },
  ],
};

export const WEEK_COUNT = 16;
/** Entries exist through this week; week 12 is the one in progress. */
export const DATA_THROUGH = 12;
const PARTIAL_WEEK = 12;
const PARTIAL_KEYS = ['homework', 'attendance'];
const TERM_START = Date.UTC(2026, 6, 6); // Monday 6 July 2026 → week 12 is 21–25 Sep

function buildWeeks() {
  return Array.from({ length: WEEK_COUNT }, (_, i) => {
    const start = new Date(TERM_START + i * 7 * 86400000);
    const end = new Date(TERM_START + (i * 7 + 4) * 86400000);
    return {
      id: `w${i + 1}`,
      term_id: 't1',
      week_number: i + 1,
      start_date: start.toISOString().slice(0, 10),
      end_date: end.toISOString().slice(0, 10),
    };
  });
}

function buildStudents(classId) {
  const prefix = classId === 'c1' ? 's' : 't';
  return NAMES[classId].map((name, i) => ({
    id: `${prefix}${String(i + 1).padStart(2, '0')}`,
    external_id: `univ:stu-${(classId === 'c1' ? 4000 : 5000) + i}`,
    class_id: classId,
    display_name: name,
    nickname: NICKNAMES[name] || null,
    avatar_url: null,
    active: true,
    // index 23 joins in week 4
    joined_week: i === 23 ? 4 : 1,
  }));
}

function buildEntries(classId, students, weeks) {
  const criteria = CRITERIA[classId];
  const rng = mulberry32(classId === 'c1' ? 20260706 : 20260707);
  const ability = {};
  students.forEach((s, i) => {
    ability[s.id] = {};
    // Indices 0 and 1 are strong, so the cap and the cap-tie are reachable.
    const base = i <= 1 ? 0.9 : 0.55 + rng() * 0.42;
    for (const c of criteria) {
      ability[s.id][c.key] = Math.min(0.99, Math.max(0.12, base + (rng() - 0.5) * 0.28));
    }
  });

  const entries = [];
  let n = 0;
  for (const w of weeks) {
    if (w.week_number > DATA_THROUGH) continue; // weeks 13–16 not yet recorded
    for (const c of criteria) {
      if (!c.everyWeek && !c.weeks.includes(w.week_number)) continue;
      if (w.week_number === PARTIAL_WEEK && !PARTIAL_KEYS.includes(c.key)) continue;
      students.forEach((s, i) => {
        if (w.week_number < s.joined_week) return;
        const noise = (rng() - 0.5) * 0.26;
        let frac = Math.min(1, Math.max(0, ability[s.id][c.key] + noise));
        if (i === 0 && w.week_number === 5) frac = 1;     // a perfect week
        if (i === 1 && w.week_number === 5) frac = 0.92;  // raw 92 × cap 1.25 → clipped to 100
        if (i === 12 && w.week_number === 6) frac = 0;    // a zero week
        if (i === 17 && c.key === 'participation' && w.week_number === 7) return; // a missing entry
        entries.push({
          id: `${classId}-e${++n}`,
          student_id: s.id,
          criterion_id: c.key,
          criterion_key: c.key,
          week_id: w.id,
          earned: Math.round(frac * c.possible),
          possible: c.possible,
          recorded_at: `${w.end_date}T16:00:00Z`,
        });
      });
    }
  }

  // An exact tie in week 9 between two students who report no commitments,
  // so the tie survives the adjustment factor.
  const a = students[10];
  const b = students[11];
  for (const e of entries) {
    if (e.week_id === 'w9' && e.student_id === b.id) {
      const twin = entries.find((x) => x.week_id === 'w9' && x.student_id === a.id && x.criterion_key === e.criterion_key);
      if (twin) e.earned = twin.earned;
    }
  }
  return entries;
}

export function createToySource() {
  const weeks = buildWeeks();
  const byClass = Object.fromEntries(
    CLASSES.map((k) => {
      const students = buildStudents(k.id);
      return [k.id, { students, entries: buildEntries(k.id, students, weeks) }];
    }),
  );

  return {
    kind: 'toy',
    label: 'Demo data',
    async listClasses(instructorId = 'i1') {
      return CLASSES.filter((c) => c.instructor_id === instructorId);
    },
    async listStudents(classId) {
      return byClass[classId] ? byClass[classId].students : [];
    },
    async listCriteria(classId) {
      return (CRITERIA[classId] || []).map(({ key, label, unit, default_weight }, i) => ({
        id: `${classId}-${key}`, class_id: classId, key, label, unit, default_weight, sort_order: i,
      }));
    },
    async listWeeks() {
      return weeks;
    },
    async getEntries({ classId = 'c1', weekIds, criterionKeys } = {}) {
      const src = byClass[classId];
      if (!src) return [];
      return src.entries.filter(
        (e) =>
          (!weekIds || weekIds.includes(e.week_id)) &&
          (!criterionKeys || criterionKeys.includes(e.criterion_key)),
      );
    },
    async listAccounts() {
      return [
        { id: 'a1', role: 'instructor', student_id: null, class_ids: ['c1', 'c2'], external_id: 'demo:instructor' },
        { id: 'a2', role: 'student', student_id: 's01', class_ids: ['c1'], external_id: 'demo:amara' },
        { id: 'a3', role: 'student', student_id: 's18', class_ids: ['c1'], external_id: 'demo:rosa' },
        { id: 'a4', role: 'student', student_id: 't03', class_ids: ['c2'], external_id: 'demo:camila' },
      ];
    },
  };
}

/* ------------------------------------------------------------- AppStore */

const DEFAULT_SETTINGS = () => ({
  typeWeights: { work: 1, childcare: 1, eldercare: 1 },
  rate: 0.01,
  cap: 1.25,
  tieBreakers: ['attendance', 'homework'],
});

/**
 * The commitment seed covers: no entry, a pending baseline, an approved
 * baseline, a factor that reaches the cap, a later effective week, a weekly
 * update, a reversed update and a rejected baseline.
 */
function seedCommitments(classId) {
  const p = classId === 'c1' ? 's' : 't';
  const id = (i) => `${p}${String(i + 1).padStart(2, '0')}`;
  const baselines = [
    { id: `${classId}-b1`, student_id: id(0), work_hours: 12, childcare_hours: 6, eldercare_hours: 0, status: 'approved', effective_from_week: 1, submitted_at: '2026-07-07T09:12:00Z', decided_by: 'i1', decided_at: '2026-07-07T17:40:00Z' },
    { id: `${classId}-b2`, student_id: id(1), work_hours: 30, childcare_hours: 10, eldercare_hours: 5, status: 'approved', effective_from_week: 1, submitted_at: '2026-07-07T10:02:00Z', decided_by: 'i1', decided_at: '2026-07-08T08:15:00Z' },
    { id: `${classId}-b3`, student_id: id(2), work_hours: 10, childcare_hours: 0, eldercare_hours: 4, status: 'pending', effective_from_week: null, submitted_at: '2026-09-18T20:31:00Z', decided_by: null, decided_at: null },
    { id: `${classId}-b4`, student_id: id(3), work_hours: 40, childcare_hours: 20, eldercare_hours: 10, status: 'rejected', effective_from_week: null, submitted_at: '2026-08-02T22:05:00Z', decided_by: 'i1', decided_at: '2026-08-03T09:00:00Z' },
    { id: `${classId}-b5`, student_id: id(4), work_hours: 8, childcare_hours: 0, eldercare_hours: 0, status: 'approved', effective_from_week: 6, submitted_at: '2026-08-08T11:20:00Z', decided_by: 'i1', decided_at: '2026-08-09T10:00:00Z' },
    { id: `${classId}-b6`, student_id: id(5), work_hours: 6, childcare_hours: 4, eldercare_hours: 0, status: 'approved', effective_from_week: 1, submitted_at: '2026-07-06T18:44:00Z', decided_by: 'i1', decided_at: '2026-07-07T17:41:00Z' },
    { id: `${classId}-b7`, student_id: id(6), work_hours: 10, childcare_hours: 0, eldercare_hours: 2, status: 'approved', effective_from_week: 1, submitted_at: '2026-07-06T19:10:00Z', decided_by: 'i1', decided_at: '2026-07-07T17:42:00Z' },
  ];
  const weeklyUpdates = [
    { id: `${classId}-u1`, student_id: id(5), week_id: 'w10', week_number: 10, work_hours: 20, childcare_hours: 4, eldercare_hours: 0, entered_at: '2026-09-07T21:00:00Z', reversed_by: null, reversed_at: null },
    { id: `${classId}-u2`, student_id: id(6), week_id: 'w9', week_number: 9, work_hours: 46, childcare_hours: 0, eldercare_hours: 2, entered_at: '2026-08-31T23:12:00Z', reversed_by: 'i1', reversed_at: '2026-09-01T08:30:00Z' },
  ];
  return { baselines, weeklyUpdates };
}

/** Per-class risk settings start at the spec's placeholder thresholds. */
function seedRiskSettings() {
  return { thresholds: { ...DEFAULT_THRESHOLDS }, active: { ...DEFAULT_ACTIVE } };
}

/** One prior piece of outreach, so the notes log is not empty on first open. */
function seedNotes(classId) {
  const p = classId === 'c1' ? 's' : 't';
  if (classId !== 'c1') return [];
  return [
    { id: 'n1', instructor_id: 'i1', class_id: classId, student_id: `${p}13`, body: 'Emailed 14 Sep about the two missed problem sets. No reply yet.', created_at: '2026-09-14T11:20:00Z' },
    { id: 'n2', instructor_id: 'i1', class_id: classId, student_id: `${p}13`, body: 'Met in office hours 18 Sep. Shift pattern changed at work. Follow up in two weeks.', created_at: '2026-09-18T15:05:00Z' },
  ];
}

export function createToyAppStore() {
  const settings = Object.fromEntries(CLASSES.map((c) => [c.id, DEFAULT_SETTINGS()]));
  const weights = {};
  const commitments = Object.fromEntries(CLASSES.map((c) => [c.id, seedCommitments(c.id)]));
  const riskSettings = Object.fromEntries(CLASSES.map((c) => [c.id, seedRiskSettings()]));
  const riskSnapshots = new Map();
  const notes = CLASSES.flatMap((c) => seedNotes(c.id));
  const log = [
    { id: 'l1', actor_id: 'i1', action: 'baseline.approve', student_id: 's01', week_id: 'w1', old_values: null, new_values: { effective_from_week: 1 }, at: '2026-07-07T17:40:00Z' },
    { id: 'l2', actor_id: 's06', action: 'weekly.set', student_id: 's06', week_id: 'w10', old_values: { work_hours: 6 }, new_values: { work_hours: 20 }, at: '2026-09-07T21:00:00Z' },
    { id: 'l3', actor_id: 'i1', action: 'weekly.reverse', student_id: 's07', week_id: 'w9', old_values: { work_hours: 46 }, new_values: { work_hours: 10 }, at: '2026-09-01T08:30:00Z' },
  ];

  return {
    kind: 'memory',
    label: 'In memory',
    async getLeagueSettings(classId) {
      return { ...settings[classId], weights: weights[classId] || null };
    },
    async saveLeagueSettings(classId, patch) {
      if (patch.weights) weights[classId] = patch.weights;
      const { weights: _w, ...rest } = patch;
      settings[classId] = { ...settings[classId], ...rest };
      return this.getLeagueSettings(classId);
    },
    async listBaselines(classId) {
      return commitments[classId].baselines;
    },
    async listWeeklyUpdates(classId) {
      return commitments[classId].weeklyUpdates;
    },
    async getCommitments(classId, studentId) {
      const c = commitments[classId];
      return {
        baseline: c.baselines.find((b) => b.student_id === studentId && b.status !== 'superseded') || null,
        weeklyUpdates: c.weeklyUpdates.filter((u) => u.student_id === studentId),
      };
    },
    async getRiskSettings(classId) {
      return riskSettings[classId];
    },
    async saveRiskSettings(classId, patch) {
      riskSettings[classId] = {
        thresholds: { ...riskSettings[classId].thresholds, ...(patch.thresholds || {}) },
        active: { ...riskSettings[classId].active, ...(patch.active || {}) },
      };
      return riskSettings[classId];
    },
    /** What the instructor saw last time, so the digest can say what changed. */
    async getRiskSnapshot(classId) {
      return riskSnapshots.get(classId) || null;
    },
    async saveRiskSnapshot(classId, snapshot) {
      riskSnapshots.set(classId, snapshot);
      return snapshot;
    },
    async addNote({ classId, studentId, instructorId = 'i1', body }) {
      const note = {
        id: `n${notes.length + 1}`,
        instructor_id: instructorId,
        class_id: classId,
        student_id: studentId,
        body,
        created_at: new Date().toISOString(),
      };
      notes.push(note);
      return note;
    },
    /** Notes are private to the instructor who wrote them. */
    async listNotes(classId, studentId, instructorId = 'i1') {
      return notes.filter(
        (n) => n.class_id === classId && n.instructor_id === instructorId && (!studentId || n.student_id === studentId),
      );
    },
    async appendLog(entry) {
      log.push({ id: `l${log.length + 1}`, at: new Date().toISOString(), ...entry });
      return log[log.length - 1];
    },
    async listLog(classId) {
      return log;
    },
  };
}

export const TOY_FIXTURES = { CLASSES, CRITERIA, WEEK_COUNT, DATA_THROUGH, NAMES };
