import { useEffect, useState } from 'react';
import { Routes, Route } from 'react-router-dom';
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
} from 'recharts';
import api from './api';
import Login from './Login';
import Register from './Register';
import Profile from './Profile';
import Enable2FA from './Enable2FA';
import AdminPanel from './AdminPanel';
import ActivatePage from './ActivatePage';
import ForgotPasswordPage from './ForgotPasswordPage';
import ResetPasswordPage from './ResetPasswordPage';

function Dashboard() {
  const [authToken, setAuthToken] = useState(() => localStorage.getItem('token'));
  const [authScreen, setAuthScreen] = useState('login'); // 'login' | 'register' | 'forgot'
  const [me, setMe] = useState(null);
  const [showAdmin, setShowAdmin] = useState(false);

  const [hosts, setHosts] = useState([]);
  const [selectedHost, setSelectedHost] = useState(null);
  const [metrics, setMetrics] = useState([]);

  const refreshMe = () => {
    if (!authToken) { setMe(null); return; }
    api.get('/api/me')
      .then((r) => setMe(r.data))
      .catch(() => setMe(null));
  };

  useEffect(() => { refreshMe(); }, [authToken]);

  useEffect(() => {
    if (!authToken) return;
    api.get('/api/hosts')
      .then((r) => setHosts(r.data))
      .catch((e) => console.error('hosts fetch failed', e));
  }, [authToken]);

  useEffect(() => {
    if (!authToken || !selectedHost) return;
    const fetchMetrics = () => {
      api.get(`/api/hosts/${selectedHost}/metrics`)
        .then((r) => {
          const formatted = r.data.map((m) => ({
            time: new Date(m.timestamp).toLocaleTimeString(),
            cpu: Number(m.cpu_percent).toFixed(2),
            ram: Number(m.ram_percent).toFixed(2),
          }));
          setMetrics(formatted);
        })
        .catch((e) => console.error('metrics fetch failed', e));
    };
    fetchMetrics();
    const interval = setInterval(fetchMetrics, 10000);
    return () => clearInterval(interval);
  }, [authToken, selectedHost]);

  const handleLogout = async () => {
    try { await api.post('/api/logout'); } catch { /* ignore */ }
    localStorage.removeItem('token');
    setAuthToken(null);
    setSelectedHost(null);
    setMetrics([]);
    setHosts([]);
  };

  // ─── Not logged in ────────────────────────────────────────────────────
  if (!authToken) {
    if (authScreen === 'register') {
      return <Register switchToLogin={() => setAuthScreen('login')} />;
    }
    if (authScreen === 'forgot') {
      return <ForgotPasswordPage />;
    }
    return (
      <Login
        setAuthToken={setAuthToken}
        switchToRegister={() => setAuthScreen('register')}
        switchToForgot={() => setAuthScreen('forgot')}
      />
    );
  }

  // ─── Dashboard ────────────────────────────────────────────────────────
  return (
    <div className="min-h-screen bg-gray-100 p-8">
      <div className="flex justify-between items-center mb-6">
        <h1 className="text-3xl font-bold text-gray-800">DevOps Dashboard</h1>
        <div className="flex items-center gap-3">
          {me?.is_admin && (
            <button
              onClick={() => setShowAdmin((v) => !v)}
              className={`px-3 py-2 rounded text-sm ${
                showAdmin ? 'bg-purple-600 text-white' : 'bg-purple-100 text-purple-700'
              }`}
            >
              {showAdmin ? 'Приховати адмін' : 'Адмін-панель'}
            </button>
          )}
          {me && (
            <span className="text-sm text-gray-600">
              {me.username} · <span className="text-gray-400">{me.role}</span>
            </span>
          )}
          <button
            onClick={handleLogout}
            className="bg-red-500 text-white px-4 py-2 rounded hover:bg-red-600 transition"
          >
            Вийти
          </button>
        </div>
      </div>

      <Profile me={me} />
      <Enable2FA me={me} onChange={refreshMe} />
      {me?.is_admin && showAdmin && <AdminPanel />}

      <div className="grid grid-cols-1 md:grid-cols-4 gap-6">
        <div className="bg-white p-4 rounded-lg shadow col-span-1">
          <h2 className="text-xl font-semibold mb-4">Підключені сервери</h2>
          <ul>
            {hosts.map((host) => (
              <li
                key={host.id}
                onClick={() => setSelectedHost(host.id)}
                className={`p-3 mb-2 rounded cursor-pointer transition ${
                  selectedHost === host.id
                    ? 'bg-blue-100 border-blue-500 border'
                    : 'bg-gray-50 hover:bg-gray-200'
                }`}
              >
                <div className="flex justify-between items-center">
                  <span className="font-medium text-gray-700">{host.name}</span>
                  <span
                    className={`w-3 h-3 rounded-full ${
                      host.is_online ? 'bg-green-500 animate-pulse' : 'bg-red-500'
                    }`}
                  />
                </div>
              </li>
            ))}
            {hosts.length === 0 && (
              <li className="text-sm text-gray-400">
                Ще немає жодного зареєстрованого хоста.
              </li>
            )}
          </ul>
        </div>

        <div className="bg-white p-6 rounded-lg shadow col-span-1 md:col-span-3">
          {selectedHost ? (
            <>
              <h2 className="text-xl font-semibold mb-4">Телеметрія сервера</h2>
              <div className="h-96 w-full">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={metrics}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="time" />
                    <YAxis domain={[0, 100]} />
                    <Tooltip />
                    <Legend />
                    <Line type="monotone" dataKey="cpu" stroke="#8884d8"
                          name="CPU (%)" strokeWidth={2} dot={false} />
                    <Line type="monotone" dataKey="ram" stroke="#82ca9d"
                          name="RAM (%)" strokeWidth={2} dot={false} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </>
          ) : (
            <div className="flex h-full items-center justify-center text-gray-400">
              Оберіть сервер ліворуч для перегляду метрик
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Dashboard />} />
      <Route path="/activate/:token" element={<ActivatePage />} />
      <Route path="/reset-password/:token" element={<ResetPasswordPage />} />
    </Routes>
  );
}
