import { useEffect, useState } from 'react';
import api from './api';

export default function AdminPanel() {
  const [users, setUsers] = useState([]);
  const [logs, setLogs] = useState([]);
  const [err, setErr] = useState(null);
  const [tab, setTab] = useState('users');

  const refresh = () => {
    api.get('/api/admin/users').then((r) => setUsers(r.data)).catch((e) =>
      setErr(e?.response?.data?.detail || 'Немає доступу'));
    api.get('/api/admin/login-logs?limit=100').then((r) => setLogs(r.data)).catch(() => {});
  };

  useEffect(() => { refresh(); }, []);

  const lock = async (id) => {
    await api.post(`/api/admin/users/${id}/lock`).catch(() => {});
    refresh();
  };
  const unlock = async (id) => {
    await api.post(`/api/admin/users/${id}/unlock`).catch(() => {});
    refresh();
  };

  if (err) {
    return (
      <div className="bg-white p-4 rounded-lg shadow mb-6 text-red-600 text-sm">
        {err}
      </div>
    );
  }

  return (
    <div className="bg-white p-4 rounded-lg shadow mb-6">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-lg font-semibold">Адмін-панель</h2>
        <div className="flex gap-2 text-sm">
          <button
            onClick={() => setTab('users')}
            className={`px-3 py-1 rounded ${tab === 'users' ? 'bg-blue-100' : ''}`}
          >
            Користувачі ({users.length})
          </button>
          <button
            onClick={() => setTab('logs')}
            className={`px-3 py-1 rounded ${tab === 'logs' ? 'bg-blue-100' : ''}`}
          >
            Журнал входів ({logs.length})
          </button>
          <button onClick={refresh} className="px-3 py-1 text-gray-500 hover:text-black">
            ⟳
          </button>
        </div>
      </div>

      {tab === 'users' && (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-left text-gray-500 border-b">
              <tr>
                <th className="py-2">ID</th>
                <th>Логін</th>
                <th>Email</th>
                <th>Активний</th>
                <th>Заблоков.</th>
                <th>Невдалі</th>
                <th>2FA</th>
                <th>Admin</th>
                <th>Дія</th>
              </tr>
            </thead>
            <tbody>
              {users.map((u) => (
                <tr key={u.id} className="border-b hover:bg-gray-50">
                  <td className="py-1">{u.id}</td>
                  <td className="font-medium">{u.username}</td>
                  <td className="text-gray-500">{u.email}</td>
                  <td>{u.is_active ? '✓' : '—'}</td>
                  <td>{u.is_locked ? <span className="text-red-600">🔒</span> : '—'}</td>
                  <td className={u.failed_login_attempts >= 3 ? 'text-red-500' : ''}>
                    {u.failed_login_attempts}
                  </td>
                  <td>{u.is_2fa_enabled ? '✓' : '—'}</td>
                  <td>{u.is_admin ? '✓' : '—'}</td>
                  <td>
                    {u.is_locked ? (
                      <button
                        onClick={() => unlock(u.id)}
                        className="text-green-600 hover:underline text-xs"
                      >
                        Розблокувати
                      </button>
                    ) : (
                      <button
                        onClick={() => lock(u.id)}
                        className="text-red-600 hover:underline text-xs"
                      >
                        Заблокувати
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {tab === 'logs' && (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-left text-gray-500 border-b">
              <tr>
                <th className="py-2">Час</th>
                <th>Логін</th>
                <th>IP</th>
                <th>Статус</th>
                <th>Причина</th>
              </tr>
            </thead>
            <tbody>
              {logs.map((l) => (
                <tr key={l.id} className="border-b hover:bg-gray-50">
                  <td className="py-1 text-gray-500 text-xs whitespace-nowrap">
                    {new Date(l.timestamp).toLocaleString()}
                  </td>
                  <td>{l.username_attempted ?? '—'}</td>
                  <td className="text-xs">{l.ip_address}</td>
                  <td>
                    <span className={{
                      success: 'text-green-600',
                      failed: 'text-red-600',
                      locked: 'text-orange-600',
                      pending: 'text-gray-500',
                    }[l.status] || ''}>
                      {l.status}
                    </span>
                  </td>
                  <td className="text-xs text-gray-500">{l.reason ?? ''}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
