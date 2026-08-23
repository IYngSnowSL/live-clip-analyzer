"""启动脚本：python run.py"""
import uvicorn

from app.config import load_config


def main():
    cfg = load_config()
    host = cfg.server.host
    port = int(cfg.server.port)
    uvicorn.run("app.main:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    main()
