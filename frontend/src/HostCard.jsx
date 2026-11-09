import { Link } from 'react-router-dom';
import { formatUptime, usageBarColor, usageColor } from './format';

/** Summary card for one host — rendered in the main grid. */
export default function HostCard({ host }) {
  const Gauge = ({ label, value }) => (
    <div>
      <div className="flex justify-between text-xs mb-1">
        <span className="text-gray-500">{label}</span>
        <span className={`font-semibold tabular-nums ${usageColor(value)}`}>
          {value == null ? '—' : `${value.toFixed(0)}%`}
        </span>
      </div>
      <div className="h-1.5 bg-gray-100 rounded overflow-hidden">
        <div
          className={`h-full transition-all ${usageBarColor(value)}`}
          style={{ width: `${Math.min(100, value ?? 0)}%` }}
        />
      </div>
    </div>
  );

  return (
    <Link
      to={`/host/${host.id}`}
      className="block bg-white border border-gray-200 hover:border-blue-400 hover:shadow-md
                 rounded-xl p-4 transition-all duration-150 group"
    >
      <div className="flex items-start justify-between mb-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span
              className={`inline-block w-2.5 h-2.5 rounded-full flex-shrink-0 ${
                host.is_online ? 'bg-green-500 animate-pulse' : 'bg-gray-400'
              }`}
              title={host.is_online ? 'Онлайн' : 'Офлайн'}
            />
            <h3 className="font-semibold text-gray-800 truncate group-hover:text-blue-600">
              {host.name}
            </h3>
            {host.my_access === 'owner' && (
              <span className="text-[9px] bg-blue-100 text-blue-700 rounded px-1 font-medium flex-shrink-0">
                owner
              </span>
            )}
            {host.my_access === 'shared' && (
              <span className="text-[9px] bg-green-100 text-green-700 rounded px-1 font-medium flex-shrink-0">
                shared
              </span>
            )}
          </div>
          <div className="text-xs text-gray-500 mt-0.5 truncate font-mono">
            {host.ip_address || '—'}{host.port ? `:${host.port}` : ''}
          </div>
          {host.owner_username && host.my_access !== 'owner' && (
            <div className="text-[10px] text-gray-400 mt-0.5">
              власник: {host.owner_username}
            </div>
          )}
        </div>
        <span className={`text-[10px] px-2 py-0.5 rounded-full font-medium ${
          host.is_online
            ? 'bg-green-50 text-green-700 border border-green-200'
            : 'bg-gray-50 text-gray-500 border border-gray-200'
        }`}>
          {host.is_online ? 'ONLINE' : 'OFFLINE'}
        </span>
      </div>

      {host.os_info && (
        <div className="text-[11px] text-gray-500 mb-3 truncate" title={host.os_info}>
          {host.os_info}
        </div>
      )}

      <div className="space-y-2">
        <Gauge label="CPU"   value={host.cpu_percent} />
        <Gauge label="RAM"   value={host.ram_percent} />
        <Gauge label="Disk"  value={host.disk_percent} />
      </div>

      <div className="flex justify-between text-[11px] text-gray-400 mt-3 pt-3 border-t border-gray-100">
        <span>Uptime: {formatUptime(host.uptime_seconds)}</span>
        <span>
          {host.last_seen_at
            ? `heartbeat ${new Date(host.last_seen_at).toLocaleTimeString()}`
            : 'очікування…'}
        </span>
      </div>
    </Link>
  );
}
