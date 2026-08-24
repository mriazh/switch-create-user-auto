# Switch Bulk User Creation Automation

[![Python Version](https://img.shields.io/badge/python-3.8%2B-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-Aruba%20%7C%20HPE%20ProCurve-orange.svg)]()

Production-ready network automation tool to bulk-create user accounts across Aruba and HPE ProCurve enterprise switches via SSH.

Supports two operating modes:

- **RBAC Mode (Default, Safe, Multi-User):** Adds a new user account without overwriting existing switch accounts. Roles: `Level-15`, `Level-9`, `Level-1`, `Level-0`.
- **Classic Mode:** Replaces/overwrites the existing single-slot manager or operator account. Roles: `manager`, `operator`.

---

## 📌 Overview

Managing user credentials across dozens or hundreds of edge, distribution, and core switches manually via CLI is slow, repetitive, and prone to human error.

This automation tool reads a central switch inventory (`switch.txt`), prompts for user credentials securely, connects concurrently to target devices using Netmiko's `hp_procurve` driver, navigates interactive password dialogs, and persists changes to startup configuration (`write memory`).

---

## ✨ Key Features

- **Interactive Secure Credentials:** New username and password are requested at runtime. Passwords use masked input (`getpass`) and require double confirmation before proceeding.
- **Role Selection:** Choose `operator` (read-only) or `manager` (full control) via `--role` CLI flag or interactive prompt. Defaults to `operator`. The role is written into the audit log and used in the switch command sequence (`password <role> user-name <user>`).
- **Interactive CLI Dialogue Handling:** Employs Netmiko's `send_command_timing` with calibrated delays to handle multi-step interactive prompts (`New password for operator:` and `Re-enter:`).
- **Multithreaded Concurrent Execution:** Supports configurable thread workers (`--workers N`) via Python's `concurrent.futures.ThreadPoolExecutor`. 100+ switches can be provisioned in 2–3 minutes.
- **Fail-Safe & Fault Tolerant:** Continues through connection failures, timeouts, and auth errors without terminating the batch run.
- **Automatic Failed Inventory Export:** Any switches that fail during execution are automatically written to `failed_switches.txt` in the exact format required for immediate re-runs.
- **Built-in Retry Loop:** Prompts at the end of execution to immediately re-attempt only the failed switches.
- **Zero Plaintext Password Leakage:** All passwords (both switch login passwords and new account passwords) are strictly masked as `******` across console outputs and log files.
- **Sanitized Inventory Parsing:** Automatically cleans UTF-8 non-breaking spaces (`\xa0` / `\xc2\xa0`) and strips whitespace around delimiters to prevent credential corruption.

---

## 🏗️ Architecture & Workflow

```text
┌────────────────┐      ┌─────────────────────────┐      ┌─────────────────────────┐
│   switch.txt   │ ───▶ │     create_user.py      │ ───▶ │   ThreadPoolExecutor    │
│  (Inventory)   │      │ (Input & Normalization) │      │      (N Workers)        │
└────────────────┘      └─────────────────────────┘      └────────────┬────────────┘
                                                                      │
                         ┌────────────────────────────────────────────┴─────────────────────────┐
                         ▼                                                                      ▼
             ┌─────────────────────────┐                                            ┌─────────────────────────┐
             │   Worker Thread #1      │                                            │    Worker Thread #N     │
             │  SSH (hp_procurve:22)   │                                            │   SSH (hp_procurve:22)  │
             │   - configure terminal  │                                            │   - configure terminal  │
             │   - password operator   │                                            │   - password operator   │
             │   - [New password:]     │                                            │   - [New password:]     │
             │   - [Re-enter:]         │                                            │   - [Re-enter:]         │
             │   - write memory        │                                            │   - write memory        │
             │   - exit                │                                            │   - exit                │
             └───────────┬─────────────┘                                            └────────────┬────────────┘
                         │                                                                       │
                         └────────────────────────────┬──────────────────────────────────────────┘
                                                      ▼
                                       ┌──────────────────────────────┐
                                       │   Summary & Audit Logger     │
                                       ├──────────────────────────────┤
                                       │ • Clean Console Output       │
                                       │ • logs/log_create_user_*.txt │
                                       │ • failed_switches.txt        │
                                       └──────────────────────────────┘
```

---

## 📋 Prerequisites & Installation

- **Python 3.8+**
- Target switches reachable over TCP port 22 (SSH)

Install the required library:
```bash
pip install -r requirements.txt
```

---

## 📂 Inventory Format (`switch.txt`)

Place `switch.txt` in the same directory as the script. Each line corresponds to one network device separated by pipe (`|`):

```text
SWITCH_NAME | IP_ADDRESS | LOGIN_USERNAME | LOGIN_PASSWORD
```

### Example:
```text
SW-CORE-01   | 10.10.10.1  | admin | Pass123!
SW-DISTRI-01 | 10.10.10.10 | admin | Pass123!
SW-ACCESS-01 | 10.10.10.20 | admin | Pass123!
```

> ⚠️ **Security Notice:** `switch.txt` and `failed_switches.txt` contain device access credentials. Both files are strictly listed in `.gitignore` to prevent accidental commits to public or private version control.

---

## 🚀 Usage Guide

### 1. Dry-Run Verification (Recommended First Step)
Tests connectivity and command syntax against the **first switch only** before launching against the entire fleet:
```bash
python create_user.py --dry-run
```

### 2. High-Performance Parallel Run
Executes user creation across all switches concurrently:
```bash
python create_user.py --workers 5
```

> 💡 **Worker Count Guidelines:**
> - **Recommended: 5 to 10 workers.** Provides optimal throughput without saturating network gateways, VPN links, or TACACS+/RADIUS authentication servers.
> - **Caution against 20+ workers:** Older switch models (e.g. HP ProCurve 2520, 2610, 2620) have limited embedded CPU power. Flooding them with simultaneous SSH cryptographic handshakes can trigger `Authentication timeout` or TCP drops.

### 3. Standard Sequential Run
Connects to switches one-by-one:
```bash
python create_user.py
```

### 4. Role Selection (`--role`) & Operation Mode (`--mode`)

Choose the operation mode and user role. Two modes are supported:

- **RBAC mode** (default, safe, multi-user): Adds a new user without overwriting existing accounts.
  Roles: `Level-15`, `Level-9`, `Level-1`, `Level-0`.
- **Classic mode**: Replaces/overwrites the existing single-slot manager or operator account.
  Roles: `manager`, `operator`.

If `--mode`/`--role` are omitted, the script prompts interactively. If `--role` is given without `--mode`, the mode is inferred from the role (Level-* roles → RBAC, manager/operator → Classic). Invalid combinations (e.g. `--mode rbac --role manager`) cause an error and exit.

```bash
# Interactive prompts for username, mode, role, and password
python create_user.py

# Explicit RBAC mode with Level-9 role
python create_user.py --mode rbac --role Level-9 --workers 5

# Explicit Classic mode replacing the manager slot
python create_user.py --mode classic --role manager --workers 5

# Role-only inference: Level-15 implies RBAC mode
python create_user.py --role Level-15 --workers 5

# Role-only inference: manager implies Classic mode
python create_user.py --role manager --workers 5
```

The chosen mode and role are recorded in the audit log (`logs/log_create_user_*.txt`).

### 5. Custom Inventory File / Re-running Failures
Run against an alternative file, such as the auto-generated failure list:
```bash
python create_user.py --file failed_switches.txt --workers 5
```

---

## 📊 Outputs & Observability

### 1. Compact Terminal Summary
During execution, each switch reports in real time:
```text
[1/50] SW-CORE-01 (10.10.10.1)... [OK]
[2/50] SW-DISTRI-01 (10.10.10.10)... [OK]
[3/50] SW-ACCESS-01 (10.10.10.20)... [FAIL] Connection timeout: TCP connection to device failed.
...
============================================================
SUMMARY
============================================================
Success: 48 | Failed: 2
```

### 2. Audit Log (`logs/`)
Detailed timestamped logs are saved automatically in `logs/log_create_user_YYYYMMDD_HHMMSS.txt`:
- Connection attempts and timestamps
- Exact commands transmitted and raw switch echo
- Detailed stack traces for failures
- Passwords automatically replaced with `******`

### 3. Auto-Generated `failed_switches.txt`
Created whenever one or more switches fail. Formatted identically to `switch.txt` for single-step re-execution.

---

## 🔍 Troubleshooting

| Error | Root Cause | Solution |
|---|---|---|
| `Pattern not detected: '[>#]'` | Device is likely an **Aruba Mobility Controller** (e.g., Aruba 7200), not an AOS-Switch/ProCurve switch. Controllers use a different CLI syntax (`mgmt-user`). | Exclude controllers from switch inventory or provision them using controller-specific CLI. |
| `Connection timeout: TCP connection to device failed` | Device is offline, host IP is unreachable, or an intermediate firewall/ACL blocks port 22. | Check physical switch power, VLAN routing, and firewall policies. |
| `Authentication timeout` | Switch CPU saturated by too many concurrent SSH sessions (especially on legacy ProCurve 2520/2610 hardware). | Lower worker concurrency to `--workers 5` or `--workers 1`. |
| `Authentication failed` | Incorrect login credentials in inventory or account locked due to excessive failed attempts. | Verify switch password in inventory; check if external AAA (RADIUS/TACACS+) is restricting logins. |

---

## 📄 License

Internal Network Operations Automation Tool. Distributed under the MIT License.
