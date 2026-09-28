FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt ./requirements-root.txt
COPY ["Vercel Remake/worker/requirements.txt", "./requirements-worker.txt"]

RUN pip install --no-cache-dir -r requirements-root.txt -r requirements-worker.txt

COPY . .

RUN chmod +x "Vercel Remake/worker/start.sh"

CMD ["sh", "Vercel Remake/worker/start.sh"]
