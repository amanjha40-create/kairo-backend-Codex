#!/usr/bin/env bash

set -euo pipefail

sudo apt-get update
sudo apt-get install --no-install-recommends -y docker.io nginx curl

sudo systemctl enable docker
sudo systemctl start docker
sudo systemctl enable nginx
sudo systemctl start nginx

sudo usermod -aG docker "${USER}"

sudo mkdir -p /opt/kairo
sudo cp nginx/default.conf /etc/nginx/sites-available/default
sudo nginx -t
sudo systemctl reload nginx

cat <<'EOF'
Bootstrap complete.
Next steps:
1. Create /opt/kairo/.env with production settings.
2. Replace the nginx `server_name` placeholder with your production API hostname.
3. Put HTTPS termination in front of the API before public launch:
   - either add a real nginx 443/TLS server block on this host
   - or place the instance behind an HTTPS load balancer such as ALB + ACM
4. Do not expose host/container port 8000 publicly in security groups.
5. Set `DOCS_ENABLED=false`, `APP_PUBLIC_BASE_URL=https://<api-hostname>`, and `TRUSTED_HOSTS=<api-hostname>` in production env.
6. Attach an IAM role with ECR read and SSM access to the instance.
7. Re-login so the docker group membership is applied to your shell.
EOF
