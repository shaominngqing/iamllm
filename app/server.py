from __future__ import annotations

import os

import uvicorn


def main() -> None:
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8000")),
        workers=1,
        access_log=False,
    )


if __name__ == "__main__":
    main()
