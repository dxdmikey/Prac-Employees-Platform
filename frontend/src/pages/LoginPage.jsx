import { useState } from 'react'
import { login } from '../services/authService.js'

// The login screen: brand mark on the dark navy background, then one card.
function LoginPage({ onLoggedIn }) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  async function handleSubmit(event) {
    // Without this the browser would reload the page on submit.
    event.preventDefault()
    setError('')
    setSubmitting(true)

    try {
      const user = await login(username, password)
      onLoggedIn(user)
    } catch (err) {
      // Covers both "wrong password" from the API and "backend not running".
      setError(err.message || 'Login failed.')
    } finally {
      // Always - so the button can never stay stuck on "Signing in...".
      setSubmitting(false)
    }
  }

  return (
    <main className="page--auth">
      <div className="brand-mark">
        <div className="brand-mark__name">Employee Platform</div>
        <div className="brand-mark__tagline">Metadata-driven enterprise demo</div>
      </div>

      <form className="card card--elevated" onSubmit={handleSubmit}>
        <h1>Sign in</h1>
        <p className="subtitle small">Use your platform account to continue.</p>

        <label htmlFor="username">Username</label>
        <input
          id="username"
          type="text"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          autoComplete="username"
          autoFocus
          required
        />

        <label htmlFor="password">Password</label>
        <input
          id="password"
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          autoComplete="current-password"
          required
        />

        {/* role="alert" makes screen readers announce the message. */}
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}

        <button type="submit" className="button--block" disabled={submitting}>
          {submitting && <span className="spinner" aria-hidden="true" />}
          {submitting ? 'Signing in...' : 'Sign in'}
        </button>
      </form>
    </main>
  )
}

export default LoginPage
