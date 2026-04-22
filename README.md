# OpenRelik worker notify

## Description
The OpenRelik Notify Worker sends workflow notifications to Discord.

## Task configuration
- `message` (`textarea`): Optional custom message. If empty, a default message is generated.
- `discord_webhook_url` (`text`): Optional webhook URL override.

## Environment variables
- `DISCORD_WEBHOOK_URL`: Discord webhook URL.

## Deploy
Add the below configuration to the OpenRelik `docker-compose.yml` file.

```yaml
openrelik-worker-notify:
    container_name: openrelik-worker-notify
    image: ghcr.io/julianghill/openrelik-worker-notify:latest
    restart: always
    environment:
      - REDIS_URL=redis://openrelik-redis:6379
      - OPENRELIK_PYDEBUG=0
      - DISCORD_WEBHOOK_URL=${DISCORD_WEBHOOK_URL}
    volumes:
      - ./data:/usr/share/openrelik/data
    command: "celery --app=src.app worker --task-events --concurrency=4 --loglevel=INFO -Q openrelik-worker-notify"
```

## Monitoring and alerting
- Success/failure is logged with workflow id, input count, and webhook host.
- On failure, the task raises a detailed RuntimeError

## Test
```bash
uv sync --group test
uv run pytest -s --cov=.
```
