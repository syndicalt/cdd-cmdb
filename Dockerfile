# Reference CMDB implementation — serves the generated FastAPI + SQLite server.
# Build: docker build -t cdd-cmdb .
# Run:   docker run -p 9090:9090 cdd-cmdb
FROM python:3.12-slim

WORKDIR /app

COPY generated/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY generated/app.py .

ENV PORT=9090
EXPOSE 9090

CMD ["python", "app.py"]
