"""Only declared, verified package bytes belong in a shared test archive."""
import hashlib
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import zipfile

from tools.test_package.archive_package import create_archive


class PackageArchiveTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.package = self.root / 'package'
        self.package.mkdir()
        self.payload = {'README.md': b'public instructions', 'runtime/python.exe': b'public runtime fixture',
                        'reframework/autorun/probe.lua': b'public project Lua fixture'}
        for name, data in self.payload.items():
            path = self.package / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        self.manifest = {'schema': 1, 'save_protection_schema': 1, 'source_commit': 'a' * 40,
                         'files': {name: hashlib.sha256(data).hexdigest() for name, data in self.payload.items()}}
        self.output = self.root / 'shared.zip'
        self.write_manifest()

    def write_manifest(self):
        (self.package / 'bundle-manifest.json').write_text(json.dumps(self.manifest), encoding='utf-8')

    def test_exports_only_manifest_files_and_emits_the_actual_zip_checksum(self):
        (self.package / 'installation.json').write_bytes(b'private local game path')
        (self.package / 'personal.save').write_bytes(b'private synthetic save')
        result = create_archive(self.package, self.output)
        with zipfile.ZipFile(self.output) as archive:
            self.assertEqual(set(archive.namelist()), set(self.payload) | {'bundle-manifest.json'})
            for name, data in self.payload.items():
                self.assertEqual(archive.read(name), data)
            self.assertEqual(json.loads(archive.read('bundle-manifest.json')), self.manifest)
        digest = hashlib.sha256(self.output.read_bytes()).hexdigest()
        self.assertEqual(result['sha256'], digest)
        self.assertEqual(result['source_commit'], 'a' * 40)
        self.assertEqual(self.output.with_suffix('.zip.sha256').read_text(), digest + '  shared.zip\n')

    def test_changed_or_missing_payload_does_not_leave_a_partial_archive(self):
        path = self.package / 'runtime/python.exe'
        for missing in (False, True):
            if missing:
                path.unlink()
            else:
                path.write_bytes(b'changed payload')
            with self.subTest(missing=missing), self.assertRaises((OSError, ValueError)):
                create_archive(self.package, self.output)
            self.assertFalse(self.output.exists())
            self.assertFalse(self.output.with_suffix('.zip.sha256').exists())

    def test_rejects_unsafe_manifest_names(self):
        for name in ('../private.save', '/absolute', 'C:/private.save', 'a\\private.save',
                     'a/../private.save', './README.md', 'a//b', 'bundle-manifest.json'):
            self.manifest['files'] = {name: '0' * 64}
            self.write_manifest()
            with self.subTest(name=name), self.assertRaises(ValueError):
                create_archive(self.package, self.output)
            self.assertFalse(self.output.exists())

    def test_directory_links_cannot_pull_private_files_into_a_manifest_archive(self):
        private = self.root / 'private'
        private.mkdir()
        (private / 'secret.txt').write_bytes(b'private fixture')
        link = self.package / 'linked'
        if os.name == 'nt':
            import _winapi
            _winapi.CreateJunction(str(private), str(link))
        else:
            link.symlink_to(private, target_is_directory=True)
        self.manifest['files'] = {'linked/secret.txt': hashlib.sha256(b'private fixture').hexdigest()}
        self.write_manifest()
        try:
            with self.assertRaises(ValueError):
                create_archive(self.package, self.output)
            self.assertFalse(self.output.exists())
        finally:
            if os.name == 'nt':
                link.rmdir()
            else:
                link.unlink()

    def test_existing_output_or_checksum_is_preserved(self):
        self.output.write_bytes(b'existing archive')
        with self.assertRaises(FileExistsError):
            create_archive(self.package, self.output)
        self.assertEqual(self.output.read_bytes(), b'existing archive')
        self.output.unlink()
        checksum = self.output.with_suffix('.zip.sha256')
        checksum.write_bytes(b'existing checksum')
        with self.assertRaises(FileExistsError):
            create_archive(self.package, self.output)
        self.assertEqual(checksum.read_bytes(), b'existing checksum')
        self.assertFalse(self.output.exists())

    def test_reexport_has_identical_bytes_despite_file_times_and_private_extras(self):
        create_archive(self.package, self.output)
        for name in self.payload:
            os.utime(self.package / name, (1_800_000_000, 1_800_000_000))
        (self.package / 'installation.json').write_bytes(b'new private pointer')
        other = self.root / 'second.zip'
        create_archive(self.package, other)
        self.assertEqual(self.output.read_bytes(), other.read_bytes())

    def test_refuses_export_into_the_package_directory(self):
        output = self.package / 'shared.zip'
        with self.assertRaises(ValueError):
            create_archive(self.package, output)
        self.assertFalse(output.exists())

    def test_requires_a_protected_manifest_with_source_identity(self):
        original = dict(self.manifest)
        for change in ({'schema': True}, {'save_protection_schema': 0}, {'source_commit': 'not-a-commit'},
                       {'files': []}, {'files': {}}, {'files': {'README.md': True}}):
            self.manifest = {**original, **change}
            self.write_manifest()
            with self.subTest(change=change), self.assertRaises(ValueError):
                create_archive(self.package, self.output)
            self.assertFalse(self.output.exists())
