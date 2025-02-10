#!/usr/bin/env python3
"""
scan_mods_exhaustive_updated.py

This script scans a macOS system in two phases.

Phase 1 (“Manual Customizations”):
  • Processes /Applications to list custom apps (separating brew‐installed ones) without deep‐listing inside .app bundles.
  • Queries brew for explicit formulas (“brew leaves”) and brew casks.
  • For each user in /Users (skipping Shared/Guest), processes selected top‑level folders (for example,
    Desktop, Documents, Downloads, Applications, and any user‐defined folder like “.portahome”).
    For each folder it computes a summary: immediate item count, total recursive file count, and total disk usage (human‑readable).
  • The manual_customizations.txt file is a single file with sections per user plus system sections.

Phase 2 (“Gray Area”):
  • For each user, any top‑level folder not in the “included” list (or that is hidden) is scanned shallowly (one level only)
    and written into a gray_area file.
  • Additionally, top‑level directories in “/” (excluding /Applications, /Users, and known system areas) are shallowly listed.
  • These outputs are intended to be post‑processed (e.g. with AI prompts) for further filtering.

Certain known system directories (e.g. /System, /private, /etc, /cores, /Volumes, /Recovery) are entirely ignored.
Hidden names (starting with “.”) and common transactional paths (such as “Library/Caches”, “Library/News”, “Library/Finances”) are filtered out from the manual report.
"""

import os
import re
import datetime
import subprocess

# --- CONFIGURATION ---

# Output locations
OUTPUT_DIR = f"scan_output_{datetime.datetime.now().strftime('%Y%m%d-%H%M%S')}"
MANUAL_FILE = os.path.join(OUTPUT_DIR, "manual_customizations.txt")
GRAY_AREA_DIR = os.path.join(OUTPUT_DIR, "gray_area")
IGNORED_FILE = os.path.join(OUTPUT_DIR, "ignored.txt")

# Directories that we do not want to scan at all (for top-level gray area scanning)
IGNORED_DIRS = [
    "/System", "/private", "/etc", "/cores", "/Volumes", "/Recovery", "/Library",
    "/net", "/home", "/opt", "/tmp", "/var", "/usr", "/bin", "/sbin", "/lib", "/libexec", "/dev", "/mnt"
    ]

# Areas handled separately
SPECIAL_AREAS = ["/Applications", "/Users"]

# For user manual customizations, only these top-level folders will be summarized.
INCLUDE_USER_FOLDERS = ["Desktop", "Documents", "Downloads", "Applications", ".portahome"]

# For user manual customizations, ignore these top-level folders (entirely).
IGNORE_USER_FOLDERS = ["Library"]

# Patterns to ignore (e.g. names starting with a dot)
IGNORED_NAME_PATTERNS = [re.compile(r'^\.')]

# Substrings (case-insensitive) in paths that, if found, cause a file/folder to be omitted from the manual report.
IGNORED_PATH_SUBSTRINGS = ["library/caches", "library/news", "library/finances"]

# --- UTILITY FUNCTIONS ---

def ensure_output_dirs():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(GRAY_AREA_DIR, exist_ok=True)

def human_readable_size(size, decimal_places=1):
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size < 1024.0:
            return f"{size:.{decimal_places}f} {unit}"
        size /= 1024.0
    return f"{size:.{decimal_places}f} PB"

def get_directory_summary(path):
    """Recursively compute the total number of files and total size (in bytes) for a directory."""
    total_size = 0
    file_count = 0
    for root, dirs, files in os.walk(path, topdown=True):
        # Skip hidden subdirectories
        dirs[:] = [d for d in dirs if not any(p.match(d) for p in IGNORED_NAME_PATTERNS)]
        for f in files:
            if any(p.match(f) for p in IGNORED_NAME_PATTERNS):
                continue
            try:
                full_path = os.path.join(root, f)
                total_size += os.path.getsize(full_path)
                file_count += 1
            except Exception:
                continue
    return file_count, total_size

