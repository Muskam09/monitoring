package main

import (
	"bytes"
	"context"
	"encoding/json"
	"log"
	"net/http"
	"os"
	"os/exec"
	"strings"
	"time"

	"github.com/docker/docker/api/types/container"
	"github.com/docker/docker/client"
	"github.com/shirou/gopsutil/v3/cpu"
	"github.com/shirou/gopsutil/v3/disk"
	"github.com/shirou/gopsutil/v3/host"
	"github.com/shirou/gopsutil/v3/mem"
	"github.com/shirou/gopsutil/v3/net"
)

// ─── Payload structs (must mirror schemas.HostMetricCreate) ────────────

type ContainerMetric struct {
	ContainerID string  `json:"container_id"`
	Name        string  `json:"name"`
	State       string  `json:"state"`
	CPUPercent  float64 `json:"cpu_percent"`
	RAMPercent  float64 `json:"ram_percent"`
}

type HostMetric struct {
	CPUPercent           float64           `json:"cpu_percent"`
	RAMPercent           float64           `json:"ram_percent"`
	DiskPercent          float64           `json:"disk_percent"`
	InodePercent         float64           `json:"inode_percent"`
	DiskReadBytesPerSec  float64           `json:"disk_read_bytes_per_sec"`
	DiskWriteBytesPerSec float64           `json:"disk_write_bytes_per_sec"`
	NetExternalRxBps     float64           `json:"net_external_rx_bps"`
	NetExternalTxBps     float64           `json:"net_external_tx_bps"`
	NetInternalRxBps     float64           `json:"net_internal_rx_bps"`
	NetInternalTxBps     float64           `json:"net_internal_tx_bps"`
	OSInfo               string            `json:"os_info,omitempty"`
	UptimeSeconds        *uint64           `json:"uptime_seconds,omitempty"`
	Containers           []ContainerMetric `json:"containers"`
}

// ─── Snapshot caches (used to compute per-second deltas) ───────────────

type diskIOSnapshot struct {
	ReadBytes  uint64
	WriteBytes uint64
	At         time.Time
}

type netIOSnapshot struct {
	Counters map[string]net.IOCountersStat // key = interface name
	At       time.Time
}

type containerStatSnapshot struct {
	// Raw CPU + system counters for a container, used to compute the CPU %
	// between two successive samples (Docker exposes cumulative counters).
	CPUTotalUsage uint64
	SystemUsage   uint64
	OnlineCPUs    uint32
	At            time.Time
}

// ─── Globals (cheap: process is one agent per host) ────────────────────

var (
	tickSeconds   = 15
	externalIFace = "" // detected once at startup via `ip route`
	prevDiskIO    *diskIOSnapshot
	prevNetIO     *netIOSnapshot
	prevContStats = map[string]containerStatSnapshot{}
)

func main() {
	apiURL := os.Getenv("API_URL")
	apiToken := os.Getenv("API_TOKEN")

	if apiURL == "" || apiToken == "" {
		log.Fatal("API_URL та API_TOKEN повинні бути задані як змінні середовища")
	}

	// Detect which network interface carries the default route — we label
	// its traffic as "External" and sum everything else as "Internal".
	// A failure here is non-fatal: we just report everything as Internal.
	externalIFace = detectExternalInterface()
	if externalIFace != "" {
		log.Printf("Інтерфейс для 'External' трафіку: %s", externalIFace)
	} else {
		log.Println("Не вдалося визначити зовнішній інтерфейс — весь трафік буде як 'Internal'")
	}

	cli, err := client.NewClientWithOpts(client.FromEnv, client.WithAPIVersionNegotiation())
	if err != nil {
		log.Printf("Попередження: не вдалося підключитися до Docker (%v)\n", err)
	}

	log.Printf("Агент успішно запущено. Збір метрик кожні %d секунд...", tickSeconds)

	// Prime the delta caches so the first send isn't garbage
	primeDeltaCaches()

	ticker := time.NewTicker(time.Duration(tickSeconds) * time.Second)
	defer ticker.Stop()

	for range ticker.C {
		collectAndSendMetrics(apiURL, apiToken, cli)
	}
}

// ─── Helpers ───────────────────────────────────────────────────────────

func detectExternalInterface() string {
	// `ip route show default` → "default via 172.17.0.1 dev eth0 ..."
	out, err := exec.Command("ip", "route", "show", "default").Output()
	if err != nil || len(out) == 0 {
		return ""
	}
	fields := strings.Fields(string(out))
	for i, f := range fields {
		if f == "dev" && i+1 < len(fields) {
			return fields[i+1]
		}
	}
	return ""
}

