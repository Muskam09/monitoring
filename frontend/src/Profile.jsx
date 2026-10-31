export default function Profile({ me }) {
  if (!me) return null;
  const badge = (ok, label) => (
    <span className={`inline-block px-2 py-0.5 rounded text-xs ${
      ok ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-500'
    }`}>{label}</span>
  );
  return (
    <div className="bg-white p-4 rounded-lg shadow mb-6">
      <h2 className="text-lg font-semibold mb-2">Профіль</h2>
      <dl className="grid grid-cols-2 gap-y-1 text-sm">
        <dt className="text-gray-500">Користувач:</dt>
        <dd className="font-medium">{me.username}</dd>
        <dt className="text-gray-500">Email:</dt>
        <dd className="font-medium">{me.email}</dd>
        <dt className="text-gray-500">Роль:</dt>
        <dd className="font-medium">{me.role}</dd>
        <dt className="text-gray-500">Статус:</dt>
        <dd className="flex flex-wrap gap-1">
          {badge(me.is_active, me.is_active ? 'активований' : 'не активований')}
          {me.is_locked && badge(false, 'заблоковано адміном')}
          {me.is_2fa_enabled && badge(true, '2FA ✓')}
          {me.is_admin && badge(true, 'admin')}
        </dd>
      </dl>
    </div>
  );
}
