module.exports = {
  apps: [
    {
      name: "ai-assistant-api",
      script: "python",
      args: "-m uvicorn app.main:app --host 0.0.0.0 --port 8001",
      cwd: "./",
      interpreter: "none",
      instances: 1,
      autorestart: true,
      watch: false,
      max_memory_restart: "500M",
      env: {
        ENVIRONMENT: "production",
      },
    },
    {
      name: "ai-assistant-worker",
      script: "python",
      args: "-m app.workers.document_worker",
      cwd: "./",
      interpreter: "none",
      instances: 1,
      autorestart: true,
      watch: false,
      max_memory_restart: "300M",
      env: {
        ENVIRONMENT: "production",
      },
    },
  ],
};

