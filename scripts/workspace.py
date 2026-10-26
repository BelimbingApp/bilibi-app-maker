#!/usr/bin/env python3
"""Application workspace commands; component repositories own their local work."""
import argparse
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import tomllib
import uuid

import recipe

ROOT, PLATFORM, BUILD = recipe.ROOT, recipe.PLATFORM, recipe.BUILD
OFFICIAL = re.compile(r'https://github\.com/BelimbingApp/[A-Za-z0-9][A-Za-z0-9_.-]*(?:\.git)?')


def run(*args, cwd=ROOT, capture=False):
    return recipe.run(*map(str, args), cwd=cwd, capture=capture)


def repositories():
    yield 'platform', PLATFORM
    if PLATFORM.is_dir():
        for layer in ('domains', 'extensions'):
            parent = PLATFORM / 'apps' / layer
            if parent.is_dir():
                for folder in sorted(parent.iterdir()):
                    if folder.is_dir() and folder.name != 'src' and not folder.name.startswith('.'):
                        yield f'apps/{layer}/{folder.name}', folder


def status():
    _, sources = recipe.recipe()
    saved = dict(sources)
    print(f'Application: {ROOT}')
    print(run('git', 'status', '--short', '--branch', capture=True), end='')
    found = set()
    for name, folder in repositories():
        found.add(name)
        print(f'\n{name}: {folder}')
        if not folder.exists():
            print('Missing; run ./bilibi setup.')
            continue
        recipe.checkout(folder)
        head = run('git', 'rev-parse', 'HEAD', cwd=folder, capture=True).strip()
        print(run('git', 'status', '--short', '--branch', cwd=folder, capture=True), end='')
        print(f'Commit: {head}')
        origin = run('git', 'remote', 'get-url', 'origin', cwd=folder, capture=True).strip()
        entry = saved.get(name)
        if entry is None:
            print('Not saved in setup.toml; commit and push, then run ./bilibi pin.')
        elif head != entry['commit'] or origin != entry['url']:
            print(f'Saved: {entry["commit"]} from {entry["url"]}. Commit and push local changes, then ./bilibi pin to save them.')
        else:
            print('Matches saved source revision (working changes shown above).')
    for name in saved.keys() - found:
        print(f'\n{name}: {PLATFORM / name} — missing; run ./bilibi setup.')