func primeDeltaCaches() {
	if io, err := disk.IOCounters(); err == nil {
		var r, w uint64
		for _, s := range io {
			r += s.ReadBytes
			w += s.WriteBytes
		}
		prevDiskIO = &diskIOSnapshot{ReadBytes: r, WriteBytes: w, At: time.Now()}
	}
	if nio, err := net.IOCounters(true); err == nil {
		m := map[string]net.IOCountersStat{}
		for _, s := range nio {
			m[s.Name] = s
		}
		prevNetIO = &netIOSnapshot{Counters: m, At: time.Now()}
	}
}

// Classify an interface as "virtual / don't count":
//
//	lo, docker0, br-*, veth*, cni*, flannel*, tun*, tap*, cali*, lxc*
//
// We still report their traffic as Internal (except lo which we drop).
func isLoopback(name string) bool { return name == "lo" }

// ─── Main collector ────────────────────────────────────────────────────

func collectAndSendMetrics(apiURL, apiToken string, cli *client.Client) {
	payload := HostMetric{}

	// Host CPU
	if p, err := cpu.Percent(0, false); err == nil && len(p) > 0 {
		payload.CPUPercent = p[0]
	}

	// Host RAM
	if v, err := mem.VirtualMemory(); err == nil {
		payload.RAMPercent = v.UsedPercent
	}

	// Host Disk + Inode (root fs)
	if d, err := disk.Usage("/"); err == nil {
		payload.DiskPercent = d.UsedPercent
		payload.InodePercent = d.InodesUsedPercent
	}

	// Disk I/O rate (bytes / second) — across all block devices
	if io, err := disk.IOCounters(); err == nil && prevDiskIO != nil {
		var r, w uint64
		for _, s := range io {
			r += s.ReadBytes
			w += s.WriteBytes
		}
		now := time.Now()
		dt := now.Sub(prevDiskIO.At).Seconds()
		if dt > 0 {
			payload.DiskReadBytesPerSec = float64(r-prevDiskIO.ReadBytes) / dt
			payload.DiskWriteBytesPerSec = float64(w-prevDiskIO.WriteBytes) / dt
		}
		prevDiskIO = &diskIOSnapshot{ReadBytes: r, WriteBytes: w, At: now}
	}

	// Network I/O rate split External vs Internal
	if nio, err := net.IOCounters(true); err == nil && prevNetIO != nil {
		now := time.Now()
		dt := now.Sub(prevNetIO.At).Seconds()
		newMap := map[string]net.IOCountersStat{}
		for _, s := range nio {
			newMap[s.Name] = s
			if isLoopback(s.Name) {
				continue
			}
			prev, ok := prevNetIO.Counters[s.Name]
			if !ok || dt <= 0 {
				continue
			}
			rxRate := float64(s.BytesRecv-prev.BytesRecv) / dt
			txRate := float64(s.BytesSent-prev.BytesSent) / dt
			if s.Name == externalIFace {
				payload.NetExternalRxBps += rxRate
				payload.NetExternalTxBps += txRate
			} else {
				payload.NetInternalRxBps += rxRate
				payload.NetInternalTxBps += txRate
			}
		}
		prevNetIO = &netIOSnapshot{Counters: newMap, At: now}
	}

	// One-off host info (sent every time, backend only fills NULL fields)
	if info, err := host.Info(); err == nil {
		payload.OSInfo = info.Platform + " " + info.PlatformVersion + " (" + info.KernelVersion + ")"
		up := info.Uptime
		payload.UptimeSeconds = &up
	}

	// Docker containers — per-container CPU% / RAM%
	payload.Containers = collectContainerStats(cli)

	// Ship it
	jsonData, err := json.Marshal(payload)
	if err != nil {
		log.Println("Помилка маршалізації JSON:", err)
		return
	}
	req, err := http.NewRequest("POST", apiURL, bytes.NewBuffer(jsonData))
	if err != nil {
		log.Println("Помилка створення запиту:", err)
		return
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-API-Token", apiToken)

	httpClient := &http.Client{Timeout: 5 * time.Second}
	resp, err := httpClient.Do(req)
	if err != nil {
		log.Printf("Помилка відправки метрик на %s: %v\n", apiURL, err)
		return
	}
	defer resp.Body.Close()

	if resp.StatusCode == 200 {
		log.Printf("Метрики відправлено. CPU=%.1f%% RAM=%.1f%% Disk=%.1f%% Inode=%.1f%% containers=%d",
			payload.CPUPercent, payload.RAMPercent, payload.DiskPercent, payload.InodePercent, len(payload.Containers))
	} else {
		log.Printf("Сервер повернув помилку: %d\n", resp.StatusCode)
	}
}

// ─── Per-container stats ───────────────────────────────────────────────

func collectContainerStats(cli *client.Client) []ContainerMetric {
	if cli == nil {
		return nil
	}
	ctx := context.Background()
	containerList, err := cli.ContainerList(ctx, container.ListOptions{All: true})
	if err != nil {
		return nil
	}
	now := time.Now()
	out := make([]ContainerMetric, 0, len(containerList))
	seen := map[string]bool{}

	for _, c := range containerList {
		name := "unknown"
		if len(c.Names) > 0 {
			name = strings.TrimPrefix(c.Names[0], "/")
		}
		m := ContainerMetric{
			ContainerID: c.ID[:12],
			Name:        name,
			State:       c.State,
		}

		// Only pull live stats for RUNNING containers — ContainerStatsOneShot
		// returns zeroes for stopped ones and generates noise in the logs.
		if c.State == "running" {
			cpuPct, ramPct, cpuTotal, sysUsage, online, ok := readOneShotStats(ctx, cli, c.ID)
			if ok {
				prev, hadPrev := prevContStats[c.ID]
				if hadPrev && sysUsage > prev.SystemUsage && cpuTotal > prev.CPUTotalUsage {
					// Standard Docker CPU % formula.
					cpuDelta := float64(cpuTotal - prev.CPUTotalUsage)
					sysDelta := float64(sysUsage - prev.SystemUsage)
					onlineCPUs := float64(online)
					if onlineCPUs == 0 {
						onlineCPUs = 1
					}
					m.CPUPercent = (cpuDelta / sysDelta) * onlineCPUs * 100.0
				} else {
					// First observation for this container — use the embedded %.
					m.CPUPercent = cpuPct
				}
				m.RAMPercent = ramPct
				prevContStats[c.ID] = containerStatSnapshot{
					CPUTotalUsage: cpuTotal, SystemUsage: sysUsage, OnlineCPUs: online, At: now,
				}
				seen[c.ID] = true
			}
		}
		out = append(out, m)
	}

	// Garbage-collect snapshots for containers that no longer exist.
	for id := range prevContStats {
		if !seen[id] {
			delete(prevContStats, id)
		}
	}
	return out
}

// Minimal stats struct — we only decode what we need from the JSON blob
// returned by Docker's /containers/{id}/stats endpoint (OneShot=true).
type dockerStatsLite struct {
	CPUStats struct {
		CPUUsage struct {
			TotalUsage uint64 `json:"total_usage"`
		} `json:"cpu_usage"`
		SystemCPUUsage uint64 `json:"system_cpu_usage"`
		OnlineCPUs     uint32 `json:"online_cpus"`
	} `json:"cpu_stats"`
	PreCPUStats struct {
		CPUUsage struct {
			TotalUsage uint64 `json:"total_usage"`
		} `json:"cpu_usage"`
		SystemCPUUsage uint64 `json:"system_cpu_usage"`
		OnlineCPUs     uint32 `json:"online_cpus"`
	} `json:"precpu_stats"`
	MemoryStats struct {
		Usage uint64 `json:"usage"`
		Limit uint64 `json:"limit"`
	} `json:"memory_stats"`
}

// readOneShotStats calls Docker and returns (cpuPercent, ramPercent,
// cpuTotalUsage, systemUsage, onlineCPUs, ok).
func readOneShotStats(ctx context.Context, cli *client.Client, id string) (float64, float64, uint64, uint64, uint32, bool) {
	resp, err := cli.ContainerStatsOneShot(ctx, id)
	if err != nil {
		return 0, 0, 0, 0, 0, false
	}
	defer resp.Body.Close()
	var s dockerStatsLite
	if err := json.NewDecoder(resp.Body).Decode(&s); err != nil {
		return 0, 0, 0, 0, 0, false
	}

	// CPU % using the precpu_stats embedded in the same response (if available).
	var cpuPct float64
	cpuDelta := float64(s.CPUStats.CPUUsage.TotalUsage) - float64(s.PreCPUStats.CPUUsage.TotalUsage)
	sysDelta := float64(s.CPUStats.SystemCPUUsage) - float64(s.PreCPUStats.SystemCPUUsage)
	online := s.CPUStats.OnlineCPUs
	if online == 0 {
		online = 1
	}
	if sysDelta > 0 && cpuDelta > 0 {
		cpuPct = (cpuDelta / sysDelta) * float64(online) * 100.0
	}

	// RAM %
	var ramPct float64
	if s.MemoryStats.Limit > 0 {
		ramPct = float64(s.MemoryStats.Usage) / float64(s.MemoryStats.Limit) * 100.0
	}

	return cpuPct, ramPct, s.CPUStats.CPUUsage.TotalUsage, s.CPUStats.SystemCPUUsage, online, true
}
