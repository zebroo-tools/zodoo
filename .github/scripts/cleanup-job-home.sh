#!/usr/bin/env bash
# Part of Zebroo GmbH. See LICENSE file for full copyright and licensing details (www.zebroo.de/license).
#
# Remove the per-job HOME created by the "Isolate job home and tools" step.
#
# Why this exists: the self-hosted runners talk to a user-namespaced Docker
# daemon. Containers started by a job (postgres above all) write their socket
# and log directories into the job home as a remapped UID (e.g. 166534). The
# runner user cannot delete those files, so the runner's own cleanup of
# _work/_temp fails silently and every job leaves its h.* directory behind.
# On 30.10.2026 that filled the runner disk and took both runners offline.
#
# What it does, in this order:
#   1. refuse anything that is not a directory "h.*" directly below
#      $RUNNER_TEMP (never a glob, never another job's home);
#   2. remove the containers that mount something from this home (plus their
#      named volumes), so nothing keeps writing into it; containers of other
#      jobs on the shared daemon are not touched;
#   3. try a plain rm -rf;
#   4. if files are left, delete them from inside a throwaway container on
#      the same Docker daemon (root there maps to the remapped UIDs), then
#      rm -rf again.
#
# Exit codes: 0 = removed or nothing to do; 0 with a ::warning:: = could not
# remove everything (the job result is not changed by cleanup); 2 = refused
# path (a workflow bug, so the step fails visibly).
#
# Usage: cleanup-job-home.sh <job-home>
set -uo pipefail

IMAGE="${JOB_HOME_CLEANUP_IMAGE:-busybox:1.36}"

die_refused() {
    echo "::error::cleanup-job-home: refusing to remove '$1': $2"
    exit 2
}

job_home="${1:-}"
[[ -n "$job_home" ]] || die_refused "" "no path given"
[[ -n "${RUNNER_TEMP:-}" ]] || die_refused "$job_home" "RUNNER_TEMP is not set"

if [[ ! -e "$job_home" && ! -L "$job_home" ]]; then
    echo "cleanup-job-home: $job_home does not exist, nothing to do"
    exit 0
fi
[[ -L "$job_home" ]] && die_refused "$job_home" "is a symlink"
[[ -d "$job_home" ]] || die_refused "$job_home" "is not a directory"

temp_real="$(cd "$RUNNER_TEMP" && pwd -P)" || die_refused "$job_home" "RUNNER_TEMP not accessible"
home_real="$(cd "$job_home" && pwd -P)" || die_refused "$job_home" "not accessible"
[[ "$(dirname "$home_real")" == "$temp_real" ]] || die_refused "$job_home" "not directly below RUNNER_TEMP"
[[ "$(basename "$home_real")" == h.?* ]] || die_refused "$job_home" "name does not start with h."

# Our own HOME may be the directory we are about to delete; work from /.
cd /

have_docker=0
command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1 && have_docker=1

if [[ "$have_docker" == 1 ]]; then
    # Only containers that mount something from THIS home. The tools runners
    # share one Docker daemon and the bake test uses fixed project names
    # (baketest190), so selecting by compose project would also hit a bake
    # running at the same time on the other runner (seen on 13.11.2026).
    own=()
    volumes=()
    mapfile -t all < <(docker ps -aq --no-trunc)
    for id in "${all[@]}"; do
        mine=0
        vols=()
        while IFS='|' read -r mtype msrc mname; do
            case "$msrc/" in "$home_real/"*) mine=1 ;; esac
            [[ "$mtype" == volume && -n "$mname" ]] && vols+=("$mname")
        done < <(docker inspect --format \
            '{{range .Mounts}}{{.Type}}|{{.Source}}|{{.Name}}{{println}}{{end}}' \
            "$id" 2>/dev/null)
        if [[ "$mine" == 1 ]]; then
            own+=("$id")
            volumes+=("${vols[@]}")
        fi
    done
    if ((${#own[@]})); then
        echo "cleanup-job-home: removing ${#own[@]} container(s) using $home_real"
        docker rm -f "${own[@]}" >/dev/null || true
    fi
    # Named volumes of those containers; docker refuses volumes still in use.
    if ((${#volumes[@]})); then
        docker volume rm "${volumes[@]}" >/dev/null 2>&1 || true
    fi
fi

rm -rf "$home_real" 2>/dev/null

if [[ -e "$home_real" && "$have_docker" == 1 ]]; then
    echo "cleanup-job-home: files owned by other UIDs left, removing them via $IMAGE"
    docker run --rm --pull missing --network none --user 0:0 \
        -v "$home_real:/job-home" "$IMAGE" \
        sh -c 'rm -rf /job-home/* /job-home/.[!.]* /job-home/..?*' || true
    rm -rf "$home_real" 2>/dev/null
fi

if [[ -e "$home_real" ]]; then
    left="$(find "$home_real" 2>/dev/null | wc -l)"
    echo "::warning::cleanup-job-home: could not remove $home_real ($left entries left, docker available: $have_docker)"
    exit 0
fi
echo "cleanup-job-home: removed $home_real"
