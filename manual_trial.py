import asyncio
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


def _restart_inside_venv() -> None:
    venv_python = BASE_DIR / ".venv" / "Scripts" / "python.exe"
    current_python = Path(sys.executable).resolve()
    if os.environ.get("HOTWHEELS_SKIP_VENV_RESTART") == "1":
        return
    if venv_python.exists() and current_python != venv_python.resolve():
        os.environ["HOTWHEELS_SKIP_VENV_RESTART"] = "1"
        os.execv(str(venv_python), [str(venv_python), *sys.argv])


_restart_inside_venv()

from main import check_all_locations


if __name__ == "__main__":
    asyncio.run(check_all_locations(force_stock_digest=True, ignore_active_hours=True))
