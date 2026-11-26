import { Navigate, useLocation } from 'react-router-dom'

import useAuth from '../context/useAuth'

export default function ProtectedRoute({ children }) {
  const { user, isLoading } = useAuth()
  const location = useLocation()

  if (isLoading) {
    return (
      <main className="grid min-h-screen place-items-center bg-[#061512] text-slate-200">
        <div className="flex items-center gap-3 text-sm">
          <span className="size-4 animate-spin rounded-full border-2 border-teal-300 border-r-transparent" />
          Restoring your secure session…
        </div>
      </main>
    )
  }

  if (!user) return <Navigate to="/login" replace state={{ from: location.pathname }} />
  return children
}

