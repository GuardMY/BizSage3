FROM nginx:1.29.4-alpine3.23

COPY nginx.conf /etc/nginx/nginx.conf

RUN nginx -t

EXPOSE 80 4319

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD ["wget", "-q", "-O", "/dev/null", "http://127.0.0.1/nginx-health"]
