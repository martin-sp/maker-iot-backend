"""
Backend Red Maker IoT - Servidor Completo
FastAPI + SQLite

Este archivo es parte del proyecto Docker
"""

from fastapi import FastAPI, HTTPException, Header
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, String, Integer, Float, DateTime, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime
from typing import Optional
import secrets
import os

# ============================================
# CONFIGURACIÓN BASE DE DATOS
# ============================================
DATABASE_PATH = os.getenv("DATABASE_PATH", "./data/maker_iot.db")
SQLALCHEMY_DATABASE_URL = f"sqlite:///{DATABASE_PATH}"

# Crear directorio data si no existe
os.makedirs(os.path.dirname(DATABASE_PATH), exist_ok=True)

engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# ============================================
# MODELOS DE BASE DE DATOS
# ============================================
class ActivationCode(Base):
    __tablename__ = "activation_codes"
    
    id = Column(Integer, primary_key=True, index=True)
    code = Column(String, unique=True, index=True)
    sede_id = Column(String)
    sede_nombre = Column(String)
    is_used = Column(Boolean, default=False)
    used_by_mac = Column(String, nullable=True)
    used_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class Device(Base):
    __tablename__ = "devices"
    
    id = Column(Integer, primary_key=True, index=True)
    mac_address = Column(String, unique=True, index=True)
    sede_id = Column(String)
    sede_nombre = Column(String)
    api_key = Column(String, unique=True)
    activated_at = Column(DateTime, default=datetime.utcnow)
    last_seen = Column(DateTime, default=datetime.utcnow)

class SensorData(Base):
    __tablename__ = "sensor_data"
    
    id = Column(Integer, primary_key=True, index=True)
    mac_address = Column(String, index=True)
    temperatura = Column(Float)
    humedad = Column(Float)
    timestamp = Column(DateTime, default=datetime.utcnow)

# Crear tablas
Base.metadata.create_all(bind=engine)

# ============================================
# MODELOS PYDANTIC (VALIDACIÓN)
# ============================================
class ActivateRequest(BaseModel):
    code: str
    mac_address: str

class UpdateRequest(BaseModel):
    temperatura: float
    humedad: float

class CreateCodeRequest(BaseModel):
    code: str
    sede_id: str
    sede_nombre: str

# ============================================
# FASTAPI APP
# ============================================
app = FastAPI(
    title="Red Maker IoT API",
    version="1.0.0",
    description="Backend para sensores ESP32 de temperatura y humedad"
)

# CORS (permitir peticiones desde cualquier origen)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================
# FUNCIONES AUXILIARES
# ============================================
def generate_api_key():
    """Generar API key única de 64 caracteres"""
    return secrets.token_urlsafe(48)

# ============================================
# ENDPOINTS DE LA API
# ============================================

@app.get("/")
def root():
    """Endpoint raíz - Info del servidor"""
    return {
        "service": "Red Maker IoT Backend",
        "version": "1.0.0",
        "status": "online",
        "timestamp": datetime.utcnow().isoformat(),
        "endpoints": {
            "activate": "POST /api/activate",
            "updates": "POST /api/updates",
            "devices": "GET /api/devices",
            "sensor_data": "GET /api/sensor-data/{mac_address}",
            "create_code": "POST /api/activation-codes",
            "list_codes": "GET /api/activation-codes",
            "panel": "GET /panel",
            "docs": "GET /docs"
        }
    }

@app.get("/health")
def health_check():
    """Health check para monitoreo"""
    db = SessionLocal()
    try:
        device_count = db.query(Device).count()
        db.close()
        return {
            "status": "healthy",
            "database": "connected",
            "devices": device_count,
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat()
        }

