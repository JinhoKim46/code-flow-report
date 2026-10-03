FROM python:3.12-slim AS base
WORKDIR /app
COPY backend/ .
COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf
CMD ["supervisord", "-c", "/etc/supervisor/conf.d/supervisord.conf"]

FROM base AS runtime
ENV MODE=prod
