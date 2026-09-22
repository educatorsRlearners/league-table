// The real backend client. Same interface as createApi() in api.js, but every
// call is an HTTP request to the FastAPI service described in ../../openapi.yaml,
// so scoring, ranking and role checks all happen on the server.
//
// Auth is a Bearer token per openapi.yaml's `bearerAuth` scheme. The backend's
// demo auth (backend/app/auth.py) accepts an instructor token ('i1') and bare
// student ids ('s01', 't03', ...) with no login flow, so the token for a call
// is derived directly from the `caller` object already threaded through every
// api.js method — no separate sign-in step is needed.

export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

function tokenFor(caller) {
  if (caller && caller.role === 'student' && caller.studentId) return caller.studentId;
  return 'i1';
}

/** Turn FastAPI's error body (a string `detail`, or a validation error list) into a message. */
function messageFrom(body, status) {
  const detail = body && body.detail;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail) && detail.length) {
    return detail
      .map((d) => {
        const field = (d.loc || []).filter((part) => !['query', 'body', 'path'].includes(part)).join('.');
        return field ? `${field}: ${d.msg}` : d.msg;
      })
      .join('; ');
  }
  if (typeof body?.message === 'string') return body.message;
  return `Request failed (${status}).`;
}

/** createHttpApi({ baseUrl, fetch }) */
export function createHttpApi({ baseUrl = '', fetch: fetchImpl } = {}) {
  const doFetch = (...args) => (fetchImpl || globalThis.fetch)(...args);

  async function send(method, path, { query, body, caller } = {}) {
    const params = new URLSearchParams();
    for (const [key, value] of Object.entries(query || {})) {
      if (value === undefined || value === null || value === '') continue;
      if (Array.isArray(value)) value.forEach((v) => params.append(key, v));
      else params.set(key, value);
    }
    const qs = params.toString();
    const init = {
      method,
      headers: { Authorization: `Bearer ${tokenFor(caller)}` },
    };
    if (body !== undefined) {
      init.headers['Content-Type'] = 'application/json';
      init.body = JSON.stringify(body);
    }

    let res;
    try {
      res = await doFetch(`${baseUrl}${path}${qs ? `?${qs}` : ''}`, init);
    } catch {
      throw new ApiError('Could not reach the server.', 0);
    }
    if (!res.ok) {
      const errBody = await res.json().catch(() => null);
      throw new ApiError(messageFrom(errBody, res.status), res.status);
    }
    return res.status === 204 ? null : res.json();
  }

  const viewQuery = ({ weekId, windowMode = 'week', rollingN, criteriaKeys, weights, nameMode = 'full' }) => ({
    week: weekId,
    window: windowMode,
    rollingN,
    criteria: criteriaKeys && criteriaKeys.length ? criteriaKeys.join(',') : undefined,
    weights: weights ? JSON.stringify(weights) : undefined,
    nameMode,
  });

  return {
    describeSource() {
      return { kind: 'http', label: 'Live backend', demo: true, store: 'FastAPI' };
    },

    /** GET /classes */
    listClasses: (instructorId = 'i1') =>
      send('GET', '/classes', { query: { instructor_id: instructorId }, caller: { role: 'instructor' } }),

    /** GET /classes/{id}/bootstrap */
    getBootstrap: (classId = 'c1') =>
      send('GET', `/classes/${classId}/bootstrap`, { caller: { role: 'instructor' } }),

    /** GET /classes/{id}/ranking */
    getRanking: ({ classId = 'c1', caller = { role: 'instructor' }, ...view }) =>
      send('GET', `/classes/${classId}/ranking`, { query: viewQuery(view), caller }),

    /** GET /classes/{id}/students/{sid}/explanation */
    getExplanation: ({ classId = 'c1', studentId, caller = { role: 'instructor' }, ...view }) =>
      send('GET', `/classes/${classId}/students/${encodeURIComponent(studentId)}/explanation`, {
        query: viewQuery(view),
        caller,
      }),

    /** GET /classes/{id}/explainer */
    getExplainer: (classId = 'c1') =>
      send('GET', `/classes/${classId}/explainer`, { caller: { role: 'instructor' } }),

    /** GET /me/commitments */
    getCommitments: ({ classId = 'c1', studentId, caller = { role: 'instructor' } }) =>
      send('GET', '/me/commitments', { query: { classId, studentId }, caller }),

    /** GET /instructor/digest */
    getDigest: (instructorId = 'i1') =>
      send('GET', '/instructor/digest', { query: { instructorId }, caller: { role: 'instructor' } }),

    /** GET /classes/{id}/students/{sid}/risk */
    getRiskRecord: ({ classId = 'c1', studentId, caller = { role: 'instructor' } }) =>
      send('GET', `/classes/${classId}/students/${encodeURIComponent(studentId)}/risk`, { caller }),

    /** POST /classes/{id}/students/{sid}/notes */
    addNote: ({ classId = 'c1', studentId, body, caller = { role: 'instructor' } }) =>
      send('POST', `/classes/${classId}/students/${encodeURIComponent(studentId)}/notes`, {
        body: { body },
        caller,
      }),

    /** GET /classes/{id}/risk-settings */
    getRiskSettings: (classId = 'c1') =>
      send('GET', `/classes/${classId}/risk-settings`, { caller: { role: 'instructor' } }),

    /** PUT /classes/{id}/risk-settings */
    saveRiskSettings: (classId, patch) =>
      send('PUT', `/classes/${classId}/risk-settings`, { body: patch, caller: { role: 'instructor' } }),

    /** GET /me/standing */
    getMyStanding: ({ classId = 'c1', studentId, caller = { role: 'student', studentId } }) =>
      send('GET', '/me/standing', { query: { classId, studentId }, caller }),

    /** PUT /classes/{id}/settings */
    saveSettings: (classId, patch) =>
      send('PUT', `/classes/${classId}/settings`, { body: patch, caller: { role: 'instructor' } }),

    /** POST /classes/{id}/refresh */
    refresh: (classId = 'c1') =>
      send('POST', `/classes/${classId}/refresh`, { caller: { role: 'instructor' } }),

    /** GET /classes/{id}/status */
    getStatus: (classId = 'c1') =>
      send('GET', `/classes/${classId}/status`, { caller: { role: 'instructor' } }),
  };
}
