#!/usr/bin/env python3
"""Build, validate and assemble the SQ-64 custom firmware registry site.

For every entry in registry/*.json this script:
  1. validates the entry document,
  2. clones the firmware repository at its pinned commit,
  3. builds it with `make`,
  4. runs the conformance spec's `image` profile against the built .vsb,
  5. runs a headless emulator smoke execution and refuses any image that
     faults or trips a critical damage detector,
  6. validates any shipped emulator UI scripts (scripts/*.json),
  7. copies the artifact, scripts and reports into the output site next to
     a generated index.json manifest.

The script needs local checkouts of the public spec and emulator projects
(--spec/--emulator). The emulator package must be importable by the Python
interpreter given with --emulator-python (for the headless run), and `node`
must be available (for UI script validation against the emulator's own
validator). Nothing here requires credentials, and the cloned firmware
repositories are built with a scrubbed environment.
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ENTRY_ID = re.compile(r'^[a-z0-9][a-z0-9-]{0,39}$')
COMMIT = re.compile(r'^[0-9a-f]{40}$')
HTTPS_GIT = re.compile(r'^https://[a-z0-9.-]+/[~\w./-]+$', re.IGNORECASE)
MAX_ARTIFACT_BYTES = 4 * 1024 * 1024
MAX_SCRIPT_BYTES = 1024 * 1024
MAX_SCRIPTS = 16
BUILD_TIMEOUT = 600
SMOKE_INSTRUCTIONS = 2_000_000


class EntryError(Exception):
    pass


def run(command, *, cwd=None, timeout=None, env=None):
    return subprocess.run(command, cwd=cwd, timeout=timeout, env=env,
                          capture_output=True, text=True)


def load_entry(path):
    entry_id = path.stem
    if not ENTRY_ID.fullmatch(entry_id):
        raise EntryError(f'{path.name}: file name must match {ENTRY_ID.pattern}')
    try:
        entry = json.loads(path.read_text())
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise EntryError(f'{path.name}: not valid JSON ({error})')
    if not isinstance(entry, dict):
        raise EntryError(f'{path.name}: expected a JSON object')
    allowed = {'name', 'repo', 'ref', 'artifact', 'description', 'homepage', 'order'}
    unknown = set(entry) - allowed
    if unknown:
        raise EntryError(f'{path.name}: unknown fields {sorted(unknown)}')
    def text(field, limit, required=True):
        value = entry.get(field)
        if value is None and not required:
            return None
        if not isinstance(value, str) or not value.strip() or len(value) > limit:
            raise EntryError(f'{path.name}: "{field}" must be a non-empty string of at most {limit} characters')
        return value.strip()
    name = text('name', 80)
    repo = text('repo', 200)
    ref = text('ref', 40)
    artifact = text('artifact', 200)
    description = text('description', 400)
    homepage = text('homepage', 200, required=False)
    order = entry.get('order', 1000)
    if not HTTPS_GIT.fullmatch(repo):
        raise EntryError(f'{path.name}: "repo" must be a public https git URL')
    if not COMMIT.fullmatch(ref):
        raise EntryError(f'{path.name}: "ref" must be a full 40-character commit hash')
    artifact_path = Path(artifact)
    if artifact_path.is_absolute() or '..' in artifact_path.parts or artifact_path.suffix.lower() != '.vsb':
        raise EntryError(f'{path.name}: "artifact" must be a relative path to a .vsb file inside the repository')
    if homepage and not homepage.startswith('https://'):
        raise EntryError(f'{path.name}: "homepage" must be an https URL')
    if not isinstance(order, int) or not 0 <= order <= 1_000_000:
        raise EntryError(f'{path.name}: "order" must be an integer from 0 to 1,000,000')
    return {'id': entry_id, 'name': name, 'repo': repo, 'ref': ref, 'artifact': artifact,
            'description': description, 'homepage': homepage, 'order': order}


def clone_pinned(repo, ref, destination):
    for step in (['git', 'init', '--quiet', str(destination)],
                 ['git', '-C', str(destination), 'remote', 'add', 'origin', repo],
                 ['git', '-C', str(destination), 'fetch', '--quiet', '--depth', '1', 'origin', ref],
                 ['git', '-C', str(destination), 'checkout', '--quiet', 'FETCH_HEAD']):
        result = run(step, timeout=300, env=scrubbed_env())
        if result.returncode:
            raise EntryError(f'could not fetch {repo} at {ref}: {result.stderr.strip() or result.stdout.strip()}')


def scrubbed_env():
    env = {key: value for key, value in os.environ.items()
           if not re.search(r'TOKEN|SECRET|PASSWORD|CREDENTIAL|AUTH', key, re.IGNORECASE)}
    env['GIT_TERMINAL_PROMPT'] = '0'
    return env


def build_entry(entry, checkout):
    result = run(['make'], cwd=checkout, timeout=BUILD_TIMEOUT, env=scrubbed_env())
    if result.returncode:
        raise EntryError(f'make failed (exit {result.returncode}):\n{result.stdout[-2000:]}\n{result.stderr[-2000:]}')
    artifact = checkout / entry['artifact']
    if not artifact.is_file():
        raise EntryError(f'make succeeded but did not produce {entry["artifact"]}')
    size = artifact.stat().st_size
    if size > MAX_ARTIFACT_BYTES:
        raise EntryError(f'{entry["artifact"]} is {size} bytes; the limit is {MAX_ARTIFACT_BYTES}')
    return artifact


def validate_image(artifact, spec, report_path):
    result = run([sys.executable, '-m', 'sq64_spec', str(artifact),
                  '--profile', 'image', '--output', str(report_path)],
                 cwd=spec, timeout=300)
    if not report_path.is_file():
        raise EntryError(f'conformance run produced no report: {result.stderr.strip()}')
    report = json.loads(report_path.read_text())
    if result.returncode or report.get('status') != 'pass':
        failed = [row['id'] for row in report.get('results', []) if row.get('status') == 'fail']
        raise EntryError(f'image profile failed: {", ".join(failed) or report.get("status")}')
    return report


def smoke_run(artifact, emulator_python, report_path):
    result = run([emulator_python, '-m', 'sq64_emulator', str(artifact), '--headless',
                  '--instructions', str(SMOKE_INSTRUCTIONS), '--report', str(report_path)],
                 timeout=900)
    if not report_path.is_file():
        raise EntryError(f'headless run produced no report (exit {result.returncode}): {result.stderr[-2000:]}')
    report = json.loads(report_path.read_text())
    if result.returncode or report.get('error'):
        raise EntryError(f'headless run failed: {report.get("error") or result.stderr[-500:]}')
    critical = report.get('critical') or {}
    if critical.get('terminated'):
        raise EntryError('headless run was terminated by a critical damage detector')
    tripped = [row['id'] for row in critical.get('results', [])
               if row.get('severity') == 'critical' and row.get('unsafeWhen') == 'pass'
               and row.get('status') == 'pass']
    if tripped:
        raise EntryError(f'critical damage detectors tripped: {", ".join(tripped)}')
    return report


def validate_scripts(checkout, validator):
    scripts_dir = checkout / 'scripts'
    if not scripts_dir.is_dir():
        return []
    files = sorted(path for path in scripts_dir.glob('*.json') if path.is_file())
    if len(files) > MAX_SCRIPTS:
        raise EntryError(f'at most {MAX_SCRIPTS} UI scripts are published; found {len(files)}')
    scripts = []
    for path in files:
        if path.stat().st_size > MAX_SCRIPT_BYTES:
            raise EntryError(f'UI script {path.name} exceeds 1 MiB')
        result = run(['node', str(validator), str(path)], timeout=60)
        if result.returncode:
            raise EntryError(f'UI script {path.name} is invalid: {result.stdout.strip() or result.stderr.strip()}')
        scripts.append({'file': path, 'name': json.loads(result.stdout)['name']})
    return scripts


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def process(entry, args, site, work):
    checkout = work / entry['id']
    print(f'[{entry["id"]}] fetching {entry["repo"]} at {entry["ref"]}')
    clone_pinned(entry['repo'], entry['ref'], checkout)
    print(f'[{entry["id"]}] building with make')
    artifact = build_entry(entry, checkout)
    reports = site / 'reports' / entry['id']
    reports.mkdir(parents=True)
    print(f'[{entry["id"]}] running conformance image profile')
    validation = validate_image(artifact, args.spec, reports / 'validation.json')
    print(f'[{entry["id"]}] running headless emulator smoke execution')
    smoke_run(artifact, args.emulator_python, reports / 'smoke.json')
    scripts = validate_scripts(checkout, args.script_validator)
    firmware_dir = site / 'firmware' / entry['id']
    firmware_dir.mkdir(parents=True)
    published = firmware_dir / artifact.name
    shutil.copyfile(artifact, published)
    published_scripts = []
    if scripts:
        (firmware_dir / 'scripts').mkdir()
        for script in scripts:
            copy = firmware_dir / 'scripts' / script['file'].name
            shutil.copyfile(script['file'], copy)
            published_scripts.append({'name': script['name'],
                                      'file': copy.relative_to(site).as_posix(),
                                      'sha256': sha256(copy)})
    print(f'[{entry["id"]}] pass · {published.name} · sha256 {sha256(published)}')
    return {'id': entry['id'], 'name': entry['name'], 'description': entry['description'],
            'repo': entry['repo'], 'ref': entry['ref'],
            **({'homepage': entry['homepage']} if entry['homepage'] else {}),
            'file': published.relative_to(site).as_posix(),
            'sha256': sha256(published), 'bytes': published.stat().st_size,
            'specVersion': validation.get('specVersion'),
            'validation': (reports / 'validation.json').relative_to(site).as_posix(),
            'smoke': (reports / 'smoke.json').relative_to(site).as_posix(),
            'scripts': published_scripts, 'order': entry['order']}


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--registry', type=Path, default=Path('registry'))
    parser.add_argument('--out', type=Path, default=Path('site'))
    parser.add_argument('--spec', type=Path, required=True, help='Checkout of the conformance spec project')
    parser.add_argument('--emulator', type=Path, required=True, help='Checkout of the emulator project')
    parser.add_argument('--emulator-python', default=sys.executable,
                        help='Python interpreter with the sq64_emulator package installed')
    parser.add_argument('--entries', nargs='*', help='Only process these entry ids (default: all)')
    args = parser.parse_args()
    # The validator imports the emulator's own script validation module so the
    # registry accepts exactly what the emulator accepts.
    args.script_validator = Path(__file__).resolve().parent / 'validate_ui_script.mjs'
    os.environ['SQ64_EMULATOR_WEB'] = str((args.emulator / 'web').resolve())

    paths = sorted(args.registry.glob('*.json'))
    if not paths:
        print('No registry entries found', file=sys.stderr)
        return 1
    if args.out.exists():
        shutil.rmtree(args.out)
    args.out.mkdir(parents=True)
    failures, manifest = [], []
    with tempfile.TemporaryDirectory(prefix='sq64-registry-') as work:
        for path in paths:
            try:
                entry = load_entry(path)
            except EntryError as error:
                failures.append(str(error))
                print(f'FAIL {path.name}: {error}', file=sys.stderr)
                continue
            if args.entries and entry['id'] not in args.entries:
                continue
            try:
                manifest.append(process(entry, args, args.out, Path(work)))
            except (EntryError, subprocess.TimeoutExpired) as error:
                failures.append(f'{entry["id"]}: {error}')
                print(f'FAIL {entry["id"]}: {error}', file=sys.stderr)
    manifest.sort(key=lambda row: (row['order'], row['id']))
    for row in manifest:
        del row['order']
    index = {'format': 'sq64-firmware-registry', 'version': 1,
             'generatedAt': datetime.now(timezone.utc).isoformat(timespec='seconds'),
             'entries': manifest}
    (args.out / 'index.json').write_text(json.dumps(index, indent=2) + '\n')
    print(f'Published {len(manifest)} firmware image(s) to {args.out}')
    if failures:
        print(f'{len(failures)} entr{"y" if len(failures) == 1 else "ies"} failed', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
