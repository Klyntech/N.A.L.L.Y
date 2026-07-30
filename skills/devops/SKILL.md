---
name: devops
description: Containerization (Docker), CI/CD pipelines (GitHub Actions), infrastructure as code (Terraform), deployment automation. Use for Dockerfiles, compose files, pipelines, cloud infrastructure.
allowed-tools: run_command file_ops
---

# DevOps

Full infrastructure stack: containers, pipelines, IaC.

## Phase 1: Assess Needs

- What's being deployed? (app, service, static site)
- Where? (cloud provider, local, hybrid)
- What's the current setup? (existing Dockerfiles, CI config)
- What's the target state? (auto-deploy on push, manual, scheduled)

## Phase 2: Docker

### Dockerfile Best Practices
```dockerfile
# 1. Use specific base version (not :latest)
FROM python:3.12-slim

# 2. Set working directory
WORKDIR /app

# 3. Copy dependency files first (cache layer)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 4. Copy application code last
COPY . .

# 5. Use non-root user
RUN useradd -m appuser
USER appuser

# 6. Expose port
EXPOSE 8000

# 7. Define startup command
CMD ["python", "main.py"]
```

### Multi-Stage Build
```dockerfile
# Build stage
FROM node:20-alpine AS builder
WORKDIR /app
COPY package*.json .
RUN npm ci
COPY . .
RUN npm run build

# Production stage
FROM nginx:alpine
COPY --from=builder /app/dist /usr/share/nginx/html
EXPOSE 80
```

### Docker Compose
```yaml
version: '3.8'
services:
  app:
    build: .
    ports:
      - "5000:5000"
    environment:
      - DATABASE_URL=postgres://db:5432/mydb
    depends_on:
      db:
        condition: service_healthy
    restart: unless-stopped

  db:
    image: postgres:16-alpine
    volumes:
      - pgdata:/var/lib/postgresql/data
    environment:
      - POSTGRES_DB=mydb
      - POSTGRES_PASSWORD=secret
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
      interval: 5s
      timeout: 5s
      retries: 5

volumes:
  pgdata:
```

### Common Commands
```bash
docker build -t myapp:latest .
docker run -p 5000:5000 myapp
docker compose up -d
docker compose logs -f app
docker exec -it <container> sh
docker system prune -af  # clean up
```

## Phase 3: CI/CD (GitHub Actions)

### Basic Pipeline
```yaml
name: CI/CD

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - run: pip install -r requirements.txt
      - run: pytest

  deploy:
    needs: test
    if: github.ref == 'refs/heads/main'
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Deploy
        run: |
          # Your deploy command here
          echo "Deploying..."
```

### Matrix Builds
```yaml
strategy:
  matrix:
    python-version: ['3.10', '3.11', '3.12']
    os: [ubuntu-latest, windows-latest]
```

### Secrets Management
- Store secrets in GitHub repo settings
- Reference as `${{ secrets.MY_SECRET }}`
- Never log secrets — use `::add-mask::`

## Phase 4: Terraform (IaC)

### Basic Structure
```hcl
# main.tf
terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
  backend "s3" {
    bucket = "my-terraform-state"
    key    = "prod/terraform.tfstate"
    region = "us-east-1"
  }
}

resource "aws_instance" "app" {
  ami           = "ami-0c55b159cbfafe1f0"
  instance_type = "t3.micro"
  
  tags = {
    Name = "myapp-prod"
  }
}
```

### Commands
```bash
terraform init      # Initialize providers
terraform plan      # Preview changes
terraform apply     # Apply changes
terraform destroy   # Tear down
terraform state list  # List resources
```

## Phase 5: Verify

After deployment:
1. Health check passes?
2. Logs show no errors?
3. Can access from outside?
4. Resource usage normal? (`docker stats`, `htop`)

## Guidelines
- Use specific versions, never :latest
- Cache dependency layers in Docker
- Test in CI before deploying
- Use health checks in compose
- Keep secrets out of code and images
