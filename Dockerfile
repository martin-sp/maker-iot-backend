# Dockerfile para Red Maker IoT Backend
FROM python:3.11-slim

# Metadata
LABEL maintainer="Red Maker IoT"
LABEL description="Backend para sensores ESP32 de temperatura y humedad"

# Establecer directorio de trabajo
WORKDIR /app

# Copiar archivo de dependencias
COPY requirements.txt .

# Instalar dependencias
RUN pip install --no-cache-dir -r requirements.txt

# Copiar código de la aplicación
COPY app.py .

# Crear directorio para la base de datos
RUN mkdir -p /app/data

# Exponer puerto
EXPOSE 8000

# Variables de entorno
ENV DATABASE_PATH=/app/data/maker_iot.db
ENV PYTHONUNBUFFERED=1

# Comando para iniciar la aplicación
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]