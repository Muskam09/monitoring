import { useState } from 'react';
import { Link } from 'react-router-dom';
import api from './api';

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState('');
  const [msg, setMsg] = useState(null);
  const [busy, setBusy] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setBusy(true);
    try {
      const r = await api.post('/api/password/forgot', { email });
      setMsg(r.data.message);
    } catch (err) {
      setMsg(err?.response?.data?.detail || 'Помилка запиту');
    } finally {
      setBusy(false);
    }
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
          />
          <button
            type="submit"
            disabled={busy}
            className="w-full bg-blue-600 text-white py-2 rounded hover:bg-blue-700 disabled:bg-blue-300 transition"
          >
            {busy ? 'Відправка…' : 'Надіслати посилання'}
          </button>
        </form>
        {msg && (
          <div className="text-sm text-center mt-3 text-gray-700">{msg}</div>
        )}
        <div className="text-center mt-6">
          <Link to="/" className="text-blue-600 hover:underline text-sm">
            ← Повернутися до входу
          </Link>
        </div>
      </div>
    </div>
  );
}
