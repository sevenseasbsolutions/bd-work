# Shared proxy rules for server.idsservices.us (http bootstrap and https).
client_max_body_size 20m;       # app caps sheet uploads at 15 MB
proxy_read_timeout   300s;      # long imports / cycle builds
proxy_send_timeout   300s;

# API: /api/foo -> http://127.0.0.1:8010/foo (trailing slash strips the prefix)
location /api/ {
    proxy_pass http://127.0.0.1:8010/;
    proxy_http_version 1.1;
    proxy_buffering off;        # streamed .xlsx exports
    proxy_set_header Host              $host;
    proxy_set_header X-Real-IP         $remote_addr;
    proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header Connection        "";
}

# Throttle password guessing: burst 5, then 1 every 6s per address.
location = /api/auth/login {
    limit_req zone=bd_work_login burst=5 nodelay;
    limit_req_status 429;
    proxy_pass http://127.0.0.1:8010/auth/login;
    proxy_http_version 1.1;
    proxy_set_header Host              $host;
    proxy_set_header X-Real-IP         $remote_addr;
    proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header Connection        "";
}

# Frontend
location / {
    proxy_pass http://127.0.0.1:8011;
    proxy_http_version 1.1;
    proxy_set_header Host              $host;
    proxy_set_header X-Real-IP         $remote_addr;
    proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header Connection        "";
}

access_log /var/log/nginx/bd-work.access.log;
error_log  /var/log/nginx/bd-work.error.log;
