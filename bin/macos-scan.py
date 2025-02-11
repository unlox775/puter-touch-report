#!/usr/bin/env python3
"""
scan_mods_global.py

This script performs a two‑phase scan of the macOS filesystem.
Data‐gathering functions update global objects (for system applications,
brew data, per‑user manual customizations, user gray areas, and top‑level gray areas).
Each processed path is registered in the global registry “scanned_paths.”
Later, a full crawler (crawl_remaining_paths) walks the remaining filesystem,
skipping any paths already in scanned_paths, and adds shallow listings to the global
remaining_gray object. Finally, write_reports() is called (with no arguments) to write out
all the accumulated data.
"""

import os
import re
import sys
import datetime
import subprocess
import textwrap

# --- GLOBAL CONFIGURATION & GLOBAL DATA OBJECTS ---

# Global registry for all processed (scanned/handled) paths
scanned_paths = set()

# Global objects for accumulated data
global_system_custom_apps = []      # list of custom (non-brew) apps in /Applications
global_system_brew_apps = []        # list of brew-installed apps in /Applications
global_brew_formulas = []           # list of brew formulas ("brew leaves")
global_user_manual = {}             # dict: username -> list of summary strings for included folders
global_user_gray = {}               # dict: username -> dict (folder -> shallow listing)
global_top_level_gray = {}          # dict: directory -> shallow listing (from gather_top_level_gray_area)
global_remaining_gray = {}          # dict: directory -> shallow listing (from crawl_remaining_paths)
global_ignored_paths = set()        # set of paths that were ignored (not scanned)

# Output directories and file paths
OUTPUT_DIR = f"scan_output_{datetime.datetime.now().strftime('%Y%m%d-%H%M%S')}"
MANUAL_FILE = os.path.join(OUTPUT_DIR, "manual_customizations.txt")
GRAY_AREA_DIR = os.path.join(OUTPUT_DIR, "gray_area")
IGNORED_FILE = os.path.join(OUTPUT_DIR, "ignored.txt")

# Directories to ignore entirely (for top-level gray area scanning)
INCLUDE_ROOT_DIRS = ["/Users", "/Applications", "/Volumes"]
IGNORED_ROOT_DIRS = [
    "/System", "/private", "/etc", "/cores", "/Volumes", "/Recovery",
    "/home", "/usr", "/.resolve", "/bin", "/sbin", "/var", "/Library",
    "/.vol", "/opt", "/dev", "/Volumes",
    "/.nofollow", "/tmp"
    ]

# Default macOS Applications that we consider “built-in” and ignore.
DEFAULT_APPS_WHITELIST = [
    "Safari", "Mail", "Calendar", "FaceTime",
    "Messages", "Notes", "App Store", "System Preferences",
    "Finder", "Contacts", "Reminders", "Maps",
    "Photos", "Preview", "iTunes", "Music", "TV",
    "Numbers", "Pages", "Keynote", "iMovie", "GarageBand", 
    "Books", "Podcasts", "News", "Stocks", "Voice Memos",
    "Home", "Activity Monitor", "Terminal", "Console",
    "Disk Utility", "Script Editor", "TextEdit", "Calculator",
    "Photo Booth", "Automator", "Dictionary",
    "Font Book", "Stickies", "Grapher", "Digital Color Meter",
    "QuickTime Player", "DVD Player", "Chess", "Migration Assistant",
    "Feedback Assistant", "ColorSync Utility", "Audio MIDI Setup",
    "Bluetooth File Exchange", "Boot Camp Assistant"
]

# For user manual customizations, only these top-level folders are “included”
INCLUDE_USER_FOLDERS = ["Desktop", "Downloads"]
SCAN_USER_GRAY_AREA_FOLDERS = ["Library/Application Support", "Documents", "Music", "Movies", "Pictures"]

