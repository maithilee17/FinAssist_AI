import axios from 'axios'

export const apiBaseUrl = (import.meta.env.VITE_API_URL ?? 'http://localhost:8000/api').replace(/\/$/, '')

const api = axios.create({
  baseURL: apiBaseUrl,
  timeout: 5000,
  withCredentials: true,
  headers: { Accept: 'application/json' },
})

const csrfCookieName = import.meta.env.VITE_CSRF_COOKIE_NAME ?? 'finassist_csrf_token'

function readCookie(name) {
  const prefix = `${encodeURIComponent(name)}=`
  const value = document.cookie.split('; ').find((cookie) => cookie.startsWith(prefix))
  return value ? decodeURIComponent(value.slice(prefix.length)) : null
}

api.interceptors.request.use((config) => {
  const method = config.method?.toLowerCase()
  if (method && !['get', 'head', 'options'].includes(method)) {
    const csrfToken = readCookie(csrfCookieName)
    if (csrfToken) config.headers.set('X-CSRF-Token', csrfToken)
  }
  return config
})

export function getApiError(error, fallback = 'Something went wrong. Please try again.') {
  const detail = error?.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail) && detail.length > 0) {
    return detail.map((item) => item.msg).join(' ')
  }
  if (error?.code === 'ECONNABORTED') return 'The server took too long to respond.'
  if (!error?.response) return 'Unable to reach the FinAssist AI server.'
  return fallback
}

export default api