def run_brew_command(args):
    try:
        result = subprocess.check_output(["brew"] + args, stderr=subprocess.DEVNULL, text=True)
        return result.strip().splitlines()
    except Exception:
        return []

def get_brew_leaves():
    return run_brew_command(["leaves"])

def get_brew_casks():
    return run_brew_command(["list", "--cask"])

def should_ignore_name(name):
    for pattern in IGNORED_NAME_PATTERNS:
        if pattern.match(name):
            return True
    return False

def should_ignore_path(path):
    lower_path = path.lower()
    for substr in IGNORED_PATH_SUBSTRINGS:
        if substr in lower_path:
            return True
    return False

# --- PROCESSING FUNCTIONS ---

def process_system_applications(brew_casks):
    """
    Process /Applications:
      • List all top-level .app bundles.
      • Separate apps whose base name (without ".app") appears in the brew cask list (case-insensitive).
    """
    apps_path = "/Applications"
    custom_apps = []
    brew_apps = []
    if os.path.isdir(apps_path):
        for item in os.listdir(apps_path):
            if item.endswith(".app"):
                base = item[:-4].lower()
                if any(base == cask.lower() for cask in brew_casks):
                    brew_apps.append(item)
                else:
                    custom_apps.append(item)
    custom_apps.sort()
    brew_apps.sort()
    return custom_apps, brew_apps

def process_brew_formulas():
    formulas = get_brew_leaves()
    formulas.sort()
    return formulas

def process_user_manual_customizations():
    """
    For each user in /Users (skipping Shared/Guest),
    examine only the selected top-level folders (INCLUDE_USER_FOLDERS).
    For each such folder, compute a summary (immediate item count and recursive file count and total size).
    Returns a mapping: username -> list of summary strings.
    """
    results = {}
    users_dir = "/Users"
    try:
        for user in os.listdir(users_dir):
            user_path = os.path.join(users_dir, user)
            if not os.path.isdir(user_path) or user.lower() in ["shared", "guest"]:
                continue
            summaries = []
            for folder in INCLUDE_USER_FOLDERS:
                target = os.path.join(user_path, folder)
                if os.path.isdir(target):
                    try:
                        immediate_items = os.listdir(target)
                        immediate_count = len([i for i in immediate_items if not should_ignore_name(i)])
                    except Exception:
                        immediate_count = 0
                    file_count, total_size = get_directory_summary(target)
                    hr_size = human_readable_size(total_size)
                    summaries.append(f"{folder}: {immediate_count} items (immediate), {file_count} files total, {hr_size}")
            results[user] = summaries
    except Exception:
        pass
    return results

def process_user_gray_area():
    """
    For each user in /Users (skipping Shared/Guest), list any top-level folder (or file)
    that is either hidden or not in INCLUDE_USER_FOLDERS (and not in IGNORE_USER_FOLDERS).
    A shallow listing (one level only) is recorded.
    Returns mapping: username -> (folder name -> list of immediate items).
    """
    results = {}
    users_dir = "/Users"
    try:
        for user in os.listdir(users_dir):
            user_path = os.path.join(users_dir, user)
            if not os.path.isdir(user_path) or user.lower() in ["shared", "guest"]:
                continue
            gray = {}
            for item in os.listdir(user_path):
                if item in INCLUDE_USER_FOLDERS or item in IGNORE_USER_FOLDERS:
                    continue
                target = os.path.join(user_path, item)
                if os.path.isdir(target):
                    try:
                        contents = os.listdir(target)
                        # Do a shallow listing and filter out hidden names.
                        contents = [c for c in contents if not should_ignore_name(c)]
                    except Exception:
                        contents = []
                    gray[item] = contents
            if gray:
                results[user] = gray
    except Exception:
        pass
    return results

