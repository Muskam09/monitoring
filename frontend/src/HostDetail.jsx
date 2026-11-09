import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import {
  Area, AreaChart, CartesianGrid, Legend, Line, LineChart,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts';
import api from './api';
import HostAccessModal from './HostAccessModal';
import { formatBytesPerSec, formatUptime, usageColor } from './format';

/** Full details page for one host — reached via /host/:id */
export default function HostDetail() {
  const { id } = useParams();
  const [host, setHost] = useState(null);
  const [series, setSeries] = useState([]);
  const [containers, setContainers] = useState([]);
  const [shareOpen, setShareOpen] = useState(false);

  // Refresh host meta + chart series + container list every 10 s.
  useEffect(() => {
    let cancelled = false;
    const tick = async () => {
      try {
        const [hostsRes, metricsRes, contsRes] = await Promise.all([
          api.get('/api/hosts'),
          api.get(`/api/hosts/${id}/metrics?limit=60`),
          api.get(`/api/hosts/${id}/containers`),
        ]);
        if (cancelled) return;
        setHost(hostsRes.data.find((h) => String(h.id) === String(id)) || null);
        setSeries(metricsRes.data.map((m) => ({
          time: new Date(m.timestamp).toLocaleTimeString(),
          cpu: Number(m.cpu_percent),
          ram: Number(m.ram_percent),
          disk: Number(m.disk_percent),
          inode: Number(m.inode_percent ?? 0),
          diskRead: Number(m.disk_read_bytes_per_sec ?? 0),
          diskWrite: Number(m.disk_write_bytes_per_sec ?? 0),
          extRx: Number(m.net_external_rx_bps ?? 0),
          extTx: Number(m.net_external_tx_bps ?? 0),
          intRx: Number(m.net_internal_rx_bps ?? 0),
          intTx: Number(m.net_internal_tx_bps ?? 0),
        })));
        setContainers(contsRes.data || []);
      } catch (e) {
        // Fail silently — next tick will retry.
      }
    };
    tick();
    const t = setInterval(tick, 10000);
    return () => { cancelled = true; clearInterval(t); };
  }, [id]);

  if (!host) {
    return (
      <div className="min-h-screen bg-gray-50 p-6">
        <Link to="/" className="text-sm text-blue-600 hover:underline">← Назад</Link>
        <div className="mt-8 text-gray-500">Завантаження…</div>
      </div>
    );
  }

  const latest = series[series.length - 1] || {};

  return (
    <div className="min-h-screen bg-gray-50">
      <div className="max-w-7xl mx-auto p-6">
        <Link to="/" className="text-sm text-blue-600 hover:underline mb-4 inline-block">
          ← Усі системи
        </Link>

        {/* Header */}
        <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-5 mb-6">
          <div className="flex items-start justify-between gap-4 flex-wrap">
            <div>
              <div className="flex items-center gap-3">
                <span
                  className={`inline-block w-3 h-3 rounded-full ${
                    host.is_online ? 'bg-green-500 animate-pulse' : 'bg-gray-400'
                  }`}
                />
                <h1 className="text-2xl font-bold text-gray-800">{host.name}</h1>
                <span className={`text-[10px] px-2 py-0.5 rounded-full font-medium ${
                  host.is_online
                    ? 'bg-green-50 text-green-700 border border-green-200'
                    : 'bg-gray-50 text-gray-500 border border-gray-200'
                }`}>
                  {host.is_online ? 'ONLINE' : 'OFFLINE'}
                </span>
              </div>
              <div className="text-sm text-gray-500 font-mono mt-1">
                {host.ip_address || '—'}{host.port ? `:${host.port}` : ''}
              </div>
              {host.os_info && (
                <div className="text-xs text-gray-400 mt-1">{host.os_info}</div>
              )}
            </div>
            <div className="text-right text-xs text-gray-500">
              <div>Uptime: <span className="text-gray-700 font-medium">{formatUptime(host.uptime_seconds)}</span></div>
              {host.last_seen_at && (
                <div>Останній heartbeat: {new Date(host.last_seen_at).toLocaleTimeString()}</div>
              )}
              {host.owner_username && (
                <div className="mt-1">
                  Власник: <span className="text-gray-700 font-medium">{host.owner_username}</span>
                  {host.my_access === 'owner' && (
                    <span className="ml-1 text-[10px] bg-blue-100 text-blue-700 px-1 rounded">ви</span>
                  )}
                  {host.my_access === 'admin' && host.my_access !== 'owner' && (
                    <span className="ml-1 text-[10px] bg-purple-100 text-purple-700 px-1 rounded">super-admin</span>
                  )}
                  {host.my_access === 'shared' && (
                    <span className="ml-1 text-[10px] bg-green-100 text-green-700 px-1 rounded">наданий доступ</span>
                  )}
                </div>
              )}
              <div className="mt-2">
                <button
                  onClick={() => setShareOpen(true)}
                  className="bg-blue-50 text-blue-700 hover:bg-blue-100 text-xs px-3 py-1 rounded border border-blue-200"
                >
                  Поділитися доступом
                </button>
              </div>
            </div>
          </div>

          {/* Big-stat KPIs */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mt-5">
            <Kpi label="CPU"   value={latest.cpu}   suffix="%" />
            <Kpi label="RAM"   value={latest.ram}   suffix="%" />
            <Kpi label="Disk"  value={latest.disk}  suffix="%" />
            <Kpi label="Inode" value={latest.inode} suffix="%" />
          </div>
        </div>

        {/* CPU + RAM chart */}
        <ChartCard title="Процесор і пам'ять">
          <ResponsiveContainer width="100%" height={240}>
            <AreaChart data={series} margin={{ top: 10, right: 10, left: 0, bottom: 0 }}>
              <defs>
                <linearGradient id="g-cpu" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#6366f1" stopOpacity={0.3} />
                  <stop offset="100%" stopColor="#6366f1" stopOpacity={0} />
                </linearGradient>
                <linearGradient id="g-ram" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#10b981" stopOpacity={0.3} />
                  <stop offset="100%" stopColor="#10b981" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#eee" />
              <XAxis dataKey="time" tick={{ fontSize: 10 }} />
              <YAxis domain={[0, 100]} tick={{ fontSize: 10 }} unit="%" />
              <Tooltip />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              <Area type="monotone" dataKey="cpu" stroke="#6366f1" fill="url(#g-cpu)" name="CPU (%)" strokeWidth={2} />
              <Area type="monotone" dataKey="ram" stroke="#10b981" fill="url(#g-ram)" name="RAM (%)" strokeWidth={2} />
            </AreaChart>
          </ResponsiveContainer>
        </ChartCard>

        {/* Disk I/O */}
        <ChartCard title="Диск I/O" subtitle="Швидкість читання/запису в байтах за секунду">
          <ResponsiveContainer width="100%" height={200}>
            <LineChart data={series}>
              <CartesianGrid strokeDasharray="3 3" stroke="#eee" />
              <XAxis dataKey="time" tick={{ fontSize: 10 }} />
              <YAxis tick={{ fontSize: 10 }} tickFormatter={formatBytesPerSec} />
              <Tooltip formatter={(v) => formatBytesPerSec(v)} />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              <Line type="monotone" dataKey="diskRead"  stroke="#3b82f6" name="Read"  strokeWidth={2} dot={false} />
              <Line type="monotone" dataKey="diskWrite" stroke="#ef4444" name="Write" strokeWidth={2} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </ChartCard>

        {/* Network: External vs Internal */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <ChartCard title="External bandwidth" subtitle="Трафік через інтерфейс default-route">
            <NetChart data={series} rxKey="extRx" txKey="extTx" />
          </ChartCard>
          <ChartCard title="Internal bandwidth" subtitle="Сума решти інтерфейсів (окрім lo)">
            <NetChart data={series} rxKey="intRx" txKey="intTx" />
          </ChartCard>
        </div>

        {/* Containers */}
        <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-5 mb-6">
          <h3 className="text-base font-semibold text-gray-800 mb-3">
            Контейнери ({containers.length})
          </h3>
          {containers.length === 0 ? (
            <div className="text-sm text-gray-400">Контейнерів не знайдено.</div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="text-left text-gray-500 border-b">
                  <tr>
                    <th className="py-2 pr-4">ID</th>
                    <th className="pr-4">Назва</th>
                    <th className="pr-4">Стан</th>
                    <th className="pr-4 text-right">CPU</th>
                    <th className="text-right">RAM</th>
                  </tr>
                </thead>
                <tbody>
                  {containers.map((c) => (
                    <tr key={c.container_id} className="border-b hover:bg-gray-50">
                      <td className="py-1.5 pr-4 font-mono text-xs text-gray-500">{c.container_id}</td>
                      <td className="pr-4 font-medium">{c.name}</td>
                      <td className="pr-4">
                        <span className={`text-xs px-2 py-0.5 rounded ${
                          c.state === 'running' ? 'bg-green-50 text-green-700' : 'bg-gray-100 text-gray-500'
                        }`}>
                          {c.state}
                        </span>
                      </td>
                      <td className={`pr-4 text-right tabular-nums ${usageColor(c.cpu_percent)}`}>
                        {Number(c.cpu_percent).toFixed(1)}%
                      </td>
                      <td className={`text-right tabular-nums ${usageColor(c.ram_percent)}`}>
                        {Number(c.ram_percent).toFixed(1)}%
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>

      <HostAccessModal
        open={shareOpen}
        onClose={() => setShareOpen(false)}
        hostId={host.id}
        hostName={host.name}
      />
    </div>
  );
}

function Kpi({ label, value, suffix }) {
  const v = value ?? 0;
  return (
    <div className="bg-gray-50 border border-gray-100 rounded-lg p-3">
      <div className="text-xs text-gray-500 mb-1">{label}</div>
      <div className={`text-2xl font-bold tabular-nums ${usageColor(v)}`}>
        {value == null ? '—' : v.toFixed(1)}
        {suffix && <span className="text-sm text-gray-400 ml-0.5">{suffix}</span>}
      </div>
      <div className="h-1.5 bg-gray-200 rounded mt-2 overflow-hidden">
        <div
          className={`h-full ${
            v >= 90 ? 'bg-red-500' : v >= 75 ? 'bg-orange-500' : v >= 50 ? 'bg-yellow-500' : 'bg-green-500'
          }`}
          style={{ width: `${Math.min(100, v)}%` }}
        />
      </div>
    </div>
  );
}

function ChartCard({ title, subtitle, children }) {
  return (
    <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-5 mb-6">
      <div className="mb-3">
        <h3 className="text-base font-semibold text-gray-800">{title}</h3>
        {subtitle && <div className="text-xs text-gray-500 mt-0.5">{subtitle}</div>}
      </div>
      {children}
    </div>
  );
}

function NetChart({ data, rxKey, txKey }) {
  return (
    <ResponsiveContainer width="100%" height={200}>
      <LineChart data={data}>
        <CartesianGrid strokeDasharray="3 3" stroke="#eee" />
        <XAxis dataKey="time" tick={{ fontSize: 10 }} />
        <YAxis tick={{ fontSize: 10 }} tickFormatter={formatBytesPerSec} />
        <Tooltip formatter={(v) => formatBytesPerSec(v)} />
        <Legend wrapperStyle={{ fontSize: 12 }} />
        <Line type="monotone" dataKey={rxKey} stroke="#06b6d4" name="RX" strokeWidth={2} dot={false} />
        <Line type="monotone" dataKey={txKey} stroke="#f97316" name="TX" strokeWidth={2} dot={false} />
      </LineChart>
    </ResponsiveContainer>
  );
}
