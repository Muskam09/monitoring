import { useEffect, useState } from 'react';
import api from './api';

/**
 * Super-admin only: a full user × host access matrix.
 *
 * Owner cell shows "👑 owner" and is read-only.
 * Non-owner cells are clickable toggles — grant / revoke access.
 * Admin rows are always fully-checked and read-only.
 */
export default function AccessMatrix() {
  const [rows, setRows] = useState([]);
  const [hosts, setHosts] = useState([]);
  const [err, setErr] = useState(null);
  const [saving, setSaving] = useState(false);

  const refresh = async () => {
    try {
      const [m, h] = await Promise.all([
        api.get('/api/admin/access-matrix'),
        api.get('/api/hosts'),
      ]);
      setRows(m.data || []);
      setHosts(h.data || []);
      setErr(null);
    } catch (e) {
      setErr(e?.response?.data?.detail || 'Не вдалося завантажити матрицю');
    }
  };

  useEffect(() => { refresh(); }, []);

  const toggle = async (user, host) => {
    if (saving) return;
    if (user.is_admin) return;              // admin can see everything anyway
    if (host.owner_id === user.user_id) return; // owner → read-only
    const hasAccess = user.shared_host_ids.includes(host.id);
    setSaving(true);
    try {
      if (hasAccess) {
        await api.delete(`/api/admin/users/${user.user_id}/revoke/${host.id}`);
      } else {
        await api.post(`/api/admin/users/${user.user_id}/grant/${host.id}`);
      }
      await refresh();
    } catch (e) {
      setErr(e?.response?.data?.detail || 'Помилка');
    } finally {
      setSaving(false);
    }
  };

  if (err) {
    return (
      <div className="bg-red-50 border border-red-200 text-red-700 text-sm rounded p-3">
        {err}
      </div>
    );
  }

  if (rows.length === 0 || hosts.length === 0) {
    return (
      <div className="text-sm text-gray-400">
        Поки немає даних. Створіть хоч один хост і одного користувача.
      </div>
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="min-w-full text-xs border-separate border-spacing-0">
        <thead>
          <tr>
            <th className="sticky left-0 bg-white text-left p-2 border-b border-gray-200 min-w-[180px]">
              Користувач
            </th>
            {hosts.map((h) => (
              <th
                key={h.id}
                className="p-2 border-b border-gray-200 text-center min-w-[88px]"
                title={h.name}
              >
                <div className="truncate max-w-[88px] mx-auto">{h.name}</div>
                <div className="text-[9px] text-gray-400 font-normal">
                  #{h.id}
                </div>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((u) => (
            <tr key={u.user_id} className="hover:bg-gray-50">
              <td className="sticky left-0 bg-white p-2 border-b border-gray-100">
                <div className="font-medium text-gray-800">{u.username}</div>
                <div className="text-[10px] text-gray-500 truncate max-w-[180px]">
                  {u.email}
                </div>
                {u.is_admin && (
                  <span className="inline-block text-[9px] bg-purple-100 text-purple-700 rounded px-1 mt-0.5">
                    super-admin
                  </span>
                )}
              </td>

              {hosts.map((h) => {
                const isOwner = h.owner_id === u.user_id;
                const isAdmin = u.is_admin;
                const hasShared = u.shared_host_ids.includes(h.id);
                const show = isOwner || isAdmin || hasShared;
                const label = isOwner
                  ? '👑'
                  : isAdmin
                  ? '✓ (admin)'
                  : hasShared
                  ? '✓'
                  : '—';
                const cellClass = isOwner
                  ? 'bg-blue-50 text-blue-700'
                  : isAdmin
                  ? 'bg-purple-50 text-purple-700 cursor-not-allowed'
                  : hasShared
                  ? 'bg-green-50 text-green-700 hover:bg-green-100'
                  : 'bg-white text-gray-400 hover:bg-gray-100';
                const clickable = !isOwner && !isAdmin;
                return (
                  <td
                    key={h.id}
                    onClick={clickable ? () => toggle(u, h) : undefined}
                    className={`p-2 border-b border-gray-100 text-center ${cellClass} ${
                      clickable ? 'cursor-pointer' : ''
                    }`}
                    title={isOwner ? 'Власник' : isAdmin ? 'Super-admin' : (hasShared ? 'Клік — забрати' : 'Клік — надати')}
                  >
                    {show ? label : '—'}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>

      <div className="text-[11px] text-gray-500 mt-3 flex flex-wrap gap-x-4 gap-y-1">
        <span><span className="inline-block w-3 h-3 bg-blue-50 border border-blue-200 rounded-sm align-middle mr-1" />👑 — власник (host-admin)</span>
        <span><span className="inline-block w-3 h-3 bg-purple-50 border border-purple-200 rounded-sm align-middle mr-1" />super-admin</span>
        <span><span className="inline-block w-3 h-3 bg-green-50 border border-green-200 rounded-sm align-middle mr-1" />✓ — наданий доступ</span>
        <span>Клік на порожню клітинку — надати доступ, на зелену — забрати</span>
      </div>
    </div>
  );
}
