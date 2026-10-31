import { useEffect, useRef, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import api from './api';

export default function ActivatePage() {
  const { token } = useParams();
  const [state, setState] = useState({ status: 'loading', message: '' });

  // React 18 StrictMode mounts every component TWICE in dev to help catch
  // unsafe effects. Without a guard, our useEffect would hit the activation
  // endpoint twice — the first call activates the account, the second sees
  // the token as "already used" and we'd show an error even though we
  // succeeded. The ref below ensures we fire exactly ONCE per token value.
  //
  // (The backend is also idempotent so this is defence-in-depth, but we
  // still want to avoid a wasted round-trip.)
  const firedForToken = useRef(null);

  useEffect(() => {
    if (!token) return;
    if (firedForToken.current === token) return;
    firedForToken.current = token;

    api.get(`/api/activate/${encodeURIComponent(token)}`)
      .then((r) => setState({ status: 'ok', message: r.data.message }))
      .catch((e) => setState({
        status: 'error',
        message: e?.response?.data?.detail || 'Не вдалося активувати акаунт',
      }));
  }, [token]);

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-100">
      <div className="bg-white p-8 rounded-lg shadow-md w-96 text-center">
        <h1 className="text-xl font-bold mb-4 text-gray-800">Активація акаунта</h1>
        {state.status === 'loading' && <p className="text-gray-500">Обробка посилання…</p>}
        {state.status === 'ok' && (
          <>
            <p className="text-green-600 mb-4">{state.message}</p>
            <Link to="/" className="text-blue-600 hover:underline">
              Перейти до входу →
            </Link>
          </>
        )}
        {state.status === 'error' && (
          <>
            <p className="text-red-600 mb-4">{state.message}</p>
            <Link to="/" className="text-blue-600 hover:underline">
              На головну
            </Link>
          </>
        )}
      </div>
    </div>
  );
}
