import { useEffect, useMemo, useState } from 'react'

import api from '../lib/api'
import AuthContext from './auth-context'

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [isLoading, setIsLoading] = useState(true)

  useEffect(() => {
    let active = true
    api.get('/auth/me')
      .then(({ data }) => { if (active) setUser(data) })
      .catch(() => { if (active) setUser(null) })
      .finally(() => { if (active) setIsLoading(false) })
    return () => { active = false }
  }, [])

  const value = useMemo(() => ({
    user,
    isLoading,
    async login(credentials) {
      const { data } = await api.post('/auth/login', credentials)
      setUser(data.user)
      return data.user
    },
    async register(details) {
      const { data } = await api.post('/auth/register', details)
      return data
    },
    async logout() {
      try {
        await api.post('/auth/logout')
      } finally {
        setUser(null)
      }
    },
  }), [isLoading, user])

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

