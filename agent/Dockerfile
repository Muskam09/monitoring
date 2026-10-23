FROM golang:1.27-alpine AS builder

WORKDIR /app
COPY go.mod go.sum ./
RUN go mod download

COPY main.go ./
# Компілюємо статичний бінарний файл без залежностей від CGO
RUN CGO_ENABLED=0 GOOS=linux go build -a -installsuffix cgo -o monitoring-agent .

# Етап 2: Створення мінімального образу
FROM alpine:latest

WORKDIR /root/
COPY --from=builder /app/monitoring-agent .

CMD ["./monitoring-agent"]