@app.post("/api/activate")
def activate_device(request: ActivateRequest):
    """
    Activar un dispositivo ESP32 con código de activación
    """
    db = SessionLocal()
    
    try:
        # Buscar código de activación
        activation = db.query(ActivationCode).filter(
            ActivationCode.code == request.code.upper()
        ).first()
        
        if not activation:
            raise HTTPException(status_code=404, detail="Código de activación no encontrado")
        
        if activation.is_used:
            raise HTTPException(
                status_code=422, 
                detail=f"Código ya utilizado por {activation.used_by_mac}"
            )
        
        # Verificar si el dispositivo ya existe
        existing_device = db.query(Device).filter(
            Device.mac_address == request.mac_address
        ).first()
        
        if existing_device:
            # Dispositivo ya registrado, devolver su API key existente
            return {
                "success": True,
                "sede_id": existing_device.sede_id,
                "sede_nombre": existing_device.sede_nombre,
                "api_key": existing_device.api_key,
                "message": "Dispositivo ya estaba registrado"
            }
        
        # Generar API key
        api_key = generate_api_key()
        
        # Crear dispositivo
        device = Device(
            mac_address=request.mac_address,
            sede_id=activation.sede_id,
            sede_nombre=activation.sede_nombre,
            api_key=api_key
        )
        db.add(device)
        
        # Marcar código como usado
        activation.is_used = True
        activation.used_by_mac = request.mac_address
        activation.used_at = datetime.utcnow()
        
        db.commit()
        
        return {
            "success": True,
            "sede_id": activation.sede_id,
            "sede_nombre": activation.sede_nombre,
            "api_key": api_key,
            "message": "Dispositivo activado exitosamente"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error interno: {str(e)}")
    finally:
        db.close()

@app.post("/api/updates")
def receive_sensor_data(
    request: UpdateRequest,
    x_api_key: str = Header(None, alias="X-API-Key")
):
    """
    Recibir datos de sensores de un ESP32
    """
    if not x_api_key:
        raise HTTPException(status_code=401, detail="API Key requerida en header X-API-Key")
    
    db = SessionLocal()
    
    try:
        # Buscar dispositivo por API key
        device = db.query(Device).filter(Device.api_key == x_api_key).first()
        
        if not device:
            raise HTTPException(status_code=401, detail="API Key inválida")
        
        # Guardar datos del sensor
        sensor_data = SensorData(
            mac_address=device.mac_address,
            temperatura=request.temperatura,
            humedad=request.humedad
        )
        db.add(sensor_data)
        
        # Actualizar última conexión del dispositivo
        device.last_seen = datetime.utcnow()
        
        db.commit()
        
        return {
            "success": True,
            "message": "Datos recibidos correctamente",
            "sede": device.sede_nombre,
            "mac_address": device.mac_address,
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error interno: {str(e)}")
    finally:
        db.close()

@app.get("/api/devices")
def list_devices():
    """Listar todos los dispositivos registrados"""
    db = SessionLocal()
    devices = db.query(Device).all()
    db.close()
    
    return {
        "total": len(devices),
        "devices": [
            {
                "mac_address": d.mac_address,
                "sede_id": d.sede_id,
                "sede_nombre": d.sede_nombre,
                "activated_at": d.activated_at.isoformat(),
                "last_seen": d.last_seen.isoformat()
            }
            for d in devices
        ]
    }

@app.get("/api/sensor-data/{mac_address}")
def get_sensor_data(mac_address: str, limit: int = 100):
    """Obtener datos de sensores de un dispositivo específico"""
    db = SessionLocal()
    data = db.query(SensorData).filter(
        SensorData.mac_address == mac_address
    ).order_by(SensorData.timestamp.desc()).limit(limit).all()
    db.close()
    
    return {
        "mac_address": mac_address,
        "total_records": len(data),
        "data": [
            {
                "temperatura": d.temperatura,
                "humedad": d.humedad,
                "timestamp": d.timestamp.isoformat()
            }
            for d in data
        ]
    }

@app.post("/api/activation-codes")
def create_activation_code(request: CreateCodeRequest):
    """Crear un nuevo código de activación"""
    db = SessionLocal()
    
    try:
        # Verificar si el código ya existe
        existing = db.query(ActivationCode).filter(
            ActivationCode.code == request.code.upper()
        ).first()
        
        if existing:
            raise HTTPException(status_code=409, detail="Código ya existe")
        
        # Crear código
        code = ActivationCode(
            code=request.code.upper(),
            sede_id=request.sede_id,
            sede_nombre=request.sede_nombre
        )
        db.add(code)
        db.commit()
        
        return {
            "success": True,
            "code": code.code,
            "sede_nombre": code.sede_nombre,
            "message": "Código de activación creado exitosamente"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error interno: {str(e)}")
    finally:
        db.close()

@app.get("/api/activation-codes")
def list_activation_codes():
    """Listar todos los códigos de activación"""
    db = SessionLocal()
    codes = db.query(ActivationCode).all()
    db.close()
    
    return {
        "total": len(codes),
        "available": len([c for c in codes if not c.is_used]),
        "used": len([c for c in codes if c.is_used]),
        "codes": [
            {
                "code": c.code,
                "sede_id": c.sede_id,
                "sede_nombre": c.sede_nombre,
                "is_used": c.is_used,
                "used_by_mac": c.used_by_mac,
                "used_at": c.used_at.isoformat() if c.used_at else None,
                "created_at": c.created_at.isoformat()
            }
            for c in codes
        ]
    }

@app.get("/panel", response_class=HTMLResponse)
def admin_panel():
    """Panel web para visualizar dispositivos y datos"""
    db = SessionLocal()
    devices = db.query(Device).all()
    codes = db.query(ActivationCode).all()
    total_readings = db.query(SensorData).count()
    
    # Obtener últimas lecturas de cada dispositivo
    latest_data = {}
    for device in devices:
        last_reading = db.query(SensorData).filter(
            SensorData.mac_address == device.mac_address
        ).order_by(SensorData.timestamp.desc()).first()
        latest_data[device.mac_address] = last_reading
    
    db.close()
    
    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Servicio IoT Marthink - Panel de Control</title>
        <style>
            * { margin: 0; padding: 0; box-sizing: border-box; }
            body { 
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; 
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                min-height: 100vh;
                padding: 20px;
            }
            .container { 
                max-width: 1400px; 
                margin: 0 auto; 
                background: white;
                border-radius: 20px;
                box-shadow: 0 20px 60px rgba(0,0,0,0.3);
                overflow: hidden;
            }
            .header {
                background: linear-gradient(135deg, #1e3a5f 0%, #2c5282 100%);
                color: white;
                padding: 30px;
                text-align: center;
            }
            .header h1 { font-size: 36px; margin-bottom: 10px; }
            .header p { opacity: 0.9; font-size: 14px; }
            
            .stats { 
                display: grid; 
                grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); 
                gap: 20px; 
                padding: 30px;
                background: #f8f9fa;
            }
            .stat-card { 
                background: white;
                padding: 25px; 
                border-radius: 15px; 
                box-shadow: 0 5px 15px rgba(0,0,0,0.1);
                border-left: 5px solid #667eea;
            }
            .stat-value { font-size: 42px; font-weight: bold; color: #1e3a5f; margin-bottom: 5px; }
            .stat-label { font-size: 14px; color: #666; text-transform: uppercase; letter-spacing: 1px; }
            
            .content { padding: 30px; }
            .section { margin-bottom: 40px; }
            .section h2 { 
                color: #1e3a5f; 
                margin-bottom: 20px; 
                padding-bottom: 10px;
                border-bottom: 3px solid #667eea;
                font-size: 24px;
            }
            
            .card { 
                background: white; 
                padding: 0; 
                border-radius: 12px; 
                box-shadow: 0 2px 10px rgba(0,0,0,0.1);
                overflow: hidden;
            }
            
            table { width: 100%; border-collapse: collapse; }
            thead { background: #1e3a5f; color: white; }
            th, td { padding: 16px; text-align: left; }
            th { font-weight: 600; text-transform: uppercase; font-size: 12px; letter-spacing: 1px; }
            tbody tr { border-bottom: 1px solid #e0e0e0; transition: background 0.2s; }
            tbody tr:hover { background: #f8f9fa; }
            
            .badge { 
                padding: 6px 12px; 
                border-radius: 20px; 
                font-size: 12px; 
                font-weight: bold;
                display: inline-block;
            }
            .badge-success { background: #10b981; color: white; }
            .badge-warning { background: #f59e0b; color: white; }
            .badge-danger { background: #ef4444; color: white; }
            
            code { 
                background: #f1f3f5; 
                padding: 4px 8px; 
                border-radius: 4px; 
                font-family: 'Courier New', monospace;
                font-size: 13px;
                color: #e91e63;
            }
            
            .empty-state {
                text-align: center;
                padding: 60px 20px;
                color: #666;
            }
            .empty-state svg {
                width: 80px;
                height: 80px;
                margin-bottom: 20px;
                opacity: 0.3;
            }
            
            .footer {
                background: #f8f9fa;
                padding: 20px 30px;
                text-align: center;
                color: #666;
                font-size: 14px;
                border-top: 1px solid #e0e0e0;
            }
            
            .api-list {
                background: #e0f2fe;
                padding: 25px;
                border-radius: 12px;
                margin-top: 20px;
            }
            .api-list h3 { color: #1e3a5f; margin-bottom: 15px; }
            .api-list ul { list-style: none; }
            .api-list li { 
                padding: 10px 0; 
                border-bottom: 1px solid #bae6fd;
            }
            .api-list li:last-child { border-bottom: none; }
            .api-list strong { color: #0c4a6e; }
            
            @keyframes pulse {
                0%, 100% { opacity: 1; }
                50% { opacity: 0.5; }
            }
            .online-indicator { 
                display: inline-block;
                width: 8px;
                height: 8px;
                border-radius: 50%;
                background: #10b981;
                animation: pulse 2s infinite;
                margin-right: 6px;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>🌡️ Red Maker IoT</h1>
                <p>Panel de Control - Sistema de Monitoreo de Sensores</p>
            </div>
            
            <div class="stats">
                <div class="stat-card">
                    <div class="stat-value">""" + str(len(devices)) + """</div>
                    <div class="stat-label">📱 Dispositivos Activos</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value">""" + str(len([c for c in codes if not c.is_used])) + """</div>
                    <div class="stat-label">🔑 Códigos Disponibles</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value">""" + str(total_readings) + """</div>
                    <div class="stat-label">📊 Lecturas Totales</div>
                </div>
            </div>
            
            <div class="content">
                <div class="section">
                    <h2>📱 Dispositivos Registrados</h2>
                    <div class="card">
    """
    
    if devices:
        html += """
                        <table>
                            <thead>
                                <tr>
                                    <th>Estado</th>
                                    <th>MAC Address</th>
                                    <th>Sede</th>
                                    <th>Temperatura</th>
                                    <th>Humedad</th>
                                    <th>Última Conexión</th>
                                </tr>
                            </thead>
                            <tbody>
        """
        
        for device in devices:
            last_data = latest_data.get(device.mac_address)
            temp = f"{last_data.temperatura:.1f}°C" if last_data else "Sin datos"
            hum = f"{last_data.humedad:.0f}%" if last_data else "Sin datos"
            
            # Calcular tiempo desde última conexión
            time_diff = (datetime.utcnow() - device.last_seen).total_seconds()
            if time_diff < 600:  # 10 minutos
                status = '<span class="badge badge-success"><span class="online-indicator"></span>Online</span>'
            elif time_diff < 3600:  # 1 hora
                status = '<span class="badge badge-warning">Inactivo</span>'
            else:
                status = '<span class="badge badge-danger">Offline</span>'
            
            html += f"""
                                <tr>
                                    <td>{status}</td>
                                    <td><code>{device.mac_address}</code></td>
                                    <td><strong>{device.sede_nombre}</strong><br><small style="color:#666;">{device.sede_id}</small></td>
                                    <td><strong>{temp}</strong></td>
                                    <td><strong>{hum}</strong></td>
                                    <td>{device.last_seen.strftime('%Y-%m-%d %H:%M:%S')}</td>
                                </tr>
            """
        
        html += """
                            </tbody>
                        </table>
        """
    else:
        html += """
                        <div class="empty-state">
                            <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
                            </svg>
                            <h3>No hay dispositivos registrados</h3>
                            <p>Activa tu primer ESP32 con un código de activación</p>
                        </div>
        """
    
    html += """
                    </div>
                </div>
                
                <div class="section">
                    <h2>🔑 Códigos de Activación</h2>
                    <div class="card">
    """
    
    if codes:
        html += """
                        <table>
                            <thead>
                                <tr>
                                    <th>Código</th>
                                    <th>Sede</th>
                                    <th>Estado</th>
                                    <th>Usado por</th>
                                    <th>Fecha de uso</th>
                                </tr>
                            </thead>
                            <tbody>
        """
        
        for code in codes:
            if code.is_used:
                status = '<span class="badge badge-danger">Usado</span>'
                used_by = f'<code>{code.used_by_mac}</code>' if code.used_by_mac else '-'
                used_date = code.used_at.strftime('%Y-%m-%d %H:%M:%S') if code.used_at else "-"
            else:
                status = '<span class="badge badge-success">Disponible</span>'
                used_by = '-'
                used_date = '-'
            
            html += f"""
                                <tr>
                                    <td><code style="font-size:14px;font-weight:bold;">{code.code}</code></td>
                                    <td><strong>{code.sede_nombre}</strong><br><small style="color:#666;">{code.sede_id}</small></td>
                                    <td>{status}</td>
                                    <td>{used_by}</td>
                                    <td>{used_date}</td>
                                </tr>
            """
        
        html += """
                            </tbody>
                        </table>
        """
    else:
        html += """
                        <div class="empty-state">
                            <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 7a2 2 0 012 2m4 0a6 6 0 01-7.743 5.743L11 17H9v2H7v2H4a1 1 0 01-1-1v-2.586a1 1 0 01.293-.707l5.964-5.964A6 6 0 1121 9z" />
                            </svg>
                            <h3>No hay códigos de activación</h3>
                            <p>Crea códigos desde la API o base de datos</p>
                        </div>
        """
    
    html += """
                    </div>
                </div>
                
                <div class="api-list">
                    <h3>📚 Endpoints API Disponibles</h3>
                    <ul>
                        <li><strong>POST /api/activate</strong> - Activar dispositivo ESP32</li>
                        <li><strong>POST /api/updates</strong> - Recibir datos de sensores</li>
                        <li><strong>GET /api/devices</strong> - Listar todos los dispositivos</li>
                        <li><strong>GET /api/sensor-data/{mac_address}</strong> - Datos de un dispositivo</li>
                        <li><strong>POST /api/activation-codes</strong> - Crear código de activación</li>
                        <li><strong>GET /api/activation-codes</strong> - Listar códigos</li>
                        <li><strong>GET /docs</strong> - Documentación interactiva (Swagger UI)</li>
                    </ul>
                </div>
            </div>
            
            <div class="footer">
                <p><strong>Red Maker IoT</strong> - Sistema de Monitoreo de Sensores ESP32</p>
                <p style="margin-top:10px;font-size:12px;">Documentación completa: <a href="/docs" style="color:#667eea;">http://localhost:8000/docs</a></p>
            </div>
        </div>
        
        <script>
            // Auto-refresh cada 30 segundos
            setTimeout(() => location.reload(), 30000);
        </script>
    </body>
    </html>
    """
    
    return html

# ============================================
# INICIALIZACIÓN
# ============================================
# ... (código anterior)

# ============================================
# INICIALIZACIÓN
# ============================================
def init_database():
    """Crear códigos de activación de ejemplo si no existen"""
    db = SessionLocal()
    
    try:
        # Verificar si ya existen códigos
        existing = db.query(ActivationCode).count()
        if existing > 0:
            print(f"✅ Base de datos inicializada ({existing} códigos existentes)")
            db.close()
            return
        
        # Crear códigos de ejemplo
        sample_codes = [
            {"code": "REM-SANPED-2025-EZPZ", "sede_id": "SANPED-001", "sede_nombre": "San Pedro Centro"},
            {"code": "REM-SANPED-2025-TEST", "sede_id": "SANPED-002", "sede_nombre": "San Pedro Norte"},
            {"code": "REM-POSADAS-2025-ABC", "sede_id": "POSADAS-001", "sede_nombre": "Posadas Centro"},
            {"code": "REM-OBERA-2025-XYZ", "sede_id": "OBERA-001", "sede_nombre": "Oberá Centro"},
            {"code": "REM-ELDORADO-2025-123", "sede_id": "ELDORADO-001", "sede_nombre": "Eldorado Centro"},
        ]
        
        for data in sample_codes:
            code = ActivationCode(**data)
            db.add(code)
        
        db.commit()
        print(f"✅ Base de datos inicializada ({len(sample_codes)} códigos creados)")
        
    except Exception as e:
        print(f"❌ Error inicializando base de datos: {e}")
        db.rollback()
    finally:
        db.close()

# Inicializar al arrancar
init_database()

# ============================================
# EJECUTAR SERVIDOR
# ============================================
if __name__ == "__main__":
    import uvicorn
    
    print("\n" + "="*60)
    print("🚀 Red Maker IoT - Backend Server")
    print("="*60)
    print("\n📡 Servidor iniciando...")
    print("   - API: http://localhost:8000")
    print("   - Docs: http://localhost:8000/docs")
    print("   - Panel: http://localhost:8000/panel")
    print("\n💡 Para usar con ESP32:")
    print("   - Servidor: 192.168.1.4:8000")
    print("\n" + "="*60 + "\n")
    
    # Iniciar servidor

    uvicorn.run(app, host="0.0.0.0", port=8000)
