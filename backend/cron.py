import subprocess
import sys
import os


def run_script(script_name):
    result = subprocess.run(
        [sys.executable, script_name],
        cwd=os.path.dirname(__file__),
        capture_output=True,
        text=True,
    )
    print(result.stdout)
    if result.stderr:
        print(f"STDERR: {result.stderr}")
    return result.returncode


if __name__ == "__main__":
    print("=== Starting ThreadRadar Cron ===")

    print("\n--- Running main.py ---")
    code = run_script("main.py")
    if code != 0:
        print(f"main.py failed with code {code}")
        sys.exit(code)

    print("\n--- Running price_updater.py ---")
    run_script("price_updater.py")

    print("\n=== Cron Complete ===")