# For user manual customizations, these top-level folders will be skipped entirely
IGNORE_USER_FOLDERS = [
    ".Trash",".ansible",".asdf",".aws",".berkshelf",".bundle",".cache",".cups",
    ".docker",".dropbox",".npm",".vscode",".yarn",".zsh_sessions","Native Instruments",
    "Accessibility","Accounts","AppleMediaServices","AddressBook","Adobe","Alfred",
    "App Store","Asana","AvastHUB","Blender","BraveSoftware","CallHistoryDB",
    "CallHistoryTransactions","ChatGPT","Chromium","CloudDocs","Code","contactsd",
    "ControlCenter","CrashReporter","DifferentialPrivacy","DiskImages","Dock",
    "Docker Desktop","Dropbox","FaceTime","FileProvider","Firefox","GitHub Desktop",
    "Google","homeenergyd","icdd","iCloud","identityservicesd","iMazing","iMovie",
    "io.sentry","iTerm2","JetBrains","Knowledge","Microsoft","MobileSync","Mozilla"
    ,"Native Instruments","networkserviceproxy","org.videolan.vlc","Postman",
    "privatecloudcomputed","Slack","Spotlight","stickersd","Sublime Text",
    "summary-events","SyncServices","tipsd","virtualenv","ZAP","zoom.us","Assistant",
    "Assistants","Audio","Autosave Information","Biome","Caches","Calendars",
    "CallServices","CloudStorage","ColorPickers","Colors","Compositions","Contacts",
    "ContainerManager","Containers","Cookies","CoreFollowUp","Daemon Containers",
    "DataAccess","DataDeliveryServices","DES","DoNotDisturb","Dropbox",
    "DuetExpertCenter","Favorites","Finance","FontCollections","Fonts","FrontBoard",
    "GameKit","Google","Group Containers","homeenergyd","HomeKit","HTTPStorages",
    "IdentityServices","Input Methods","IntelligencePlatform","Intents",
    "Internet Plug-Ins","iTunes","Keyboard","Keyboard Layouts","KeyboardServices",
    "Keychains","LanguageModeling","LaunchAgents","LockdownMode","Logs","Mail",
    "Messages","Metadata","Mobile Documents","News","NGL","Passes",
    "PersonalizationPortrait","Photos","PPM","PreferencePanes","Preferences",
    "Printers","PrivateCloudCompute","Python","QuickLook","Reminders","ResponseKit",
    "Safari","SafariSafeBrowsing","SafariSandboxBroker","Saved Application State",
    "Screen Savers","ScreenRecordings","Scripts","Services","Sharing","Shortcuts",
    "Sounds","Spelling","Spotlight","Staging","StatusKit","Stickers","studentd",
    "Suggestions","SyncedPreferences","Translation","Trial","UnifiedAssetFramework",
    "Weather","WebKit"
    ]

# Patterns to ignore (e.g. names starting with a dot)
IGNORED_NAME_PATTERNS = [re.compile(r'^\.')]

# Substrings (case-insensitive) in a path that cause the file/folder to be omitted from manual report
IGNORED_PATH_SUBSTRINGS = ["library/caches", "library/news", "library/finances"]

# Limit for immediate listing (if too many items, you might later add logic to summarize)
MAX_ITEMS = 100

# --- NEW FUNCTIONS TO TRACK & CRAWL PROCESSED PATHS ---

def register_scanned_path(path):
    """
    Register a path (file or directory) as having been processed.
    The normalized version of the given path is added to the global scanned_paths set.
    """
    global scanned_paths
    print(f"Registering scanned path: {path}")
    scanned_paths.add(os.path.normpath(path))

