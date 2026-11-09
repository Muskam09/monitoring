import { useEffect, useState } from 'react';
import { Routes, Route, useNavigate } from 'react-router-dom';
import api from './api';

import Login from './Login';
import Register from './Register';
import Profile from './Profile';
import Enable2FA from './Enable2FA';
import AdminPanel from './AdminPanel';
import ActivatePage from './ActivatePage';
import ForgotPasswordPage from './ForgotPasswordPage';
import ResetPasswordPage from './ResetPasswordPage';
import HostDetail from './HostDetail';
import HostCard from './HostCard';
import AddSystemModal from './AddSystemModal';

/** Main dashboard — grid of HostCards + actions header. */
function Dashboard() {
  const navigate = useNavigate();
  const [authToken, setAuthToken] = useState(() => localStorage.getItem('token'));
  const [authScreen, setAuthScreen] = useState('login');
  const [me, setMe] = useState(null);

  const [hosts, setHosts] = useState([]);
  const [hostsLoading, setHostsLoading] = useState(false);

  const [showAdmin, setShowAdmin] = useState(false);
  const [showAccount, setShowAccount] = useState(false);
  const [showAdd, setShowAdd] = useState(false);

  const refreshMe = () => {
    if (!authToken) { setMe(null); return; }
    api.get('/api/me').then((r) => setMe(r.data)).catch(() => setMe(null));
  };

  const refreshHosts = () => {
    if (!authToken) return;
    setHostsLoading(true);
    api.get('/api/hosts')
      .then((r) => setHosts(r.data))
      .catch(() => {})
      .finally(() => setHostsLoading(false));
  };

  useEffect(() => { refreshMe(); }, [authToken]);

  useEffect(() => {
    if (!authToken) return;
    refreshHosts();
    const t = setInterval(refreshHosts, 10000);
    return () => clearInterval(t);
  }, [authToken]);

  const handleLogout = async () => {
    try { await api.post('/api/logout'); } catch { /* ignore */ }
    localStorage.removeItem('token');
    setAuthToken(null);
    setHosts([]);
  };

  // ─── Not logged in ────────────────────────────────────────────────────
  if (!authToken) {
    if (authScreen === 'register') {
      return <Register switchToLogin={() => setAuthScreen('login')} />;
    }
    return (
      <Login
        setAuthToken={setAuthToken}
        switchToRegister={() => setAuthScreen('register')}
        switchToForgot={() => navigate('/forgot-password')}
      />
    );
  }

  // ─── Dashboard ────────────────────────────────────────────────────────
  return (
    <div className="min-h-screen bg-gray-50">
      {/* Top bar */}
      <header className="bg-white border-b border-gray-200 sticky top-0 z-30">
        <div className="max-w-7xl mx-auto px-6 h-14 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div className="w-6 h-6 rounded bg-gradient-to-br from-blue-500 to-indigo-600" />
            <span className="font-semibold text-gray-800">DevOps Dashboard</span>
          </div>

          <div className="flex items-center gap-2">
            {me?.is_admin && (
              <button
                onClick={() => setShowAdmin((v) => !v)}
                className={`px-3 py-1.5 rounded text-xs font-medium ${
                  showAdmin
                    ? 'bg-purple-600 text-white'
                    : 'bg-purple-50 text-purple-700 hover:bg-purple-100'
                }`}
              >
                {showAdmin ? 'Приховати адмін' : 'Адмін-панель'}
              </button>
            )}
            <button
              onClick={() => setShowAccount((v) => !v)}
              className={`px-3 py-1.5 rounded text-xs font-medium ${
                showAccount
                  ? 'bg-gray-700 text-white'
                  : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
              }`}
            >
              {showAccount ? 'Приховати акаунт' : 'Акаунт і 2FA'}
            </button>
            {me && (
              <span className="text-xs text-gray-500 ml-2 hidden sm:inline">
                {me.username} · <span className="text-gray-400">{me.role}</span>
              </span>
            )}
            <button
              onClick={handleLogout}
              className="bg-red-500 text-white px-3 py-1.5 rounded text-xs font-medium hover:bg-red-600"
            >
              Вийти
            </button>
          </div>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-6 py-6">
        {/* Collapsible account / admin sections (hidden by default so they
            don't take over the main page) */}
        {showAccount && (
          <>
            <Profile me={me} />
            <Enable2FA me={me} onChange={refreshMe} />
          </>
        )}
        {me?.is_admin && showAdmin && <AdminPanel />}

        {/* Section header */}
        <div className="flex items-end justify-between mb-5">
          <div>
            <h1 className="text-2xl font-bold text-gray-800">Системи</h1>
            <p className="text-sm text-gray-500">
              {hosts.length} {hosts.length === 1 ? 'хост' : 'хостів'} ·{' '}
              {hosts.filter((h) => h.is_online).length} онлайн
            </p>
          </div>
          <button
            onClick={() => setShowAdd(true)}
            className="bg-blue-600 text-white px-4 py-2 rounded font-medium text-sm
                       hover:bg-blue-700 transition flex items-center gap-1 shadow-sm"
          >
            <span className="text-lg leading-none">+</span>
            <span>Додати систему</span>
          </button>
        </div>

        {/* Grid of host cards */}
        {hostsLoading && hosts.length === 0 ? (
          <div className="text-gray-400 text-sm">Завантаження…</div>
        ) : hosts.length === 0 ? (
          <div className="bg-white border border-dashed border-gray-300 rounded-xl p-10 text-center">
            <div className="text-4xl mb-2">🖥️</div>
            <h3 className="text-gray-800 font-semibold mb-1">
              Ще немає жодної зареєстрованої системи
            </h3>
            <p className="text-sm text-gray-500 mb-4">
              Натисніть «Додати систему», щоб згенерувати токен агента
              та <code>docker-compose.yml</code>.
            </p>
            <button
              onClick={() => setShowAdd(true)}
              className="bg-blue-600 text-white px-4 py-2 rounded font-medium text-sm hover:bg-blue-700"
            >
              + Додати систему
            </button>
          </div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
            {hosts.map((h) => (
              <HostCard key={h.id} host={h} />
            ))}
          </div>
        )}
      </main>

      <AddSystemModal
        open={showAdd}
        onClose={() => setShowAdd(false)}
        onCreated={refreshHosts}
      />
    </div>
  );
}

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Dashboard />} />
      <Route path="/host/:id" element={<HostDetail />} />
      <Route path="/activate/:token" element={<ActivatePage />} />
      <Route path="/forgot-password" element={<ForgotPasswordPage />} />
      <Route path="/reset-password/:token" element={<ResetPasswordPage />} />
    </Routes>
  );
}
