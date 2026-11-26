"""Runner script that executes each backend test file in an isolated process."""

import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYTEST_EXE = ROOT / "backend" / ".venv" / "Scripts" / "pytest.exe"
TESTS_DIR = ROOT / "backend" / "tests"

def main():
    test_files = sorted([f.name for f in TESTS_DIR.glob("test_*.py")])
    print(f"Discovered {len(test_files)} test files in {TESTS_DIR}")

    total_passed = 0
    total_skipped = 0
    total_failed = 0
    total_errors = 0
    results = []

    start_all = time.time()

    for idx, filename in enumerate(test_files, start=1):
        test_path = TESTS_DIR / filename
        t0 = time.time()
        proc = subprocess.run(
            [str(PYTEST_EXE), str(test_path), "-q"],
            capture_output=True,
            text=True,
            cwd=str(ROOT / "backend"),
        )
        duration = round(time.time() - t0, 3)
        output = proc.stdout + proc.stderr

        # Parse summary line: e.g. "10 passed in 0.77s", "4 passed, 1 skipped in 1.2s", "1 failed"
        passed = 0
        skipped = 0
        failed = 0

        for line in reversed(output.splitlines()):
            line_str = line.strip(" =")
            if "passed" in line_str or "skipped" in line_str or "failed" in line_str or "error" in line_str:
                parts = [p.strip() for p in line_str.split(",")]
                for p in parts:
                    if "passed" in p:
                        try:
                            passed = int(p.split()[0])
                        except ValueError:
                            pass
                    elif "skipped" in p:
                        try:
                            skipped = int(p.split()[0])
                        except ValueError:
                            pass
                    elif "failed" in p:
                        try:
                            failed = int(p.split()[0])
                        except ValueError:
                            pass
                break

        status = "PASSED" if proc.returncode == 0 else "FAILED"
        if status == "PASSED":
            total_passed += passed
            total_skipped += skipped
        else:
            total_failed += (failed or 1)
            total_passed += passed
            total_skipped += skipped

        results.append({
            "file": filename,
            "status": status,
            "passed": passed,
            "skipped": skipped,
            "failed": failed,
            "duration_s": duration,
            "stdout": proc.stdout.strip(),
            "stderr": proc.stderr.strip(),
        })

        status_sym = "[OK]" if status == "PASSED" else "[FAIL]"
        print(f"[{idx:02d}/{len(test_files)}] {status_sym} {filename:<45} passed={passed:<3} skipped={skipped:<2} failed={failed:<2} ({duration}s)")

    elapsed = round(time.time() - start_all, 2)
    print("\n" + "=" * 80)
    print(f"BACKEND REGRESSION SUMMARY:")
    print(f"Total Files:   {len(test_files)}")
    print(f"Total Passed:  {total_passed}")
    print(f"Total Skipped: {total_skipped}")
    print(f"Total Failed:  {total_failed}")
    print(f"Elapsed Time:  {elapsed}s")
    print("=" * 80)

    # Save output to reports
    out_file = ROOT / "reports" / "phase3e_lite_regression_results.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump({
            "total_files": len(test_files),
            "total_passed": total_passed,
            "total_skipped": total_skipped,
            "total_failed": total_failed,
            "elapsed_seconds": elapsed,
            "files": results,
        }, f, indent=2)
    print(f"Results recorded in {out_file}")

    if total_failed > 0:
        sys.exit(1)

if __name__ == "__main__":
    main()