def crawl_remaining_paths(base="/"):
    """
    Crawl the entire filesystem starting at the given base directory,
    skipping any path that has already been registered via register_scanned_path.
    For each new directory encountered, record a shallow listing in global_remaining_gray.
    Debug output is printed on the same terminal line (overwriting it) to show progress.
    """
    global global_remaining_gray
    for root, dirs, files in os.walk(base, topdown=True):
        # Skip if it is a symlink
        if os.path.islink(root):
            continue

        print(f"=========> Scanning directory: {root}\n")
        # prinf files
        print(f"Files: {files}\n")
        print(f"Dirs: {dirs}\n")
        normalized_root = os.path.normpath(root)
        if normalized_root in scanned_paths:
            print(f"   X==X Skipping already scanned path: {normalized_root}")
            dirs[:] = []  # do not descend further
            continue
        sys.stdout.write(f"Scanning directory: {normalized_root} \n")
        sys.stdout.flush()
        # Process files (debug output only)
        for file in files:
            full_path = os.path.join(root, file)
            normalized_file = os.path.normpath(full_path)
            if normalized_file in scanned_paths:
                print(f"   X==X Skipping already scanned path: {normalized_file}")
                continue
            sys.stdout.write(f"Scanning file: {normalized_file} \n")
            sys.stdout.flush()
        # For each new directory, update global_remaining_gray with a shallow listing.
        new_dirs = []
        for d in dirs:
            d_full = os.path.join(root, d)
            normalized_d = os.path.normpath(d_full)
            if normalized_d in scanned_paths:
                print(f"   X==X Skipping already scanned path: {normalized_d}")
            else:
                # test: if there is a seen path that is a child of this path, then drill deeper
                if scanned_path_exists_as_subdirectory(normalized_d):
                    sys.stdout.write(f"Drilling deeper into: {normalized_d} \n")
                    new_dirs.append(d)
                    # try:
                    #     listing = os.listdir(normalized_d)
                    #     listing = [i for i in listing if not should_ignore_name(i)]
                    # except Exception:
                    #     listing = []
                    # global_remaining_gray[normalized_d] = listing
                else:
                    sys.stdout.write(f"Recording directory as gray area: {normalized_d} \n")
                    # if under a User directory, record the gray area for that user
                    if normalized_d.startswith("/Users/"):
                        user = normalized_d.split("/")[2]
                        record_user_gray(user, normalized_d)
                    else:
                        record_top_level_gray(normalized_d)
        dirs[:] = new_dirs
    sys.stdout.write("\nCrawl complete.\n")
    sys.stdout.flush()

def scanned_path_exists_as_subdirectory(path):
    """
    Check if the given path (file or directory) exists as a file or directory under any scanned path.
    """
    for scanned_path in scanned_paths:
        # print(f"Checking if {path} is under {scanned_path}")
        if scanned_path.startswith(path + os.sep):
            return True
    return False

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
    """
    Recursively compute the total number of files and total size (in bytes) for a directory.
    """
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
        full_args = ["brew"] + args
        # Check if running as sudo, if so, drop duso to run brew as a normal user
        if os.geteuid() == 0:
            print(f"Running as root, dropping to user ({os.getenv('SUDO_USER')}) to run brew")
            full_args = ["sudo", "-u", os.getenv("SUDO_USER"), "brew"] + args

        # Grab stdout and error, so we can debug if there is an error
        result = subprocess.run(full_args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False, text=True)
        parsed = result.stdout.strip().splitlines()
        # If we didn't get anything, complain
        if not parsed:
            print(f"Error: No output from command: {result}")
        # print(f"Command error: {result.stderr}")
        # print(f"Command result: {parsed}")
        return parsed
    except subprocess.CalledProcessError as e:
        print(f"CalledProcessError: {e.returncode}, {e.cmd}, {e.output}, {e.stderr}")
        return []
    except Exception as e:
        print(f"Error running brew command: {args} : {e}")
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

# --- GATHERING FUNCTIONS (Data Accumulation, update globals) ---

def gather_system_applications(brew_casks):
    """
    Process /Applications:
      • List all top-level .app bundles.
      • Separate those whose base name (without ".app") appears in the brew cask list (case-insensitive).
    Updates global_system_custom_apps and global_system_brew_apps.
    """
    apps_path = "/Applications"
    if os.path.isdir(apps_path):
        for item in os.listdir(apps_path):
            full_item = os.path.join(apps_path, item)
            if item.endswith(".app"):
                record_application(full_item, brew_casks)
    global_system_custom_apps.sort()
    global_system_brew_apps.sort()

def record_application(full_item, brew_casks):
    """
    Process a single application, updating the appropriate global list and registering the path.
    """
    global global_system_custom_apps, global_system_brew_apps
    register_scanned_path(full_item)
    base = os.path.basename(full_item)[:-4]
    base_lower = base.lower()
    if any(base_lower == cask.lower() for cask in brew_casks):
        global_system_brew_apps.append(os.path.basename(full_item))
    else:
        if base in DEFAULT_APPS_WHITELIST:
            record_ignore_path(full_item)
        else:    
            global_system_custom_apps.append(os.path.basename(full_item))

