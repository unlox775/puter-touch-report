#!/bin/bash
# scan_mods.sh
# This script scans the entire filesystem, splits files into:
#   1. Manual customizations (definite intentional changes/user documents)
#   2. Gray areas (ambiguous paths to be AI‐filtered later)
#   3. Ignored files (paths that we know are system, logging, cache, etc.)
#
# The output is placed in a directory named with the current date/time stamp.

# Set up output directory with timestamp
timestamp=$(date +"%Y%m%d-%H%M%S")
output_dir="scan_output_$timestamp"
mkdir -p "$output_dir/gray_area"

# Define output files
manual_report="$output_dir/manual_customizations.txt"
ignored_report="$output_dir/ignored_files.txt"

# --- CONFIGURABLE RULES ---
# Define paths to ignore (known to be system, caches, logs, etc.)
# Adjust these as needed.
ignored_paths=(
  "/System"
  "/Library/Caches"
  "/private/var/log"
  "/private/var/tmp"
  "/tmp"
  "/var/tmp"
)

# Define paths that we consider as “definite” manual customizations or user documents.
# For example, files in the Applications folder (user-installed), Desktop, Documents, etc.
customization_paths=(
  "/Applications"
  "$HOME/Desktop"
  "$HOME/Documents"
  "$HOME/Library/Preferences"   # e.g. custom app preferences
)

# --- SCANNING ---
# For demonstration purposes, we will:
# 1. Scan the known ignore paths and dump them to ignored_report.
# 2. Scan the known customization paths and dump them to manual_report.
# 3. Perform a full scan of the filesystem, then subtract any file that appears in either list.
#
# A full scan is written to a temporary file.
# The remaining files (that don’t match our inclusion or exclusion patterns)
# are considered "gray area" and are dumped for further filtering.

# 1. Dump ignored paths (if they exist)
echo "Scanning ignored paths..."
: > "$ignored_report"
for ipath in "${ignored_paths[@]}"; do
  if [ -d "$ipath" ]; then
    echo "Ignoring files under $ipath" >> "$ignored_report"
    # List files under ipath (suppress errors)
    find "$ipath" -type f 2>/dev/null >> "$ignored_report"
  fi
done

# 2. Dump customization paths (if they exist)
echo "Scanning customization paths..."
: > "$manual_report"
for cpath in "${customization_paths[@]}"; do
  if [ -d "$cpath" ]; then
    echo "Files under $cpath (assumed manual/user modifications):" >> "$manual_report"
    find "$cpath" -type f 2>/dev/null >> "$manual_report"
  fi
done

# 3. Full filesystem scan.
# We use sudo to have access to most locations.
# The full scan will list all files and then we will exclude the ones already captured.
echo "Performing full filesystem scan (this may take a while)..."
temp_full_scan="$output_dir/full_scan.txt"
sudo find / -type f 2>/dev/null > "$temp_full_scan"

# Function: create a grep pattern from an array of paths.
build_pattern() {
  local arr=("$@")
  local pattern=""
  for p in "${arr[@]}"; do
    # Escape slashes for regex use
    p=$(echo "$p" | sed 's/\//\\\//g')
    if [ -z "$pattern" ]; then
      pattern="$p"
    else
      pattern="$pattern|$p"
    fi
  done
  echo "$pattern"
}

# Build regex patterns for ignored and customization paths.
ignored_regex=$(build_pattern "${ignored_paths[@]}")
customization_regex=$(build_pattern "${customization_paths[@]}")

# 4. Extract gray area files:
# Exclude any file that matches either the ignored or customization patterns.
gray_area_file="$output_dir/gray_area/gray_area_files.txt"
grep -Ev "$ignored_regex" "$temp_full_scan" | grep -Ev "$customization_regex" > "$gray_area_file"

# Optional: Further break gray areas into separate dumps by top-level directory.
# For example, group by the first component of the path (e.g., /Users, /opt, /usr).
echo "Grouping gray area files by top-level directory..."
awk -F/ '{ if (NF>1) print "/"$2; else print "/" }' "$gray_area_file" | sort | uniq | while read topdir; do
  # Replace "/" with an underscore for filename ("/Users" becomes "_Users.txt")
  outfile=$(echo "$topdir" | sed 's/\//_/g')
  outfile="${outfile:-root}"
  grep "^$topdir" "$gray_area_file" > "$output_dir/gray_area/gray_area${outfile}.txt"
done

# Cleanup temporary file
rm "$temp_full_scan"

echo "Scan complete."
echo "Manual customizations stored in: $manual_report"
echo "Ignored files stored in: $ignored_report"
echo "Gray area files and grouped dumps stored in: $output_dir/gray_area"