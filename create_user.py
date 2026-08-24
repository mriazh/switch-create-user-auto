#!/usr/bin/env python3
"""
Bulk SSH user creation for Aruba/HP ProCurve switches.
Reads switch inventory from switch.txt and creates an operator user on each switch.
"""

import argparse
import getpass
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from netmiko import ConnectHandler
from netmiko.exceptions import NetmikoTimeoutException, NetmikoAuthenticationException


@dataclass
class SwitchInfo:
    name: str
    ip: str
    username: str
    password: str


@dataclass
class SwitchResult:
    switch: SwitchInfo
    success: bool
    message: str
    output: str
    timestamp: datetime


def parse_switches(filepath: str) -> List[SwitchInfo]:
    """Read switch.txt and parse lines in format 'NAME | IP | USERNAME | PASSWORD'."""
    switches = []
    path = Path(filepath)
    if not path.exists():
        print(f"Error: File '{filepath}' not found.")
        sys.exit(1)

    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        for line_num, line in enumerate(f, 1):
            line = line.replace("\xa0", " ").strip()
            if not line:
                continue
            parts = [part.replace("\xa0", " ").strip() for part in line.split("|")]
            if len(parts) != 4:
                continue
            name, ip, username, password = parts
            switches.append(
                SwitchInfo(name=name, ip=ip, username=username, password=password)
            )
    return switches


def get_user_input(cli_role: Optional[str] = None) -> tuple[str, str, str]:
    """Prompt for username, then role, then password (with confirmation). Optionally accept role from CLI."""
    username = input("Enter username to create: ").strip()
    if not username:
        print("Username cannot be empty.")
        sys.exit(1)

    role = cli_role if cli_role else prompt_role()

    max_retries = 3
    for attempt in range(1, max_retries + 1):
        password1 = getpass.getpass("Enter password for new user: ")
        password2 = getpass.getpass("Re-enter password: ")

        if password1 == password2:
            if password1:
                break
            else:
                print("Password cannot be empty.")
        else:
            remaining = max_retries - attempt
            if remaining > 0:
                print(f"Passwords do not match. {remaining} attempt(s) remaining.")
            else:
                print("Maximum retries exceeded. Exiting.")
                sys.exit(1)
    else:
        sys.exit(1)

    return username, password1, role


def prompt_role() -> str:
    """Interactively prompt for user role. Defaults to operator."""
    for _ in range(3):
        print("Select user role:")
        print("  [1] operator (Read-only / View monitoring)")
        print("  [2] manager  (Full control / Read-Write / Config & Backup)")
        choice = input("Enter choice [1/2] (default: 1): ").strip().lower()
        if choice in ("1", "operator", ""):
            return "operator"
        if choice in ("2", "manager"):
            return "manager"
        print("Invalid choice. Please try again.")
    print("Invalid choice. Defaulting to operator.")
    return "operator"


def confirm_execution(username: str, count: int, role: str) -> bool:
    """Ask for confirmation before proceeding."""
    response = (
        input(
            f"You are about to create a {role} user '{username}' on {count} switches. Continue? (y/n): "
        )
        .strip()
        .lower()
    )
    return response in ("y", "yes")


def create_user_on_switch(
    switch: SwitchInfo, new_username: str, new_password: str, role: str = "operator"
) -> SwitchResult:
    """Create a user on a single switch via SSH."""
    device = {
        "device_type": "hp_procurve",
        "host": switch.ip,
        "username": switch.username,
        "password": switch.password,
        "port": 22,
        "timeout": 30,
        "conn_timeout": 30,
    }

    timestamp = datetime.now()
    full_output = []

    try:
        with ConnectHandler(**device) as conn:
            # Enter configuration mode
            output = conn.send_command_timing("configure terminal", delay_factor=2)
            full_output.append(f"[configure terminal] {output}")

            # Create user command
            output = conn.send_command_timing(
                f"password {role} user-name {new_username}", delay_factor=2
            )
            full_output.append(f"[password {role} user-name {new_username}] {output}")

            # Wait for password prompt and send password
            time.sleep(1)
            output = conn.send_command_timing(new_password, delay_factor=2)
            full_output.append("[New password:] ******")

            # Wait for re-enter prompt and send password again
            time.sleep(1)
            output = conn.send_command_timing(new_password, delay_factor=2)
            full_output.append("[Re-enter:] ******")

            # Save configuration
            output = conn.send_command_timing("write memory", delay_factor=2)
            full_output.append(f"[write memory] {output}")

            # Exit
            output = conn.send_command_timing("exit", delay_factor=2)
            full_output.append(f"[exit] {output}")

        return SwitchResult(
            switch=switch,
            success=True,
            message="User created successfully",
            output="\n".join(full_output),
            timestamp=timestamp,
        )

    except NetmikoTimeoutException as e:
        return SwitchResult(
            switch=switch,
            success=False,
            message=f"Connection timeout: {e}",
            output=str(e),
            timestamp=timestamp,
        )
    except NetmikoAuthenticationException as e:
        return SwitchResult(
            switch=switch,
            success=False,
            message=f"Authentication failed: {e}",
            output=str(e),
            timestamp=timestamp,
        )
    except Exception as e:
        return SwitchResult(
            switch=switch,
            success=False,
            message=f"Error: {e}",
            output=str(e),
            timestamp=timestamp,
        )