def process_top_level_gray_area():
    """
    For every top-level directory in "/" that is not in SPECIAL_AREAS or IGNORED_DIRS,
    perform a shallow listing (immediate contents, filtering out hidden items).
    Returns mapping: directory -> list of items.
    """
    results = {}
    try:
        for entry in os.listdir("/"):
            full_path = os.path.join("/", entry)
            if os.path.isdir(full_path):
                if full_path in SPECIAL_AREAS or any(full_path.startswith(ig) for ig in IGNORED_DIRS):
                    continue
                try:
                    items = os.listdir(full_path)
                    items = [i for i in items if not should_ignore_name(i)]
                except Exception:
                    items = []
                results[full_path] = items
    except Exception:
        pass
    return results

# --- OUTPUT FUNCTIONS ---

def write_manual_customizations(system_custom_apps, system_brew_apps, brew_formulas, user_manual):
    with open(MANUAL_FILE, "w") as f:
        f.write("=== Manual Customizations Report ===\n\n")
        
        # System Applications Section
        f.write("== /Applications ==\n")
        f.write("Custom Applications (non-brew):\n")
        if system_custom_apps:
            for app in system_custom_apps:
                f.write(f" - {app}\n")
        else:
            f.write(" (None found)\n")
        f.write("\nBrew Cask Applications:\n")
        if system_brew_apps:
            for app in system_brew_apps:
                f.write(f" - {app}\n")
        else:
            f.write(" (None found)\n")
        
        # Brew Formulas Section
        f.write("\n== Brew Formulas (explicit installs) ==\n")
        if brew_formulas:
            for formula in brew_formulas:
                f.write(f" - {formula}\n")
        else:
            f.write(" (None found)\n")
        
        # User Customizations Section
        f.write("\n== User Customizations ==\n")
        for user, summaries in user_manual.items():
            f.write(f"\n-- User: {user} --\n")
            if summaries:
                for line in summaries:
                    f.write(f" - {line}\n")
            else:
                f.write(" (No custom folders found)\n")

def write_gray_area(user_gray, top_level_gray):
    # Per-user gray area files
    for user, folders in user_gray.items():
        filename = os.path.join(GRAY_AREA_DIR, f"user_{user}_gray_area.txt")
        with open(filename, "w") as f:
            f.write(f"Gray Area for user: {user}\n")
            for folder, contents in folders.items():
                f.write(f"\n-- {folder} (top-level listing) --\n")
                for item in contents:
                    f.write(f" - {item}\n")
    # Top-level gray area files
    for dir_path, items in top_level_gray.items():
        safe_name = dir_path.strip("/").replace("/", "_") or "root"
        filename = os.path.join(GRAY_AREA_DIR, f"{safe_name}_gray_area.txt")
        with open(filename, "w") as f:
            f.write(f"Gray Area for {dir_path} (top-level listing):\n")
            for item in items:
                f.write(f" - {item}\n")

def write_ignored():
    with open(IGNORED_FILE, "w") as f:
        f.write("Ignored Directories (not scanned):\n")
        for d in IGNORED_DIRS:
            f.write(f" - {d}\n")

# --- MAIN DRIVER ---

def main():
    ensure_output_dirs()
    
    # Get brew data.
    brew_casks = get_brew_casks()
    brew_formulas = process_brew_formulas()
    
    # Process /Applications.
    system_custom_apps, system_brew_apps = process_system_applications(brew_casks)
    
    # Process user manual customizations.
    user_manual = process_user_manual_customizations()
    
    # Process gray area for users.
    user_gray = process_user_gray_area()
    
    # Process top-level gray area.
    top_level_gray = process_top_level_gray_area()
    
    # Write all outputs.
    write_manual_customizations(system_custom_apps, system_brew_apps, brew_formulas, user_manual)
    write_gray_area(user_gray, top_level_gray)
    write_ignored()
    
    print("Scan complete. Output available in", OUTPUT_DIR)

if __name__ == "__main__":
    main()