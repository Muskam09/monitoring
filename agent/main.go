package main

import (
	"bytes"
	"context"
	"encoding/json"
	"log"
	"net/http"
	"os"
	"strings"
	"time"

	"github.com/docker/docker/api/types/container"
	"github.com/docker/docker/client"
	"github.com/shirou/gopsutil/v3/cpu"
	"github.com/shirou/gopsutil/v3/disk"
	"github.com/shirou/gopsutil/v3/mem"
)

// Структури, які точно відповідають Pydantic-схемам на бекенді
type ContainerMetric struct {
	ContainerID string  `json:"container_id"`
	Name        string  `json:"name"`
	State       string  `json:"state"`
	CPUPercent  float64 `json:"cpu_percent"`
	RAMPercent  float64 `json:"ram_percent"`
}

type HostMetric struct {
	CPUPercent  float64           `json:"cpu_percent"`
	RAMPercent  float64           `json:"ram_percent"`
	DiskPercent float64           `json:"disk_percent"`
	Containers  []ContainerMetric `json:"containers"`
}

func main() {
	apiURL := os.Getenv("API_URL")
	apiToken := os.Getenv("API_TOKEN")

	if apiURL == "" || apiToken == "" {
		log.Fatal("API_URL та API_TOKEN повинні бути задані як змінні середовища")
	}

	// Ініціалізація Docker клієнта
	cli, err := client.NewClientWithOpts(client.FromEnv, client.WithAPIVersionNegotiation())
	if err != nil {
		log.Printf("Попередження: не вдалося підключитися до Docker (%v)\n", err)
	}

	log.Println("Агент успішно запущено. Збір метрик кожні 15 секунд...")

	ticker := time.NewTicker(15 * time.Second)
	defer ticker.Stop()

	for range ticker.C {
		collectAndSendMetrics(apiURL, apiToken, cli)
	}
}

func collectAndSendMetrics(apiURL, apiToken string, cli *client.Client) {
	// 1. Збір метрик Хоста
	cpuPercents, _ := cpu.Percent(0, false)
	cpuUsage := 0.0
	if len(cpuPercents) > 0 {
		cpuUsage = cpuPercents[0]
	}

	vMem, _ := mem.VirtualMemory()
	diskStat, _ := disk.Usage("/")

	var containers []ContainerMetric

	// 2. Збір інформації про Docker-контейнери
	if cli != nil {
		ctx := context.Background()
		containerList, err := cli.ContainerList(ctx, container.ListOptions{All: true})
		if err == nil {
			for _, c := range containerList {
				name := "unknown"
				if len(c.Names) > 0 {
					name = strings.TrimPrefix(c.Names[0], "/")
				}
				
				containers = append(containers, ContainerMetric{
					ContainerID: c.ID[:12],
					Name:        name,
					State:       c.State,
					CPUPercent:  0.0, // Для спрощення MVP залишаємо 0.0, глибокий парсинг Docker Stats можна додати пізніше
					RAMPercent:  0.0,
				})
			}
		}
	}

	payload := HostMetric{
		CPUPercent:  cpuUsage,
		RAMPercent:  vMem.UsedPercent,
		DiskPercent: diskStat.UsedPercent,
		Containers:  containers,
	}

	// 3. Відправка на Backend
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

	client := &http.Client{Timeout: 5 * time.Second}
	resp, err := client.Do(req)
	if err != nil {
		log.Printf("Помилка відправки метрик на %s: %v\n", apiURL, err)
		return
	}
	defer resp.Body.Close()

	if resp.StatusCode == 200 {
		log.Println("Метрики успішно відправлено.")
	} else {
		log.Printf("Сервер повернув помилку: %d\n", resp.StatusCode)
	}
}