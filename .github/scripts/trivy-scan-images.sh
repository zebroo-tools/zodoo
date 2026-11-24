#!/usr/bin/env bash
# Part of Zebroo GmbH. See LICENSE file for full copyright and licensing details (www.zebroo.de/license).
#
# CVE scan of the locally built prebuild images, used by prebuild-images.yml
# between "odoo build --no-zodoo-push" and "odoo zodoo-push".
#
#   trivy-scan-images.sh scan   <project> <report-dir> <service>...
#   trivy-scan-images.sh verify <project> <report-dir> <service>...
#
# "scan" resolves each service to the local image that zodoo-push uploads
# (<project>-<service>, see _local_image_name in lib_zodoo_registry.py),
# logs its image ID and scans exactly that ID: the image is exported with
# "docker save <id>" and Trivy reads the tarball, so no tag can move
# between lookup and scan.
#
# "verify" runs right before the push and fails if any of these images now
# has a different ID than the one that was scanned.
#
# Findings never fail the script (report only, a blocking threshold is a
# separate decision). Everything else does: missing image, DB download,
# Trivy error. The workflow relies on that to skip the push (fail-closed).
#
# Environment:
#   TRIVY_CACHE_DIR       vulnerability DB location (required)
#   TRIVY_FORCE_FAILURE   "true" makes the scan fail on purpose (CI test of
#                         the fail-closed path): Trivy is pointed at an empty
#                         DB directory and told not to download one.
#   GITHUB_STEP_SUMMARY   summary table is appended here when set
set -euo pipefail

mode="${1:?mode (scan|verify) missing}"
project="${2:?project name missing}"
report_dir="${3:?report directory missing}"
shift 3
[ "$#" -gt 0 ] || {
	echo "::error::no services given"
	exit 1
}
: "${TRIVY_CACHE_DIR:?TRIVY_CACHE_DIR must be set}"

ids_file="$report_dir/scanned-image-ids.txt"

image_id() {
	docker image inspect --format '{{.Id}}' "$1"
}

summarize() {
	# Counts per severity from a Trivy JSON report, plus how many of them
	# have a fixed version. Prints one Markdown table row.
	python3 - "$@" <<'PY'
import json, sys
service, image_id, path = sys.argv[1:4]
with open(path) as fh:
    report = json.load(fh)
counts = {s: [0, 0] for s in ("CRITICAL", "HIGH", "MEDIUM")}
for result in report.get("Results") or []:
    for vuln in result.get("Vulnerabilities") or []:
        entry = counts.get(vuln.get("Severity"))
        if entry is None:
            continue
        entry[0] += 1
        if vuln.get("FixedVersion"):
            entry[1] += 1
cells = [f"{total} ({fixable})" for total, fixable in counts.values()]
print(f"| {service} | `{image_id[:19]}` | " + " | ".join(cells) + " |")
PY
}

scan() {
	mkdir -p "$report_dir"
	: >"$ids_file"

	local cache="$TRIVY_CACHE_DIR"
	if [ "${TRIVY_FORCE_FAILURE:-false}" = "true" ]; then
		echo "::warning::TRIVY_FORCE_FAILURE is set: the scan will fail on purpose."
		cache="$(mktemp -d)"
	fi

	local rows=() service image id tmp tar json
	for service in "$@"; do
		image="${project}-${service}"
		if ! id="$(image_id "$image")"; then
			echo "::error::Image $image not found, nothing to scan for service $service."
			exit 1
		fi
		echo "Scanning $image image-id=$id"
		echo "$service $id" >>"$ids_file"

		# Named after the image: Trivy shows the file name as the target
		# in the report.
		tmp="$(mktemp -d "${TMPDIR:-/tmp}/trivy.XXXXXX")"
		tar="$tmp/$image.tar"
		json="$report_dir/$service.json"
		docker save "$id" -o "$tar"
		# --exit-code 0: findings are reported, not enforced. A Trivy error
		# still exits non-zero and stops the script.
		if ! trivy image \
			--cache-dir "$cache" \
			--skip-db-update \
			--skip-java-db-update \
			--scanners vuln \
			--exit-code 0 \
			--quiet \
			--format json \
			--output "$json" \
			--input "$tar"; then
			rm -rf "$tmp"
			echo "::error::Trivy failed for $image ($id). Nothing is pushed."
			exit 1
		fi
		rm -rf "$tmp"
		trivy convert --quiet --format table --output "$report_dir/$service.txt" "$json"
		rows+=("$(summarize "$service" "$id" "$json")")
	done

	local summary
	summary="$(
		echo "### Trivy scan: $project"
		echo
		echo "Findings per severity, fixable ones in brackets. Report only, findings do not fail the job."
		echo
		echo "| Image | Image ID | CRITICAL | HIGH | MEDIUM |"
		echo "| --- | --- | --- | --- | --- |"
		printf '%s\n' "${rows[@]}"
		echo
	)"
	echo "$summary"
	if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then
		echo "$summary" >>"$GITHUB_STEP_SUMMARY"
	fi
}

verify() {
	[ -s "$ids_file" ] || {
		echo "::error::$ids_file missing: images were not scanned."
		exit 1
	}
	local service scanned_id current_id
	for service in "$@"; do
		scanned_id="$(awk -v s="$service" '$1 == s {print $2}' "$ids_file")"
		if [ -z "$scanned_id" ]; then
			echo "::error::Service $service was not scanned."
			exit 1
		fi
		current_id="$(image_id "${project}-${service}")"
		if [ "$current_id" != "$scanned_id" ]; then
			echo "::error::${project}-${service} changed after the scan ($scanned_id -> $current_id)."
			exit 1
		fi
		echo "Push candidate ${project}-${service} image-id=$current_id matches scanned image"
	done
}

case "$mode" in
scan) scan "$@" ;;
verify) verify "$@" ;;
*)
	echo "::error::unknown mode $mode"
	exit 1
	;;
esac
