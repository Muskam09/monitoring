import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import api from './api';

export default function ForgotPasswordPage() {
  const navigate = useNavigate();
  const [email, setEmail] = useState('');
  const [msg, setMsg] = useState(null);
  const [ok, setOk] = useState(false);
  const [busy, setBusy] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setMsg(null); setOk(false);
    setBusy(true);
    try {
      const r = await api.post('/api/password/forgot', { email });
      setMsg(r.data?.message || 'Якщо акаунт існує, лист надіслано.');
      setOk(true);
    } catch (err) {
      setMsg(err?.response?.data?.detail || 'Помилка запиту');
      setOk(false);
    } finally {
      setBusy(false);
    }
  };

  const goHome = () => {
    // Explicit navigation covers both logged-in and logged-out users —
    // Dashboard will decide whether to render Login or the host grid.
    navigate('/', { replace: true });
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-100">
      <div className="bg-white p-8 rounded-lg shadow-md w-96">
        <h1 className="text-xl font-bold mb-4 text-gray-800 text-center">
          Відновлення пароля
        </h1>
        <p className="text-sm text-gray-500 mb-4 text-center">
          Введіть пошту, вказану під час реєстрації. Ми надішлемо посилання
          для встановлення нового пароля.
        </p>
        <form onSubmit={handleSubmit} className="space-y-3">
          <input
            type="email"
            placeholder="Електронна пошта"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="w-full border px-3 py-2 rounded"
            required
            autoFocus
          />
          <button
            type="submit"
            disabled={busy || !email}
            className="w-full bg-blue-600 text-white py-2 rounded hover:bg-blue-700 disabled:bg-blue-300 transition"
          >
            {busy ? 'Відправка…' : 'Надіслати посилання'}
          </button>
        </form>

        {msg && (
          <div className={`text-sm text-center mt-3 ${ok ? 'text-green-600' : 'text-red-600'}`}>
            {msg}
          </div>
        )}
        {ok && (
          <div className="text-[11px] text-gray-500 text-center mt-2">
            У dev-режимі листи доступні у{' '}
            <a
              href="http://localhost:8025"
              target="_blank"
              rel="noreferrer"
              className="text-blue-600 hover:underline"
            >
              MailHog
            </a>
          </div>
        )}

        <div className="text-center mt-6">
          <button
            type="button"
            onClick={goHome}
            className="text-blue-600 hover:underline text-sm bg-transparent border-none cursor-pointer"
          >
            ← Повернутися до входу
          </button>
        </div>
      </div>
    </div>
  );
}
