// The real backend client. Same interface as createApi() in api.js, but every call is an
// HTTP request to the FastAPI service described in openapi.yaml, so scoring, ranking and
// role checks all happen on the server.
//
// The one place JS option names (weekId, windowMode, ...) become the API's snake_case
// parameters is here.

import { ApiError } from './apiError.js';

export { ApiError };

/** Turn FastAPI's error body (a string, or a list of per-field problems) into a message. */
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
  return `Request failed (${status}).`;
}

/**
 * createHttpApi({ baseUrl, fetch, onUnauthorized })
 *
 * onUnauthorized: called once when a class endpoint answers 401 (for example after the
 * server restarted and forgot the session); the request is then retried one time.
 */
export function createHttpApi({ baseUrl = '/api', fetch: fetchImpl, onUnauthorized } = {}) {
  const doFetch = (...args) => (fetchImpl || globalThis.fetch)(...args);

  async function send(method, path, { query, body } = {}, retried = false) {
    const params = new URLSearchParams();
    for (const [key, value] of Object.entries(query || {})) {
      if (value !== undefined && value !== null && value !== '') params.set(key, value);
    }
    const qs = params.toString();
    const init = { method, credentials: 'same-origin', headers: {} };
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

    if (res.status === 401 && onUnauthorized && !retried && !/^\/(auth|demo)\//.test(path)) {
      await onUnauthorized();
      return send(method, path, { query, body }, true);
    }
    if (!res.ok) {
      const errBody = await res.json().catch(() => null);
      throw new ApiError(messageFrom(errBody, res.status), res.status);
    }
    return res.status === 204 ? null : res.json();
  }

  const viewQuery = ({ weekId, windowMode = 'week', criteriaKeys, weights, nameMode = 'full' }) => ({
    week: weekId,
    window: windowMode,
    criteria: criteriaKeys && criteriaKeys.length ? criteriaKeys.join(',') : undefined,
    weights: weights ? JSON.stringify(weights) : undefined,
    name_mode: nameMode,
  });

  return {
    /** GET /classes/{id} */
    getBootstrap: (classId = 'c1') => send('GET', `/classes/${classId}`),

    /** GET /classes/{id}/ranking */
    getRanking: ({ classId = 'c1', ...view }) =>
      send('GET', `/classes/${classId}/ranking`, { query: viewQuery(view) }),

    /** GET /classes/{id}/students/{sid}/explanation — the server decides what the caller may see. */
    getExplanation: ({ classId = 'c1', studentId, caller, ...view }) =>
      send('GET', `/classes/${classId}/students/${encodeURIComponent(studentId)}/explanation`, {
        query: viewQuery(view),
      }),

    /** PUT /classes/{id}/weights */
    saveWeights: (classId, weights) => send('PUT', `/classes/${classId}/weights`, { body: { weights } }),

    /** POST /classes/{id}/refresh */
    refresh: (classId = 'c1') => send('POST', `/classes/${classId}/refresh`),

    /** GET /classes/{id}/status — unlike the mock, this is asynchronous. */
    getStatus: (classId = 'c1') => send('GET', `/classes/${classId}/status`),

    /** POST /auth/login */
    login: ({ email, password }) => send('POST', '/auth/login', { body: { email, password } }),

    /** GET /auth/me */
    getCurrentAccount: () => send('GET', '/auth/me'),

    /** POST /auth/logout */
    logout: () => send('POST', '/auth/logout'),

    /** GET /demo/accounts — demo data only. */
    listDemoAccounts: () => send('GET', '/demo/accounts'),
  };
}

/**
 * The page has no sign-in screen yet, so with demo data it signs in as the demo teacher.
 * An existing session is reused. Against a real data source this fails with a message.
 */
export async function signInAsDemoTeacher(api) {
  try {
    return await api.getCurrentAccount();
  } catch (err) {
    if (err.status !== 401) throw err;
  }
  const needSignIn = new ApiError('Please sign in to view this class.', 401);
  let accounts;
  try {
    accounts = await api.listDemoAccounts();
  } catch (err) {
    if (err.status === 404) throw needSignIn;
    throw err;
  }
  const teacher = accounts.find((a) => a.role === 'teacher');
  if (!teacher) throw needSignIn;
  return api.login({ email: teacher.email, password: teacher.password });
}