def gather_brew_formulas():
    """
    Retrieves brew formulas (explicit installs) and updates global_brew_formulas.
    """
    global global_brew_formulas
    formulas = get_brew_leaves()
    print(f"Formulas: {formulas}")
    formulas.sort()
    global_brew_formulas = formulas

def gather_user_manual_customizations():
    """
    For each user in /Users (skipping Shared/Guest), examines only the selected top-level folders
    (INCLUDE_USER_FOLDERS). For each folder that exists, calls record_user_manual_customization()
    to compute and record its summary.
    
    The effect is that global_user_manual is updated with one summary entry per folder per user,
    each following the exact format:
      "{folder}: {immediate_count} immediate items, {file_count} files total, {hr_size}"
    """
    global global_user_manual
    global_user_manual = {}  # reset or initialize the global state
    users_dir = "/Users"
    try:
        for user in os.listdir(users_dir):
            user_path = os.path.join(users_dir, user)
            if not os.path.isdir(user_path) or user.lower() in ["shared", "guest"]:
                continue
            for folder in INCLUDE_USER_FOLDERS:
                target = os.path.join(user_path, folder)
                if os.path.isdir(target):
                    record_user_manual_customization(user, folder, target)
    except Exception:
        pass

def record_user_manual_customization(user, folder, target):
    """
    For a given user and a given folder (with name folder) at path target:
      - Registers the target as scanned.
      - Computes:
          * immediate_count: number of immediate (non-hidden) items in target.
          * file_count and total_size (via get_directory_summary).
          * hr_size: total_size in human‑readable form.
      - Formats the summary string exactly as:
          "{folder}: {immediate_count} immediate items, {file_count} files total, {hr_size}"
      - Updates global_user_manual for the given user by appending this summary.
      
    This is the only function that updates global_user_manual for a manual customization entry.
    """
    register_scanned_path(target)
    try:
        immediate_items = os.listdir(target)
        immediate_count = len([i for i in immediate_items if not should_ignore_name(i)])
    except Exception:
        immediate_count = 0

    file_count, total_size = get_directory_summary(target)
    hr_size = human_readable_size(total_size)
    summary = f"{folder}: {immediate_count} immediate items, {file_count} files total, {hr_size}"

    global global_user_manual
    if user not in global_user_manual:
        global_user_manual[user] = []
    global_user_manual[user].append(summary)

def gather_user_gray_area():
    """
    For each user in /Users (skipping Shared/Guest), lists any top-level folder (or file)
    that is either hidden or not in INCLUDE_USER_FOLDERS (and not in IGNORE_USER_FOLDERS).
    For each such directory, performs a shallow listing (one level only) and updates global_user_gray.
    """
    results = {}
    users_dir = "/Users"
    try:
        for user in os.listdir(users_dir):
            user_path = os.path.join(users_dir, user)
            if not os.path.isdir(user_path) or user.lower() in ["shared", "guest"]:
                continue
            # Scan Items in the User's Application Support
            for gray_folder in SCAN_USER_GRAY_AREA_FOLDERS:
                scan_path = os.path.join(user_path, gray_folder)
                if os.path.isdir(scan_path):
                    for item in os.listdir(scan_path):
                        if item in IGNORE_USER_FOLDERS or item.startswith("com."):
                            record_ignore_path(os.path.join(scan_path, item))
                            continue
                        target = os.path.join(scan_path, item)
                        if os.path.isdir(target):
                            sys.stdout.write(f"A => ")
                            record_user_gray(user, target)

            # Scan items in the User's Home Dir
            for item in os.listdir(user_path):
                if item in INCLUDE_USER_FOLDERS or item in IGNORE_USER_FOLDERS:
                    continue
                target = os.path.join(user_path, item)
                if os.path.isdir(target):
                    sys.stdout.write(f"B => ")
                    record_user_gray(user, target)
    except Exception:
        pass

