import { useEffect, useState } from 'react';
import api from './api';

/**
 * Modal: manage view-access for a single host.
 *
 * Visible to any user with view access, but the "add / remove" controls
 * only appear when the server marks `can_manage=true` (owner + super-admin).
 */
export default function HostAccessModal({ open, onClose, hostId, hostName }) {
  const [board, setBoard] = useState(null);
  const [identifier, setIdentifier] = useState('');
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);

  const load = () => {
    if (!hostId) return;
    api.get(`/api/hosts/${hostId}/access`)
      .then((r) => setBoard(r.data))
      .catch((e) => setErr(e?.response?.data?.detail || 'Не вдалося завантажити доступи'));
  };

  useEffect(() => {
    if (!open) return;
    setErr(null); setIdentifier('');
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, hostId]);

  if (!open) return null;

  const share = async (e) => {
    e.preventDefault();
    setErr(null); setBusy(true);
    try {
      await api.post(`/api/hosts/${hostId}/share`, { identifier });
      setIdentifier('');
      load();
    } catch (e) {
      setErr(e?.response?.data?.detail || 'Не вдалося надати доступ');
    } finally {
      setBusy(false);
    }
  };

  const revoke = async (uid) => {
    try {
      await api.delete(`/api/hosts/${hostId}/share/${uid}`);
      load();
    } catch (e) {
      setErr(e?.response?.data?.detail || 'Помилка');
    }
  };

  return (
    <div
      className="fixed inset-0 bg-black/40 backdrop-blur-sm flex items-start justify-center z-50 p-4 overflow-y-auto"
      onClick={onClose}
    >
      <div
        className="bg-white rounded-xl shadow-2xl w-full max-w-lg mt-16 p-6"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-4">
          <div>
            <h2 className="text-lg font-semibold text-gray-800">Доступ до хоста</h2>
            <p className="text-xs text-gray-500">{hostName}</p>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-700 text-2xl leading-none">
            ×
          </button>
        </div>

        {!board ? (
          <div className="text-sm text-gray-400">Завантаження…</div>
        ) : (
          <>
            {/* Owner row */}
            <div className="mb-4 p-3 bg-blue-50 border border-blue-100 rounded">
              <div className="text-[11px] text-blue-600 uppercase font-medium">
                Власник (адмін хоста)
              </div>
              <div className="text-sm text-gray-800 mt-0.5">
                {board.owner_username || '— ніхто —'}
              </div>
            </div>

            {/* Grant form */}
            {board.can_manage && (
              <form onSubmit={share} className="mb-4 space-y-2">
                <label className="text-xs font-medium text-gray-700 block">
                  Надати доступ користувачу
                </label>
                <div className="flex gap-2">
                  <input
                    type="text"
                    value={identifier}
                    onChange={(e) => setIdentifier(e.target.value)}
                    placeholder="email або логін"
                    className="flex-grow border border-gray-200 rounded px-3 py-2 text-sm focus:outline-none focus:border-blue-400"
                    required
                  />
                  <button
                    type="submit"
                    disabled={busy || !identifier}
                    className="bg-blue-600 text-white px-4 py-2 rounded text-sm hover:bg-blue-700 disabled:bg-blue-300"
                  >
                    Додати
                  </button>
                </div>
                {err && (
                  <div className="bg-red-50 border border-red-200 text-red-700 text-xs rounded p-2">
                    {err}
                  </div>
                )}
              </form>
            )}

            {/* Grant list */}
            <div>
              <div className="text-[11px] text-gray-500 uppercase font-medium mb-2">
                Користувачі з доступом ({board.grants.length})
              </div>
              {board.grants.length === 0 ? (
                <div className="text-sm text-gray-400 text-center py-4">
                  Поки нікому не надано доступ.
                </div>
              ) : (
                <ul className="divide-y divide-gray-100 border border-gray-100 rounded">
                  {board.grants.map((g) => (
                    <li key={g.user_id} className="flex items-center justify-between p-3">
                      <div className="min-w-0">
                        <div className="text-sm font-medium text-gray-800 truncate">
                          {g.username}
                        </div>
                        <div className="text-xs text-gray-500 truncate">{g.email}</div>
                        {g.granted_by_username && (
                          <div className="text-[10px] text-gray-400 mt-0.5">
                            надано {g.granted_by_username} ·{' '}
                            {new Date(g.granted_at).toLocaleString()}
                          </div>
                        )}
                      </div>
                      {board.can_manage && (
                        <button
                          onClick={() => revoke(g.user_id)}
                          className="text-xs text-red-600 hover:underline flex-shrink-0 ml-3"
                        >
                          Забрати
                        </button>
                      )}
                    </li>
                  ))}
                </ul>
              )}
              {!board.can_manage && (
                <p className="text-[11px] text-gray-400 mt-2">
                  Лише власник або супер-адмін може керувати доступом.
                </p>
              )}
            </div>
          </>
        )}

        <div className="flex justify-end mt-6">
          <button
            onClick={onClose}
            className="bg-gray-100 text-gray-700 hover:bg-gray-200 px-4 py-2 text-sm rounded"
          >
            Закрити
          </button>
        </div>
      </div>
    </div>
  );
}
