from fastapi import FastAPI, Depends, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from database import engine, get_db
import models, schemas

models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="Custom DevOps Dashboard API")

# Дозвіл на крос-доменні запити від React
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # У продакшені вказується конкретний домен
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def verify_agent_token(x_api_token: str = Header(...), db: Session = Depends(get_db)):
    host = db.query(models.Host).filter(models.Host.api_token == x_api_token).first()
    if not host:
        raise HTTPException(status_code=401, detail="Invalid API token")
    return host

@app.post("/api/telemetry")
def receive_telemetry(payload: schemas.HostMetricCreate, host: models.Host = Depends(verify_agent_token), db: Session = Depends(get_db)):
    db_metric = models.HostMetric(
        host_id=host.id, cpu_percent=payload.cpu_percent,
        ram_percent=payload.ram_percent, disk_percent=payload.disk_percent
    )
    db.add(db_metric)
    db.commit()
    db.refresh(db_metric)

    for container in payload.containers:
        db_container = models.ContainerMetric(
            host_metric_id=db_metric.id, container_id=container.container_id,
            name=container.name, state=container.state,
            cpu_percent=container.cpu_percent, ram_percent=container.ram_percent
        )
        db.add(db_container)
    
    host.is_online = True
    db.commit()
    return {"status": "success", "metric_id": db_metric.id}

# --- НОВІ ЕНДПОІНТИ ДЛЯ FRONTEND ---

@app.get("/api/hosts")
def get_hosts(db: Session = Depends(get_db)):
    return db.query(models.Host).all()

@app.get("/api/hosts/{host_id}/metrics")
def get_host_metrics(host_id: int, db: Session = Depends(get_db)):
    # Повертаємо останні 20 записів для побудови графіка
    return db.query(models.HostMetric).filter(models.HostMetric.host_id == host_id).order_by(models.HostMetric.timestamp.desc()).limit(20).all()