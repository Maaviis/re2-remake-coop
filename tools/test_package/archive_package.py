"""Export only manifest-bound public package bytes, with an archive checksum."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import stat
import zipfile


def _file(root, name):
    relative = PurePosixPath(name)
    if (not name or relative.is_absolute() or relative.as_posix() != name
            or any(part in ('.', '..') for part in relative.parts)
            or any(char in name for char in ('\\', ':', '\0'))):
        raise ValueError('Unsafe package manifest path: ' + name)
    path = root
    for part in relative.parts:
        path = path / part
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            raise ValueError('Package payload contains a link: ' + name)
    if not path.is_file():
        raise ValueError('Package payload is not a regular file: ' + name)
    return path


def create_archive(package, output):
    root = Path(package).resolve(strict=True)
    output = Path(output).resolve()
    checksum = output.with_suffix(output.suffix + '.sha256')
    if output.is_relative_to(root):
        raise ValueError('Export outside the package directory')
    if output.exists() or checksum.exists():
        raise FileExistsError('Archive or checksum already exists')
    manifest_bytes = _file(root, 'bundle-manifest.json').read_bytes()
    manifest = json.loads(manifest_bytes.decode('utf-8-sig'))
    if (not isinstance(manifest, dict) or type(manifest.get('schema')) is not int or manifest['schema'] != 1
            or type(manifest.get('save_protection_schema')) is not int or manifest['save_protection_schema'] != 1
            or not isinstance(manifest.get('source_commit'), str)
            or not re.fullmatch('[0-9a-f]{40}', manifest['source_commit'])
            or not isinstance(manifest.get('files'), dict) or not manifest['files']):
        raise ValueError('A protected package manifest with a source commit is required')
    payload = []
    for name, expected in sorted(manifest['files'].items()):
        if (not isinstance(name, str) or name == 'bundle-manifest.json'
                or not isinstance(expected, str) or not re.fullmatch('[0-9a-f]{64}', expected)):
            raise ValueError('Invalid package manifest entry')
        payload.append((name, _file(root, name), expected))

    output.parent.mkdir(parents=True, exist_ok=True)
    created = checksum_created = False
    try:
        with output.open('xb') as stream:
            created = True
            with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
                def add(name, data):
                    entry = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 2))
                    entry.create_system = 3
                    entry.external_attr = 0o100644 << 16
                    entry.compress_type = zipfile.ZIP_DEFLATED
                    archive.writestr(entry, data)

                for name, path, expected in payload:
                    data = path.read_bytes()
                    if hashlib.sha256(data).hexdigest() != expected:
                        raise ValueError('Package checksum mismatch: ' + name)
                    add(name, data)
                add('bundle-manifest.json', manifest_bytes)
        digest = hashlib.sha256(output.read_bytes()).hexdigest()
        with checksum.open('x', encoding='ascii', newline='\n') as stream:
            checksum_created = True
            stream.write(digest + '  ' + output.name + '\n')
    except BaseException:
        if checksum_created:
            checksum.unlink(missing_ok=True)
        if created:
            output.unlink(missing_ok=True)
        raise
    return {'output': str(output), 'source_commit': manifest['source_commit'],
            'files': len(payload) + 1, 'sha256': digest}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    try:
        result = create_archive(args.package, args.output)
    except (OSError, ValueError) as exc:
        raise SystemExit(str(exc)) from None
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
