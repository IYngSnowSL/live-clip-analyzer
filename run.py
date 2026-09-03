"""启动脚本：python run.py"""
import uvicorn

from app.config import check_bind_guard, load_config


def main():
    cfg = load_config()
    check_bind_guard(cfg)
    host = cfg.server.host
    port = int(cfg.server.port)
    uvicorn.run("app.main:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    main()