def hooks():
    spec = importlib.util.spec_from_file_location('hooks', ROOT / 'scripts/install-hooks.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.install(PLATFORM, ['python3', 'scripts/discover-modules.py', '--check'])
    module.install(ROOT, ['python3', 'scripts/workspace.py', 'check-staged'])


def output_paths():
    BUILD.mkdir(parents=True, exist_ok=True)
    target = Path(os.environ.get('CARGO_TARGET_DIR', BUILD / 'target')).resolve()
    if target.is_relative_to(recipe.SOURCES):
        raise ValueError('CARGO_TARGET_DIR must be outside sources/; use build/target for outputs')
    target.mkdir(parents=True, exist_ok=True)
    # A symlink does not match Platform's directory-only /target/ ignore.
    # Keep this machine-local output link ignored without changing component source.
    exclude = Path(run('git', 'rev-parse', '--git-path', 'info/exclude', cwd=PLATFORM, capture=True).strip())
    if not exclude.is_absolute():
        exclude = PLATFORM / exclude
    exclude.parent.mkdir(parents=True, exist_ok=True)
    existing = exclude.read_text() if exclude.exists() else ''
    if '/target' not in existing.splitlines():
        with exclude.open('a') as stream:
            stream.write('\n# Bilibi workspace output link\n/target\n')
    # Older supported Platform launchers address target/debug directly. This is
    # an output link only: no editable source repository is mounted by symlink.
    link = PLATFORM / 'target'
    if link.is_symlink() and link.resolve() == target:
        pass
    elif link.exists() or link.is_symlink():
        raise ValueError(f'{link}: existing output path left unchanged. Move it to {target} deliberately, then remove the old path and rerun ./bilibi setup.')
    else:
        link.symlink_to(target, target_is_directory=True)
    os.environ['CARGO_TARGET_DIR'] = str(target)


def setup():
    for tool in ('git', 'bash'):
        if not shutil.which(tool):
            raise ValueError(f'Install {tool}, then rerun ./bilibi setup.')
    recipe.materialize()
    hooks()
    output_paths()
    run('bash', ROOT / 'scripts/dev-setup.sh', PLATFORM)
    print('Setup complete. Local sources and runtime data are preserved. Run ./bilibi start.')


def git_step(folder, *args):
    return shlex.join(['git', '-C', str(folder), *args])


def update_clean(folder, generated=None):
    """Only byte-for-byte known generated output may be replaced by update."""
    recipe.checkout(folder)
    changes = run('git', 'status', '--porcelain=v1', '-z', '--untracked-files=all', cwd=folder, capture=True)
    allowed = []
    for entry in changes.split('\0'):
        if not entry:
            continue
        path = entry[3:]
        if (entry[:2] == ' M' and generated and path in generated
                and not (folder / path).is_symlink()
                and (folder / path).is_file()
                and (folder / path).read_bytes() == generated[path]
                and not run('git', 'diff', '--summary', '--', path, cwd=folder, capture=True)):
            allowed.append(path)
            continue
        raise ValueError(f'{folder}: uncommitted work ({path}); inspect with '
                         f'{git_step(folder, "status", "--short")}, then commit or stash it yourself and rerun ./bilibi update')
    return allowed


def generated_output():
    if not PLATFORM.exists():
        return {}
    discovery = recipe.discovery_module()
    try:
        result = {str(path.relative_to(PLATFORM)): text.encode()
                  for path, text in discovery.outputs(PLATFORM, discovery.discovered(PLATFORM)).items()}
    except Exception as error:
        raise ValueError(f'{PLATFORM}: cannot verify generated composition ({error}); run '
                         f'{git_step(PLATFORM, "status", "--short")} and python3 '
                         f'{shlex.quote(str(PLATFORM / "scripts/discover-modules.py"))} --check; '
                         'resolve the reported source mismatch, then rerun ./bilibi update') from error
    # Accept the saved application lock or an intact previously restored pin.
    lock = PLATFORM / 'Cargo.lock'
    for saved in (ROOT / 'composition', PLATFORM / '.local/composition'):
        try:
            if (recipe.digest(saved / 'Cargo.lock') == recipe.read(saved / 'manifest.txt')['cargo_lock_sha256']
                    and lock.read_bytes() == (saved / 'Cargo.lock').read_bytes()):
                result['Cargo.lock'] = lock.read_bytes()
        except (OSError, ValueError, KeyError):
            pass
    return result


def origin_serves(url, commit):
    """A commit held only by a tag or pull request ref is published; an empty scratch repository cannot have it locally."""
    with tempfile.TemporaryDirectory(prefix='bilibi-served-') as scratch:
        run('git', 'init', '--quiet', scratch, cwd=ROOT)
        return subprocess.run(['git', 'fetch', '--quiet', '--depth=1', url, commit], cwd=scratch,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False).returncode == 0


def update():
    """Fast-forward the application, then restore its saved source composition."""
    update_clean(ROOT)
    branch = run('git', 'branch', '--show-current', capture=True).strip()
    if not branch:
        raise ValueError(f'{ROOT}: detached HEAD; run {git_step(ROOT, "switch", "<application-branch>")} and rerun ./bilibi update')
    remote = subprocess.run(['git', 'config', '--get', f'branch.{branch}.remote'], cwd=ROOT,
                            text=True, stdout=subprocess.PIPE, check=False).stdout.strip()
    if remote in ('', '.'):
        raise ValueError(f'{ROOT}: no remote upstream; run {git_step(ROOT, "push", "--set-upstream", "origin", branch)} and rerun ./bilibi update')
    try:
        run('git', 'fetch', '--no-tags', remote)
        upstream = run('git', 'rev-parse', '--symbolic-full-name', '@{upstream}', capture=True).strip()
        target = run('git', 'rev-parse', upstream, capture=True).strip()
    except subprocess.CalledProcessError as error:
        raise ValueError(f'{ROOT}: cannot fetch the application upstream; run {git_step(ROOT, "fetch", remote)}, '
                         'check the branch upstream with git branch -vv, then rerun ./bilibi update') from error
    ahead = run('git', 'rev-list', f'{upstream}..HEAD', capture=True).strip()
    if ahead:
        raise ValueError(f'{ROOT}: commits are not in {upstream}; inspect with {git_step(ROOT, "log", "--oneline", f"{upstream}..HEAD")}, '
                         f'then publish with {git_step(ROOT, "push")} (reconcile any divergence yourself) and rerun ./bilibi update')
    # Read the incoming recipe without changing the application checkout first.
    try:
        with tempfile.TemporaryDirectory(prefix='bilibi-update-') as temp:
            candidate = Path(temp)
            (candidate / 'composition').mkdir()
            for name in ('setup.toml', 'composition/manifest.txt', 'composition/Cargo.lock'):
                data = subprocess.check_output(['git', 'show', f'{target}:{name}'], cwd=ROOT)
                (candidate / name).write_bytes(data)
            _, sources = recipe.recipe(candidate)
            recipe.check_pin(candidate)
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as error:
        raise ValueError(f'{ROOT}/setup.toml and composition/: incoming saved composition is invalid ({error}); '
                         f'inspect with {git_step(ROOT, "show", target + ":setup.toml")}, '
                         'ask the application maintainer to publish a consistent recipe, manifest and lock, then retry') from error
    saved = dict(sources)
    mounted = list(repositories())
    for _, folder in mounted:
        if folder.is_symlink() or folder.resolve() != folder or (folder.exists() and not folder.is_dir()):
            raise ValueError(f'{folder}: conflicting source path; move it aside deliberately and rerun ./bilibi update')
        if folder.exists():
            recipe.checkout(folder)
    for name, folder in mounted:
        if folder.exists():
            if name != 'platform':
                update_clean(folder)
            else:
                # Reject edits to discovery itself before importing it. The
                # generated bytes provisionally allowed here are verified below.
                pending = {path: (folder / path).read_bytes() for path in recipe.GENERATED
                           if (folder / path).is_file() and not (folder / path).is_symlink()}
                update_clean(folder, pending)
    generated = generated_output()
    replacements = []
    for name, folder in mounted:
        if not folder.exists() and not folder.is_symlink():
            continue
        allowed = update_clean(folder, generated if name == 'platform' else None)
        if name not in saved:
            raise ValueError(f'{folder}: not in the incoming setup.toml; move this clone outside sources/ yourself, '
                             'or save it with ./bilibi pin and publish the application recipe before retrying')
        source = saved[name]
        origin = subprocess.run(['git', 'remote', 'get-url', 'origin'], cwd=folder,
                                text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=False).stdout.strip()
        if origin != source['url']:
            action = 'set-url' if origin else 'add'
            raise ValueError(f'{folder}: origin differs from setup.toml; inspect with {git_step(folder, "remote", "-v")}; '
                             f'if the saved URL is correct, run {git_step(folder, "remote", action, "origin", source["url"])} and retry')
        replacements.append((folder, source, allowed))
    # Fetch only after every existing repository has passed the edit checks.
    for folder, source, _ in replacements:
        try:
            run('git', 'fetch', '--prune', '--tags', 'origin', cwd=folder)
            unpublished = run('git', 'rev-list', 'HEAD', '--not', '--remotes=origin', cwd=folder, capture=True).strip()
            if unpublished and not origin_serves(source['url'], run('git', 'rev-parse', 'HEAD', cwd=folder, capture=True).strip()):
                raise ValueError(f'{folder}: unpushed commits; inspect with {git_step(folder, "log", "--oneline", "HEAD", "--not", "--remotes=origin")}, '
                                 f'then publish with {git_step(folder, "push", "origin", "HEAD:<branch>")} and rerun ./bilibi update')
            run('git', 'fetch', 'origin', source['commit'], cwd=folder)
        except subprocess.CalledProcessError as error:
            raise ValueError(f'{folder}: cannot obtain saved commit {source["commit"]}; run '
                             f'{git_step(folder, "fetch", "origin", source["commit"])}; verify setup.toml with its owner, then retry') from error
    head = run('git', 'rev-parse', 'HEAD', capture=True).strip()
    if head != target:
        run('git', '-c', 'core.hooksPath=/dev/null', 'merge', '--ff-only', '--no-autostash', target)
        # Use the updated command implementation and recipe after pulling scripts.
        os.execv(sys.executable, [sys.executable, str(ROOT / 'scripts/workspace.py'), 'update'])
    for folder, source, allowed in replacements:
        # These bytes were proven to be generated, and the index was clean.
        for path in allowed:
            (folder / path).write_bytes(subprocess.check_output(['git', 'show', f'HEAD:{path}'], cwd=folder))
        if run('git', 'rev-parse', 'HEAD', cwd=folder, capture=True).strip() != source['commit']:
            run('git', '-c', 'core.hooksPath=/dev/null', 'checkout', '--detach', source['commit'], cwd=folder)
    recipe.materialize()
    recipe.restore()
    print('Updated application and restored saved source commits and composition. Use ./bilibi pin to save new selections.')


def start():
    setup()
    status()
    print('\nStarting local sources with the development seed. Saved release pins are not the identity of this development run.', flush=True)
    # A development run must not compile a stale release pin as its identity.
    # Keep the old machine-local pin for inspection rather than deleting it.
    pin = PLATFORM / '.local/composition'
    if (pin / 'manifest.txt').exists():
        backup = PLATFORM / '.local' / ('composition-before-development-' + uuid.uuid4().hex)
        pin.rename(backup)
    os.chdir(PLATFORM)
    os.environ.setdefault('BILIBI_APPLICATION_ROOT', str(ROOT))
    os.execvp('bash', ['bash', '-c', 'if [[ -f $HOME/.cargo/env ]]; then source "$HOME/.cargo/env"; fi; exec bash scripts/start-app.sh'])


def add_explicit(component, kind, source, commit):
    """Keep Software's explicit-source contract in step with Platform add."""
    if component in {'base', 'core', 'web', 'src'}:
        raise ValueError('use a component ID from catalogue.json, for example: ./bilibi add finance')
    if not re.fullmatch(r'[0-9a-f]{40}', commit):
        raise ValueError('--commit must be a full 40-character lowercase commit ID')
    if not OFFICIAL.fullmatch(source):
        raise ValueError(f'{component} is not an official BelimbingApp repository; use the manual mounting guide')
    recipe.materialize()
    hooks()
    folder = PLATFORM / 'apps' / kind / component
    if folder.exists() or folder.is_symlink():
        if folder.is_symlink() or not folder.is_dir():
            raise ValueError(f'{folder} is occupied; move it aside deliberately before adding {component}')
        if Path(run('git', 'rev-parse', '--show-toplevel', cwd=folder, capture=True).strip()).resolve() != folder.resolve():
            raise ValueError(f'{folder} is not its own Git checkout; move it aside deliberately')
        actual = run('git', 'remote', 'get-url', 'origin', cwd=folder, capture=True).strip().removesuffix('.git')
        if actual != source.removesuffix('.git'):
            raise ValueError(f'{folder} has a different origin; inspect it with git -C {folder} remote -v '
                             'and reconcile it deliberately; no files or remotes were changed')
        if run('git', 'rev-parse', 'HEAD', cwd=folder, capture=True).strip() != commit:
            raise ValueError(f'{folder} is not at commit {commit}. Commit or stash its work, then run: '
                             f'git -C {folder} fetch origin && git -C {folder} checkout --detach {commit}; '
                             'nothing was changed')
        print(f'Keeping existing checkout, branch and edits: {folder}', flush=True)
    else:
        run('git', 'clone', '--', source.removesuffix('.git') + '.git', folder)
        try:
            run('git', 'checkout', '--detach', commit, cwd=folder)
        except subprocess.CalledProcessError:
            raise ValueError(f'{source} has no commit {commit}; the new clone was kept at {folder}. '
                             f'Check the commit in Software, then remove that clone (rm -rf {folder}) and retry') from None
    descriptor = tomllib.loads((folder / 'bilibi.container.toml').read_text())
    if descriptor.get('id') != component or descriptor.get('layer') != {'domains': 'domain', 'extensions': 'extension'}[kind]:
        raise ValueError(f'{folder}/bilibi.container.toml does not match the requested component; '
                         'checkout retained for inspection')
    print(f'Added {component} at {folder}. Run ./bilibi start. Commit and push component edits before ./bilibi pin.')


def add(component, kind=None, source=None, commit=None):
    if not re.fullmatch(r'[a-z][a-z0-9]*(?:_[a-z0-9]+)*', component):
        if kind is not None:
            raise ValueError('use a component ID from catalogue.json, for example: ./bilibi add finance')
        raise ValueError('Use a component ID such as finance or supply_chain.')
    if kind is not None:
        return add_explicit(component, kind, source, commit)
    # Obtain missing sources and install the guard even before the first start.
    recipe.materialize()
    hooks()
    catalogue = json.loads((PLATFORM / 'catalogue.json').read_text())
    matches = [(layer, facts) for layer in ('domains', 'extensions')
               if (facts := catalogue.get(layer, {}).get(component)) is not None]
    if len(matches) != 1:
        raise ValueError(f'{component}: choose an unambiguous official Domain or Extension from the Software page')
    layer, facts = matches[0]
    url = facts['repository'].removesuffix('.git') + '.git'
    if not re.fullmatch(r'https://github\.com/BelimbingApp/[A-Za-z0-9_.-]+\.git', url):
        raise ValueError(f'{component}: the catalogue entry is not an official BelimbingApp repository')
    folder = PLATFORM / 'apps' / layer / component
    if folder.exists() or folder.is_symlink():
        raise ValueError(f'{folder}: already exists; local work left unchanged. Run ./bilibi status.')
    # Select the remote's default branch; pin will later record this exact commit.
    listing = run('git', 'ls-remote', url, 'HEAD', capture=True).split()
    if not listing:
        raise ValueError(f'{component}: remote has no HEAD')
    recipe.clone({'url': url, 'commit': listing[0]}, folder)
    print(f'Added {component} at {folder}. Run ./bilibi start. Commit and push component edits before ./bilibi pin.')


def selected_recipe():
    setup, _ = recipe.recipe()
    selected = {'format': 1, 'targets': setup['targets'], 'domains': [], 'extensions': []}
    for name, folder in repositories():
        recipe.checkout(folder)
        changes = run('git', 'status', '--porcelain', '--untracked-files=all', cwd=folder, capture=True)
        for line in changes.splitlines():
            if name != 'platform' or line[3:] not in recipe.GENERATED or line[:2] not in (' M', 'M '):
                raise ValueError(f'{folder}: commit local changes in this repository and push before ./bilibi pin ({line})')
        source = {'url': run('git', 'remote', 'get-url', 'origin', cwd=folder, capture=True).strip(),
                  'commit': run('git', 'rev-parse', 'HEAD', cwd=folder, capture=True).strip()}
        if name == 'platform':
            selected['platform'] = source
        else:
            _, layer, identity = name.split('/')
            selected[layer].append({'id': identity, **source})
    return selected


def serialize(setup):
    # JSON strings are also TOML basic strings for validated source URLs and IDs.
    lines = ['format = 1', 'targets = ' + json.dumps(setup['targets']), '', '[platform]']
    for key, value in setup['platform'].items():
        lines.append(f'{key} = {json.dumps(value)}')
    for layer in ('domains', 'extensions'):
        for source in setup[layer]:
            lines.extend(['', f'[[{layer}]]'])
            lines.extend(f'{key} = {json.dumps(value)}' for key, value in source.items())
    return '\n'.join(lines) + '\n'


def pin():
    selected = selected_recipe()
    local = ROOT / '.local'
    local.mkdir(exist_ok=True)
    before = {name: (ROOT / name).read_bytes() for name in ('setup.toml', 'composition/manifest.txt', 'composition/Cargo.lock')}
    with tempfile.TemporaryDirectory(prefix='pin-candidate-', dir=local) as temp:
        candidate = Path(temp)
        for name in ('scripts', 'composition'):
            shutil.copytree(ROOT / name, candidate / name, ignore=shutil.ignore_patterns('__pycache__', 'node_modules'))
        for name in ('builder.toml', 'rust-toolchain.toml', '.dockerignore'):
            shutil.copyfile(ROOT / name, candidate / name)
        (candidate / 'setup.toml').write_text(serialize(selected))
        recipe.recipe(candidate)  # Validate every URL, commit and component ID first.
        env = dict(os.environ)
        # Never let a caller's path override make this candidate touch live sources.
        for key in ('BILIBI_SOURCE_DIR', 'BILIBI_BUILD_DIR', 'CARGO_TARGET_DIR'):
            env.pop(key, None)
        subprocess.run(['python3', str(candidate / 'scripts/recipe.py'), 'materialize'], env=env, check=True)
        subprocess.run(['bash', str(candidate / 'scripts/builder.sh'), 'python3', 'scripts/recipe.py', 'pin-candidate'], env=env, check=True)
        recipe.check_pin(candidate)
        if selected_recipe() != selected:
            raise ValueError('Local source selections changed while preparing the candidate; saved set left unchanged. Rerun ./bilibi pin.')
        # Concurrent hand edits must never be overwritten by the prepared candidate.
        if any((ROOT / name).read_bytes() != data for name, data in before.items()):
            raise ValueError('Saved recipe changed while pin was preparing; candidate discarded. Rerun ./bilibi pin.')
        try:
            for name in before:
                replacement = ROOT / name
                with tempfile.NamedTemporaryFile(prefix='.bilibi-pin-', dir=replacement.parent, delete=False) as stream:
                    pending = Path(stream.name)
                    stream.write((candidate / name).read_bytes())
                try:
                    pending.chmod(replacement.stat().st_mode & 0o777)
                    pending.replace(replacement)
                finally:
                    pending.unlink(missing_ok=True)
        except BaseException:
            for name, data in before.items():
                (ROOT / name).write_bytes(data)
            raise
    print('Saved the validated candidate. Review and commit setup.toml and composition/ together. Run ./bilibi setup in a fresh clone, then ./bilibi check.')


def check_staged():
    with tempfile.TemporaryDirectory(prefix='bilibi-index-') as temp:
        index = Path(temp)
        (index / 'composition').mkdir()
        for name in ('setup.toml', 'composition/manifest.txt', 'composition/Cargo.lock'):
            (index / name).write_text(run('git', 'show', ':' + name, capture=True))
        recipe.check_pin(index)


def main():
    parser = argparse.ArgumentParser(prog='./bilibi', description=__doc__)
    parser.add_argument('command', nargs='?', choices=('help', 'start', 'update', 'add', 'status', 'setup', 'check', 'pin', 'build', 'check-staged'),
                        metavar='{help,start,update,add,status,setup,check,pin,build}')
    parser.add_argument('component', nargs='?')
    parser.add_argument('--kind', choices=('domains', 'extensions'), help='add: component mount kind; give with --source and --commit')
    parser.add_argument('--source', help='add: official BelimbingApp repository URL from Software')
    parser.add_argument('--commit', help='add: exact full lowercase commit ID from Software')
    args = parser.parse_args()
    supplied = (args.kind is not None, args.source is not None, args.commit is not None)
    if any(supplied) and args.command != 'add':
        parser.error('--kind, --source and --commit are only for ./bilibi add')
    if any(supplied) and not all(supplied):
        raise ValueError('--kind, --source and --commit go together; give all three or none')
    if (args.command == 'add') != (args.component is not None):
        parser.error('Use ./bilibi add <component> [--kind domains|extensions --source <url> --commit <sha>]; other commands take no arguments')
    if args.command in (None, 'help'):
        print('This is a Bilibi application: your own product, built on Bilibi.\n'
              'To change Bilibi itself, work in https://github.com/BelimbingApp/bilibi instead.\n\n'
              'Usage: ./bilibi <command>\n\n'
              'Run your application on this computer\n'
              '  start         Install anything missing, run the application, and open it\n'
              '                in your browser.\n'
              '  add <name>    Add a Domain or Extension, such as: ./bilibi add finance\n'
              '                Or paste the add command that the Software page shows.\n'
              '                Then run ./bilibi start again to use it.\n'
              '  status        List the Platform, Domains and Extensions, with their branches,\n'
              '                your uncommitted changes, and any difference from the saved versions.\n\n'
              'Work with your team\n'
              '  update        Get your team\'s latest pushed changes, and switch every source\n'
              '                to the versions saved in setup.toml.\n'
              '  pin           Save the versions you are running into setup.toml and\n'
              '                composition/. Commit and push your source changes first,\n'
              '                then commit those files here. Needs Docker.\n\n'
              'Before a release\n'
              '  check         Build and test the saved versions against an empty test\n'
              '                database. Needs Docker.\n'
              '  build         Build the release program from the saved versions. Needs Docker.\n'
              '                docs/guides/releasing.md explains how to publish a release.\n\n'
              'Less often\n'
              '  setup         Install the tools and fetch the sources, without starting.\n'
              '  help          Show this list.')
        return
    if args.command == 'status':
        status()
        return
    if args.command == 'check-staged':
        check_staged()
        return
    local = ROOT / '.local'
    local.mkdir(exist_ok=True)
    with (local / 'workspace.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if args.command == 'add':
            add(args.component, args.kind, args.source, args.commit)
        elif args.command in ('check', 'build'):
            recipe.check_sources()
            recipe.check_pin()
            recipe.verify_remote()
            run('bash', ROOT / 'scripts/builder.sh', 'scripts/check.sh' if args.command == 'check' else 'scripts/build.sh')
        else:
            globals()[args.command]()


if __name__ == '__main__':
    try:
        main()
    except (ValueError, KeyError, OSError, subprocess.CalledProcessError) as error:
        sys.exit(str(error))
