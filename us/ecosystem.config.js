// ecosystem.config.js — PM2 process manager
// Install: npm install -g pm2
// Start:   pm2 start ecosystem.config.js
// Save:    pm2 save && pm2 startup

module.exports = {
  apps: [
    // ── Telegram Bot ───────────────────────────────────────────────────
    {
      name:        "ssd-bot",
      script:      "python",
      args:        "mainny.py",
      cwd:         "/home/ec2-user/us",
      interpreter: "none",
      autorestart: true,
      watch:       false,
      max_restarts: 10,
      restart_delay: 5000,
      env: {
        PYTHONUNBUFFERED: "1",
      },
      log_date_format: "YYYY-MM-DD HH:mm:ss",
      out_file:  "/home/ec2-user/logs/bot-out.log",
      error_file: "/home/ec2-user/logs/bot-err.log",
    },

    // ── FastAPI Backend ────────────────────────────────────────────────
    {
      name:        "ssd-api",
      script:      "uvicorn",
      args:        "api_server:app --host 127.0.0.1 --port 8000 --workers 2",
      cwd:         "/home/ec2-user/us",
      interpreter: "none",
      autorestart: true,
      watch:       false,
      max_restarts: 10,
      restart_delay: 3000,
      env: {
        PYTHONUNBUFFERED: "1",
      },
      log_date_format: "YYYY-MM-DD HH:mm:ss",
      out_file:   "/home/ec2-user/logs/api-out.log",
      error_file: "/home/ec2-user/logs/api-err.log",
    },

    // ── Next.js Frontend ───────────────────────────────────────────────
    {
      name:        "ssd-web",
      script:      "npm",
      args:        "start",
      cwd:         "/home/ec2-user/us/web",
      interpreter: "none",
      autorestart: true,
      watch:       false,
      max_restarts: 10,
      restart_delay: 3000,
      env: {
        NODE_ENV: "production",
        PORT:     "3000",
      },
      log_date_format: "YYYY-MM-DD HH:mm:ss",
      out_file:   "/home/ec2-user/logs/web-out.log",
      error_file: "/home/ec2-user/logs/web-err.log",
    },
  ],
};
