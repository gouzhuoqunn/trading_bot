from __future__ import annotations

from config import CONFIG


def main() -> None:
    log_file = CONFIG.logging.log_file
    log_file.parent.mkdir(parents=True, exist_ok=True)
    log_file.write_text("", encoding="utf-8")
    print(f"Cleared log file at {log_file}")


if __name__ == "__main__":
    main()
