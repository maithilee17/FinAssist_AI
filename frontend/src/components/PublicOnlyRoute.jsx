import { Navigate } from 'react-router-dom'

import useAuth from '../context/useAuth'

export default function PublicOnlyRoute({ children }) {
  const { user, isLoading } = useAuth()
  if (isLoading) return null
  return user ? <Navigate to="/dashboard" replace /> : children
}

