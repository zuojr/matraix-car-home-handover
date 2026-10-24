"""Local HTTP service entrypoint with authenticated graceful Windows shutdown."""

import argparse
import os
import secrets

from fastapi import Header, HTTPException
import uvicorn


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--service", choices=("simulator", "assistant"), required=True)
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    if args.service == "simulator":
        from .simulator import factory
    else:
        from .chat import factory
    app = factory()
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=args.port, log_level="warning")
    )

    @app.post("/internal/shutdown")
    def shutdown(x_journey_control: str = Header(default="")):
        if not secrets.compare_digest(
            x_journey_control, os.environ["JOURNEY_CONTROL_TOKEN"]
        ):
            raise HTTPException(403, "Private shutdown")
        server.should_exit = True
        return {"shutdown_requested": True}

    server.run()


if __name__ == "__main__":
    main()
