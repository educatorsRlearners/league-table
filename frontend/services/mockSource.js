// ToyAdapter — a seeded, reproducible DataSource implementation.
// Same read-only contract as the (future) SheetsAdapter:
//   listClasses, listStudents, listCriteria, listWeeks, getEntries
// No real student data ever lives here.

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

const NAMES = [
  'Amara Okonkwo', 'Ben Halvorsen', 'Cleo Marchetti', 'Dara Whitfield', 'Elif Demir',
  'Farid Nasser', 'Greta Lindqvist', 'Hugo Ferreira', 'Imani Blake', 'Jonas Reuter',
  'Kiara Mensah', 'Liam Donoghue', 'Mira Chandra', 'Nils Aaltonen', 'Odette Laurent',
  'Pablo Guerrero', 'Quinn Alderton', 'Rosa Ibarra', 'Samir Haddad', 'Tessa Vermeulen',
  'Ugo Bianchi', 'Vera Novak', 'Wes Carmichael', 'Xanthe Poulos', 'Yusuf Kaya',
  'Zara Mbeki', 'Aiden Rourke', 'Bianca Serrano', 'Caspar Wendt', 'Delphine Roy',
  'Eero Virtanen', 'Freya Ashdown', 'Gideon Stark', 'Hana Yamashita', 'Isla Bennett',
];

const NICKNAMES = {
  'Amara Okonkwo': 'Ammo', 'Ben Halvorsen': 'Benno', 'Cleo Marchetti': 'Clee',
  'Wes Carmichael': 'Wez', 'Zara Mbeki': 'Z', 'Isla Bennett': 'Izzy',
};

const CRITERIA = [
  { key: 'homework', label: 'Homework', unit: 'tasks on time', default_weight: 25, possible: 5, everyWeek: true },
  { key: 'attendance', label: 'Attendance', unit: 'sessions', default_weight: 20, possible: 5, everyWeek: true },
  { key: 'participation', label: 'Participation', unit: 'points', default_weight: 20, possible: 25, everyWeek: true },
  { key: 'project', label: 'Project scores', unit: 'marks', default_weight: 25, possible: 100, weeks: [2, 5, 8, 10] },
  { key: 'quizzes', label: 'Quizzes', unit: 'marks', default_weight: 10, possible: 20, everyWeek: true },
];

const CLASS = { id: 'c1', external_id: 'clever:sec-4821', name: 'Year 10 Physics · Set B', term_id: 't1' };

const WEEK_COUNT = 10;
const TERM_START = Date.UTC(2026, 0, 5);

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

function buildStudents() {
  return NAMES.map((name, i) => ({
    id: `s${String(i + 1).padStart(2, '0')}`,
    external_id: `clever:stu-${4000 + i}`,
    class_id: 'c1',
    display_name: name,
    nickname: NICKNAMES[name] || null,
    avatar_url: null,
    active: true,
    // Isla Bennett joins in week 4
    joined_week: name === 'Isla Bennett' ? 4 : 1,
  }));
}

function buildEntries(students, weeks) {
  const rng = mulberry32(20260920);
  // A stable per-student, per-criterion ability, plus week-to-week noise, so
  // the table has a believable order that still moves.
  const ability = {};
  for (const s of students) {
    ability[s.id] = {};
    const base = 0.45 + rng() * 0.5;
    for (const c of CRITERIA) ability[s.id][c.key] = Math.min(0.99, Math.max(0.15, base + (rng() - 0.5) * 0.3));
  }

  const entries = [];
  let n = 0;
  for (const w of weeks) {
    for (const c of CRITERIA) {
      if (!c.everyWeek && !c.weeks.includes(w.week_number)) continue;
      for (const s of students) {
        if (w.week_number < s.joined_week) continue; // joined mid-term: no entries
        const noise = (rng() - 0.5) * 0.28;
        let frac = Math.min(1, Math.max(0, ability[s.id][c.key] + noise));
        // Seeded edge cases
        if (s.display_name === 'Amara Okonkwo' && w.week_number === 5) frac = 1; // a perfect week
        if (s.display_name === 'Gideon Stark' && w.week_number === 6) frac = 0; // a zero week
        const earned = Math.round(frac * c.possible);
        // Missing entry: Rosa Ibarra has no participation recorded in week 7
        if (s.display_name === 'Rosa Ibarra' && c.key === 'participation' && w.week_number === 7) continue;
        entries.push({
          id: `e${++n}`,
          student_id: s.id,
          criterion_id: c.key,
          criterion_key: c.key,
          week_id: w.id,
          earned,
          possible: c.possible,
          recorded_at: `${w.end_date}T16:00:00Z`,
        });
      }
    }
  }

  // Seeded exact tie in week 9: Liam Donoghue mirrors Ben Halvorsen.
  const ben = students.find((s) => s.display_name === 'Ben Halvorsen');
  const liam = students.find((s) => s.display_name === 'Liam Donoghue');
  for (const e of entries) {
    if (e.week_id === 'w9' && e.student_id === liam.id) {
      const twin = entries.find(
        (x) => x.week_id === 'w9' && x.student_id === ben.id && x.criterion_key === e.criterion_key,
      );
      if (twin) e.earned = twin.earned;
    }
  }
  return entries;
}

export function createToySource() {
  const weeks = buildWeeks();
  const students = buildStudents();
  const entries = buildEntries(students, weeks);

  return {
    kind: 'toy',
    label: 'Demo data',
    async listClasses() {
      return [CLASS];
    },
    async listStudents(classId) {
      return students.filter((s) => s.class_id === classId);
    },
    async listCriteria() {
      return CRITERIA.map(({ key, label, unit, default_weight }, i) => ({
        id: key, class_id: 'c1', key, label, unit, default_weight, sort_order: i,
      }));
    },
    async listWeeks() {
      return weeks;
    },
    async getEntries({ weekIds, criterionKeys } = {}) {
      return entries.filter(
        (e) =>
          (!weekIds || weekIds.includes(e.week_id)) &&
          (!criterionKeys || criterionKeys.includes(e.criterion_key)),
      );
    },
    /** Demo accounts, so role rules can be exercised without real people. */
    async listAccounts() {
      return [
        { id: 'a1', role: 'teacher', student_id: null, external_id: 'demo:teacher' },
        { id: 'a2', role: 'student', student_id: 's01', external_id: 'demo:amara' },
        { id: 'a3', role: 'student', student_id: 's18', external_id: 'demo:rosa' },
      ];
    },
  };
}

export const TOY_FIXTURES = { CLASS, CRITERIA, WEEK_COUNT, NAMES };
