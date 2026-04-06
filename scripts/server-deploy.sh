#!/bin/bash
# ArcWatch server-side deploy script
# Runs as root via SSM on the EC2 instance
set -e

APP_DIR="/opt/arcwatch/app"
S3_BUCKET="pbs-production-static-36f9d155"

echo "=== [1/5] Install Docker if missing ==="
if ! command -v docker > /dev/null 2>&1; then
    if command -v amazon-linux-extras > /dev/null 2>&1; then
        # Amazon Linux 2
        amazon-linux-extras install docker -y
    elif command -v dnf > /dev/null 2>&1; then
        # Amazon Linux 2023
        dnf install -y docker
    else
        yum install -y docker
    fi
    systemctl enable --now docker
fi

# Ensure docker compose v2 plugin is available
if ! docker compose version > /dev/null 2>&1; then
    if command -v dnf > /dev/null 2>&1; then
        dnf install -y docker-compose-plugin 2>/dev/null || true
    else
        yum install -y docker-compose-plugin 2>/dev/null || true
    fi
fi

echo "=== [2/5] Fetch production env ==="
aws s3 cp "s3://$S3_BUCKET/config/arcwatch.env.prod" "$APP_DIR/.env.prod" --region us-east-1
chmod 600 "$APP_DIR/.env.prod"

echo "=== [3/5] Docker compose up ==="
cd "$APP_DIR"
docker compose -f docker-compose.prod.yml pull --quiet 2>/dev/null || true
docker compose -f docker-compose.prod.yml up -d --build
sleep 15
docker compose -f docker-compose.prod.yml ps

echo "=== [4/5] Nginx config ==="
cp "$APP_DIR/scripts/nginx-arcwatch.conf" /etc/nginx/sites-available/arcwatch
ln -sf /etc/nginx/sites-available/arcwatch /etc/nginx/sites-enabled/arcwatch
nginx -t
systemctl reload nginx

echo "=== [5/5] Health check ==="
sleep 5
HTTP=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8001/ 2>/dev/null || echo "000")
echo "Local health check: $HTTP"
if [ "$HTTP" = "000" ] || [ "$HTTP" = "502" ] || [ "$HTTP" = "503" ]; then
    echo "WARNING: web container not responding on 8001 — check logs:"
    docker compose -f "$APP_DIR/docker-compose.prod.yml" logs web --tail=30
fi

echo "=== Deploy complete ==="
