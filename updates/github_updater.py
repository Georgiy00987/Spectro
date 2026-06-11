"""Compatibility wrapper around the GitHub updater tool used by the Updates UI."""
from tools.github_update import (
    load_toml,
    run_check,
    update_project,
    main,
)

__all__ = ["load_toml", "run_check", "update_project", "main"]

if __name__ == "__main__":
    main()