def record_user_gray(user, record_path):
    """
    Records the shallow listing for a given record_path (a directory) in the provided gray dictionary.
    This function is the only one that calls register_scanned_path() for the record_path.
    It attempts to list the immediate (non-hidden) contents of the record_path and then updates gray[item].
    """
    global global_user_gray
    user_path = f"/Users/{user}"
    path_within_user_str = record_path[len(user_path):]
    register_scanned_path(record_path)
    try:
        contents = os.listdir(record_path)
        contents = [c for c in contents if not should_ignore_name(c)]
    except Exception:
        contents = []
    if user not in global_user_gray:
        global_user_gray[user] = {}
    global_user_gray[user][path_within_user_str] = contents

def gather_top_level_gray_area():
    """
    For every top-level directory in "/" that is not in IGNORED_ROOT_DIRS,
    performs a shallow listing (immediate contents, filtering out hidden items)
    and updates global_top_level_gray.
    """
    try:
        for entry in os.listdir("/"):
            full_path = os.path.join("/", entry)
            if os.path.isdir(full_path):
                if any(full_path.startswith(ig) for ig in IGNORED_ROOT_DIRS) or any(full_path.startswith(ig) for ig in INCLUDE_ROOT_DIRS):
                    continue
                sys.stdout.write(f"C => #{full_path}")
                record_top_level_gray(full_path)
    except Exception:
        pass

def record_top_level_gray(full_path):
    global global_top_level_gray

    register_scanned_path(full_path)
    try:
        items = os.listdir(full_path)
        items = [i for i in items if not should_ignore_name(i)]
    except Exception:
        items = []
    global_top_level_gray[full_path] = items

def record_ignore_path(path):
    """
    Records a path in the global ignored_paths set.
    """
    global global_ignored_paths
    register_scanned_path(path)
    global_ignored_paths.add(path)

# --- REPORTING FUNCTION ---

