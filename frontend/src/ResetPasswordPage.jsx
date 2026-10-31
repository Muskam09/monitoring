import { useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import api from './api';
import { evaluate } from './passwordStrength';

export default function ResetPasswordPage() {
  const { token } = useParams();
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [msg, setMsg] = useState(null);
  const [ok, setOk] = useState(false);
  const [busy, setBusy] = useState(false);

  const strength = useMemo(() => evaluate(password), [password]);
  const match = password && password === confirm;

  const handleSubmit = async (e) => {
    e.preventDefault();
    setMsg(null);
    if (!strength.passes) {
      setMsg('Пароль не відповідає політиці: ' + strength.issues.join(', '));
      return;
    }
    if (!match) {
      setMsg('Паролі не збігаються');
      return;
    }
    setBusy(true);
    try {
      const r = await api.post('/api/password/reset', {
        token,
        new_password: password,
      });
      setMsg(r.data.message);
      setOk(true);
    } catch (err) {
      setMsg(err?.response?.data?.detail || 'Помилка скидання пароля');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-100">
      <div className="bg-white p-8 rounded-lg shadow-md w-96">
        <h1 className="text-xl font-bold mb-4 text-gray-800 text-center">
          Новий пароль
        </h1>
        {!ok ? (
          <form onSubmit={handleSubmit} className="space-y-3">
            <input
              type="password"
              placeholder="Новий пароль"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full border px-3 py-2 rounded"
              autoComplete="new-password"
              required
            />
            <input
              type="password"
              placeholder="Повторіть пароль"
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              className="w-full border px-3 py-2 rounded"
              autoComplete="new-password"
              required
            />
            {password && (
              <div>
                <div className="flex gap-1 mb-1">
                  {[0, 1, 2, 3, 4].map((i) => (
                    <div key={i} className={`h-2 flex-1 rounded ${
                      i <= strength.score ? strength.color : 'bg-gray-200'
                    }`} />
                  ))}
                </div>
                <p className="text-xs text-gray-600">
                  Складність: {strength.label}
                  {!strength.passes && (
                    <span className="text-red-500">
                      {' '}· потрібно: {strength.issues.join(', ')}
                    </span>
                  )}
                </p>
              </div>
            )}
            <button
              type="submit"
              disabled={busy || !strength.passes || !match}
              className="w-full bg-blue-600 text-white py-2 rounded hover:bg-blue-700 disabled:bg-blue-300 transition"
            >
              {busy ? 'Збереження…' : 'Зберегти пароль'}
            </button>
          </form>
        ) : (
          <p className="text-green-600 text-center">{msg}</p>
        )}
        {msg && !ok && (
          <div className="text-red-600 text-sm mt-3 text-center">{msg}</div>
        )}
        <div className="text-center mt-6">
          <Link to="/" className="text-blue-600 hover:underline text-sm">
            На головну
          </Link>
        </div>
      </div>
    </div>
  );
}
