import { useState } from 'react';
import { GoogleLogin } from '@react-oauth/google';
import api from './api';

export default function Login({ setAuthToken, switchToRegister, switchToForgot }) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  // Task 5 — 2FA step
  const [twofaTicket, setTwofaTicket] = useState(null);
  const [otp, setOtp] = useState('');

  const finish = (jwt) => {
    localStorage.setItem('token', jwt);
    setAuthToken(jwt);
  };

  const handleGoogleSuccess = async (credentialResponse) => {
    try {
      const res = await api.post('/api/auth/google', {
        token: credentialResponse.credential,
      });
      finish(res.data.access_token);
    } catch (err) {
      setError(err?.response?.data?.detail || 'Не вдалося увійти через Google');
    }
  };

  const handlePasswordLogin = async (e) => {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const body = new URLSearchParams();
      body.append('username', username);
      body.append('password', password);
      const res = await api.post('/api/login', body, {
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      });
      if (res.data.twofa_required) {
        setTwofaTicket(res.data.twofa_ticket);
      } else if (res.data.access_token) {
        finish(res.data.access_token);
      } else {
        setError('Непередбачена відповідь сервера');
      }
    } catch (err) {
      setError(err?.response?.data?.detail || 'Помилка входу');
    } finally {
      setBusy(false);
    }
  };

  const handle2FAVerify = async (e) => {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const res = await api.post('/api/2fa/verify-login', {
        ticket: twofaTicket,
        code: otp,
      });
      finish(res.data.access_token);
    } catch (err) {
      setError(err?.response?.data?.detail || 'Невірний код 2FA');
    } finally {
      setBusy(false);
    }
  };

  // ─── 2FA step ─────────────────────────────────────────────────────────
  if (twofaTicket) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-100">
        <div className="bg-white p-8 rounded-lg shadow-md w-96">
          <h1 className="text-2xl font-bold mb-6 text-gray-800 text-center">
            Двофакторна автентифікація
          </h1>
          <p className="text-sm text-gray-600 mb-4 text-center">
            Введіть 6-значний код з вашого застосунку автентифікації
            (Google Authenticator / Authy).
          </p>
          <form onSubmit={handle2FAVerify} className="space-y-3">
            <input
              type="text"
              inputMode="numeric"
              pattern="\d{6}"
              maxLength={6}
              placeholder="123456"
              value={otp}
              onChange={(e) => setOtp(e.target.value.replace(/\D/g, ''))}
              className="w-full border px-3 py-2 rounded text-center text-xl tracking-widest"
              autoFocus
              required
            />
            <button
              type="submit"
              disabled={busy || otp.length !== 6}
              className="w-full bg-blue-600 text-white py-2 rounded hover:bg-blue-700 disabled:bg-blue-300 transition"
            >
              {busy ? 'Перевірка…' : 'Підтвердити'}
            </button>
          </form>
          {error && (
            <div className="text-red-600 text-sm mt-3 text-center">{error}</div>
          )}
          <button
            type="button"
            onClick={() => { setTwofaTicket(null); setOtp(''); setError(null); }}
            className="text-sm text-gray-500 hover:underline block mx-auto mt-4"
          >
            ← Повернутися
          </button>
        </div>
      </div>
    );
  }

  // ─── Credentials step ─────────────────────────────────────────────────
  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-100">
      <div className="bg-white p-8 rounded-lg shadow-md w-96">
        <h1 className="text-2xl font-bold mb-6 text-gray-800 text-center">
          Вхід у систему
        </h1>

        <form onSubmit={handlePasswordLogin} className="space-y-3">
          <input
            type="text"
            placeholder="Ім'я користувача"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            className="w-full border px-3 py-2 rounded"
            autoComplete="username"
            required
          />
          <input
            type="password"
            placeholder="Пароль"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="w-full border px-3 py-2 rounded"
            autoComplete="current-password"
            required
          />
          <button
            type="submit"
            disabled={busy}
            className="w-full bg-blue-600 text-white py-2 rounded hover:bg-blue-700 disabled:bg-blue-300 transition"
          >
            {busy ? 'Вхід…' : 'Увійти'}
          </button>
        </form>

        {error && (
          <div className="text-red-600 text-sm mt-3 text-center">{error}</div>
        )}

        <div className="text-right mt-2">
          <button
            type="button"
            onClick={switchToForgot}
            className="text-xs text-gray-500 hover:text-blue-600 hover:underline"
          >
            Забули пароль?
          </button>
        </div>

        <div className="my-4 flex items-center">
          <div className="flex-grow h-px bg-gray-200" />
          <span className="px-2 text-xs text-gray-400">або</span>
          <div className="flex-grow h-px bg-gray-200" />
        </div>

        <div className="flex justify-center">
          <GoogleLogin
            onSuccess={handleGoogleSuccess}
            onError={() => setError('Помилка Google Login')}
          />
        </div>

        <p className="text-sm text-gray-500 mt-6 text-center">
          Немає акаунта?{' '}
          <button
            type="button"
            onClick={switchToRegister}
            className="text-blue-600 hover:underline"
          >
            Зареєструватися
          </button>
        </p>
      </div>
    </div>
  );
}