def write_reports():
    """
    Writes out all accumulated data from global objects.
    No arguments are passed; the function uses the globals.
    """
    ensure_output_dirs()
    # Write Manual Customizations Report
    with open(MANUAL_FILE, "w") as f:
        f.write("=== Manual Customizations Report ===\n\n")
        
        # System Applications Section
        f.write("== /Applications ==\n")
        f.write("Custom Applications (non-brew):\n")
        if global_system_custom_apps:
            for app in global_system_custom_apps:
                f.write(f" - {app}\n")
        else:
            f.write(" (None found)\n")
        f.write("\nBrew Cask Applications:\n")
        if global_system_brew_apps:
            for app in global_system_brew_apps:
                f.write(f" - {app}\n")
        else:
            f.write(" (None found)\n")
        
        # Brew Formulas Section
        f.write("\n== Brew Formulas (explicit installs) ==\n")
        if global_brew_formulas:
            for formula in global_brew_formulas:
                f.write(f" - {formula}\n")
        else:
            f.write(" (None found)\n")
        
        # User Customizations Section
        f.write("\n== User Customizations ==\n")
        for user, summaries in global_user_manual.items():
            f.write(f"\n-- User: {user} --\n")
            if summaries:
                for line in summaries:
                    f.write(f" - {line}\n")
            else:
                f.write(" (No custom folders found)\n")
    
    # Write Gray Area Reports
    # Per-user gray areas
    for user, folders in global_user_gray.items():
        filename = os.path.join(GRAY_AREA_DIR, f"user_{user}_gray_area.txt")
        with open(filename, "w") as f:
            f.write(f"Gray Area for user: {user}\n")

            f.write("\nAI Prompt: Below is a listing of some things found in this user's home directory.\n")
            for folder, contents in folders.items():
                if folder == "/Library":
                    continue

                f.write(f"\n-- ~{folder} (top-level listing) --\n")
                for item in contents:
                    f.write(f" - {item}\n")

            # Print AI Prompt Multi-line text:
            f.write(textwrap.dedent("""\
                AI Prompt Continued:                     
                The Five‑Level Framework

                The framework breaks down all observed modifications into five categories:
                    1.	Default State of the Computer
                Items and settings that come pre‑installed or pre‑configured by the operating system and vendor.
                Examples:
                    •	OS system files and folders
                    •	Pre‑installed applications and default settings
                    •	Standard library files and directories in /System or /Applications on macOS
                    2.	Intentional Customizations
                Modifications you deliberately make to tailor the system to your needs.
                Examples:
                    •	Manual configuration changes (shell profiles, custom app shortcuts)
                    •	Installation of selected software packages (e.g., using Homebrew) where you explicitly choose the application
                    •	Changes to system or application settings that are applied deliberately
                    3.	User‑Created Documents
                Files that you generate or save for work, personal projects, or other purposes. These are typically important data that require regular backup.
                Examples:
                    •	Documents in your ~/Documents folder
                    •	Files saved on the Desktop or other designated data directories
                    •	Project files and code that are not part of system configurations
                    4.	Cascading Dependencies (Side‑Effects of Intentional Changes)
                Additional files or libraries that are installed automatically when you perform an intentional action. These are not explicitly chosen by you but are brought in as a dependency.
                Examples:
                    •	When installing MySQL via Homebrew, libraries (such as a curses library) that are installed automatically
                    •	Auto‑resolved dependency packages that are not manually selected
                    5.	Transactional (Ephemeral) Files
                Files generated during regular system use that are transient or routine byproducts. These files typically do not require manual backup or long‑term tracking.
                Examples:
                    •	Log files (in /var/log or ~/Library/Logs)
                    •	Cache files (in /Library/Caches or application‑specific cache directories)
                    •	Temporary files created during application use

                My goal in giving you this is that you can identify the:
                - Intentional Customizations
                - User‑Created Documents

                ... and ignore everything else.  You are preparing to back up this stuff we DO care about. Give me:
                1. a list of top-level items only that can be ignored and why
                2. give me a command to do a `tar -czvpf` (to be run from within that home dir) to zip up of the ones that are worth keeping
                3. Give me a paragraph with the reasoning behind keeping the files you chose.

                Please, lean towards excluding more than including.  We want to be sure we are not backing up unnecessary files.  If you are unsure about a file, it is better to exclude it.  We can always come back and add it later if needed.  Especially with dot files and folders, if it is from a package you recognize, and it doesn't have secret keys or something, then I don't really want to keep it.
                """))
    # Top-level gray areas (from initial gather)
    for dir_path, items in global_top_level_gray.items():
        safe_name = dir_path.strip("/").replace("/", "_") or "root"
        filename = os.path.join(GRAY_AREA_DIR, f"{safe_name}_gray_area.txt")
        with open(filename, "w") as f:
            f.write(f"Gray Area for {dir_path} (top-level listing):\n")
            for item in items:
                f.write(f" - {item}\n")
    # Remaining gray areas (from crawl_remaining_paths)
    for dir_path, items in global_remaining_gray.items():
        safe_name = dir_path.strip("/").replace("/", "_") or "root"
        filename = os.path.join(GRAY_AREA_DIR, f"{safe_name}_remaining_gray.txt")
        with open(filename, "w") as f:
            f.write(f"Remaining Gray Area for {dir_path} (shallow listing):\n")
            for item in items:
                f.write(f" - {item}\n")
    
    # Write Ignored Directories
    with open(IGNORED_FILE, "w") as f:
        f.write("Ignored Directories (not scanned):\n")
        for d in global_ignored_paths:
            f.write(f" - {d}\n")

# --- MAIN DRIVER ---

def main():
    ensure_output_dirs()
    
    # record all the IGNORED_ROOT_DIRS as ignored paths
    for ig in IGNORED_ROOT_DIRS:
        record_ignore_path(ig)

    # Gather brew data
    print("Gathering brew data...")
    brew_casks = get_brew_casks()  # still returned, to be passed into system app processing
    print("Casks:", brew_casks)
    gather_brew_formulas()         # updates global_brew_formulas
    print("Gathering system applications...")
    gather_system_applications(brew_casks)  # updates global_system_custom_apps & global_system_brew_apps
    print("Gathering user manual customizations...")
    gather_user_manual_customizations()       # updates global_user_manual
    print("Gathering gray areas...")
    gather_user_gray_area()                   # updates global_user_gray
    gather_top_level_gray_area()              # updates global_top_level_gray
    
    # Now crawl the remaining paths and update global_remaining_gray.
    print("Starting full crawl of remaining paths (debug output will update on one line)...")
    crawl_remaining_paths("/")
    
    # Finally, write all reports.
    write_reports()
    
    print("Scan complete. Output available in", OUTPUT_DIR)

if __name__ == "__main__":
    main()