def run_batch(
    switches: List[SwitchInfo],
    new_username: str,
    new_password: str,
    role: str = "operator",
    max_workers: int = 1,
) -> List[SwitchResult]:
    """Run user creation on all switches sequentially or in parallel."""
    results = []

    if max_workers == 1:
        # Sequential execution with status line
        for i, switch in enumerate(switches, 1):
            print(
                f"[{i}/{len(switches)}] {switch.name} ({switch.ip})... ",
                end="",
                flush=True,
            )
            result = create_user_on_switch(switch, new_username, new_password, role)
            results.append(result)
            if result.success:
                print("[OK]")
            else:
                print(f"[FAIL] {result.message}")
    else:
        # Parallel execution
        print(f"Running with {max_workers} workers...")
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_switch = {
                executor.submit(
                    create_user_on_switch, switch, new_username, new_password, role
                ): switch
                for switch in switches
            }

            completed = 0
            for future in as_completed(future_to_switch):
                switch = future_to_switch[future]
                completed += 1
                try:
                    result = future.result()
                    results.append(result)
                    print(
                        f"[{completed}/{len(switches)}] {switch.name} ({switch.ip})... {'[OK]' if result.success else f'[FAIL] {result.message}'}"
                    )
                except Exception as e:
                    result = SwitchResult(
                        switch=switch,
                        success=False,
                        message=f"Execution error: {e}",
                        output=str(e),
                        timestamp=datetime.now(),
                    )
                    results.append(result)
                    print(
                        f"[{completed}/{len(switches)}] {switch.name} ({switch.ip})... [FAIL] {result.message}"
                    )

    return results


def print_summary(results: List[SwitchResult]) -> None:
    """Print compact summary of results."""
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)

    success_count = 0
    fail_count = 0

    for result in results:
        status = "[OK]" if result.success else "[FAIL]"
        print(f"{status} {result.switch.name} ({result.switch.ip})")
        if result.success:
            success_count += 1
        else:
            fail_count += 1

    print("-" * 60)
    print(f"Success: {success_count} | Failed: {fail_count}")

    if fail_count > 0:
        print("\nFailed switches:")
        for result in results:
            if not result.success:
                print(f"  {result.switch.name} ({result.switch.ip}): {result.message}")


def write_log(
    results: List[SwitchResult], username: str, role: str = "operator"
) -> None:
    """Write detailed log file with masked passwords."""
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = log_dir / f"log_create_user_{timestamp}.txt"

    with open(log_file, "w") as f:
        f.write("Bulk User Creation Log\n")
        f.write(f"Target username: {username}\n")
        f.write(f"Target role: {role}\n")
        f.write(f"Execution time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"Total switches: {len(results)}\n")
        f.write("=" * 80 + "\n\n")

        for result in results:
            f.write(f"Switch: {result.switch.name} ({result.switch.ip})\n")
            f.write(f"Login user: {result.switch.username}\n")
            f.write("Login password: ******\n")
            f.write(f"Timestamp: {result.timestamp.strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Success: {result.success}\n")
            f.write(f"Message: {result.message}\n")
            f.write(f"Output:\n{result.output}\n")
            f.write("-" * 80 + "\n\n")

    print(f"\nLog written to: {log_file}")


def write_failed_switches(results: List[SwitchResult]) -> None:
    """Write failed switches to failed_switches.txt for retry."""
    failed = [r for r in results if not r.success]
    if not failed:
        return

    with open("failed_switches.txt", "w") as f:
        for result in failed:
            f.write(
                f"{result.switch.name} | {result.switch.ip} | {result.switch.username} | {result.switch.password}\n"
            )

    print(f"Failed switches written to: failed_switches.txt ({len(failed)} entries)")


def prompt_retry(failed_switches: List[SwitchResult]) -> bool:
    """Ask if user wants to retry failed switches."""
    count = len(failed_switches)
    if count == 0:
        return False

    response = input(f"\n{count} switch(es) failed. Retry? (y/n): ").strip().lower()
    return response in ("y", "yes")


def main():
    parser = argparse.ArgumentParser(
        description="Bulk create operator user on Aruba/HP ProCurve switches"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Test on first switch only"
    )
    parser.add_argument(
        "--workers", type=int, default=1, help="Number of parallel workers (default: 1)"
    )
    parser.add_argument(
        "--file",
        type=str,
        default="switch.txt",
        help="Path to switch inventory file (default: switch.txt)",
    )
    parser.add_argument(
        "--role",
        choices=["operator", "manager"],
        default=None,
        help="User role: operator (read-only) or manager (full control). If omitted, prompts interactively.",
    )
    args = parser.parse_args()

    # Parse switches
    switches = parse_switches(args.file)
    if not switches:
        print("No valid switches found in inventory file.")
        sys.exit(1)

    print(f"Loaded {len(switches)} switches from {args.file}")

    # Get user input
    username, password, role = get_user_input(args.role)

    # Confirm
    if not confirm_execution(username, len(switches), role):
        print("Cancelled.")
        sys.exit(0)

    # Dry-run: slice to first switch
    if args.dry_run:
        print("\n[DRY-RUN] Testing on first switch only...")
        switches = switches[:1]

    # Run batch
    try:
        results = run_batch(
            switches, username, password, role, max_workers=args.workers
        )
    except KeyboardInterrupt:
        print("\n\nInterrupted by user.")
        # Still write log with partial results
        write_log([], username, role)
        sys.exit(1)

    # Print summary
    print_summary(results)

    # Write log
    write_log(results, username, role)

    # Write failed switches file
    write_failed_switches(results)

    # Offer retry
    failed = [r for r in results if not r.success]
    if failed and prompt_retry(failed):
        print("\nRetrying failed switches...")
        retry_switches = [r.switch for r in failed]
        retry_results = run_batch(
            retry_switches, username, password, role, max_workers=args.workers
        )
        print_summary(retry_results)
        write_log(retry_results, username, role)
        write_failed_switches(retry_results)


if __name__ == "__main__":
    main()
