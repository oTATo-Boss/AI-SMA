"""Reproducible template releases. Never fetches third-party skills or executes release metadata."""
import hashlib
import io
import json
import os
import re
import shutil
import ssl
import subprocess
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from sma_common import UpdateError, category, fingerprint, lock, put, read, safe, sha

ASSET = 'ai-sma-template.zip'
MANIFEST = 'release-manifest.json'
INPUTS = ['新建项目.py', '新建账号.py', '更新项目.py', '发布.json', 'README.md', 'LICENSE', '骨架', '模板']
LIMIT = 128 * 1024 * 1024
LAST_TRANSPORT = 'urllib'


def version(value):
    match = re.fullmatch(r'v?(\d+)\.(\d+)\.(\d+)', value or '')
    if not match:
        raise UpdateError('必须使用稳定语义版本：' + str(value))
    return tuple(map(int, match.groups()))


def validate_manifest(manifest):
    if not isinstance(manifest, dict) or manifest.get('schema_version') != 1 or manifest.get('update_protocol') != 1:
        raise UpdateError('不支持的发行清单或更新协议')
    files = manifest.get('files')
    if not isinstance(files, dict) or not files or len(files) > 20000:
        raise UpdateError('发行文件清单格式或数量无效')
    for rel, spec in files.items():
        if not isinstance(rel, str) or not isinstance(spec, dict) or not re.fullmatch('[0-9a-f]{64}', str(spec.get('sha256', ''))):
            raise UpdateError('发行文件摘要格式无效')
        if spec.get('mode') not in {0o644, 0o755}:
            raise UpdateError('不支持的发行文件权限')


def build(root, output, development=False):
    root, output = Path(root).resolve(), Path(output).resolve()
    meta = read(root / '发布.json')
    version(meta['version'])
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
    dirty = subprocess.check_output(['git', 'status', '--porcelain', '--', *INPUTS], cwd=root, text=True).strip()
    if dirty and not development:
        raise UpdateError('发行输入尚未提交，不能构建稳定发行')
    files = {}
    for item in INPUTS:
        source = root / item
        for path in sorted(source.rglob('*')) if source.is_dir() else [source]:
            rel = path.relative_to(root).as_posix()
            if '__pycache__' in path.parts or path.suffix == '.pyc' or path.name == '.DS_Store':
                continue
            safe(root, rel)
            if path.is_file():
                files[rel] = {'sha256': sha(path), 'mode': 0o755 if path.stat().st_mode & 0o111 else 0o644,
                              'ownership': category(rel[3:]) if rel.startswith('骨架/') else 'release'}
    manifest = dict(meta, schema_version=1, source_commit=commit, development=development, files=files)
    data = (json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode()
    output.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output / ASSET, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for rel, spec in sorted(files.items()):
            info = zipfile.ZipInfo(rel, (2020, 1, 1, 0, 0, 0))
            info.external_attr = spec['mode'] << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, (root / rel).read_bytes())
        archive.writestr(MANIFEST, data)
    put(output / MANIFEST, data)
    put(output / 'checksums.json', {ASSET: sha(output / ASSET), MANIFEST: sha(output / MANIFEST)})
    return manifest


def verify(root, allow_development=False):
    root = Path(root)
    manifest = read(safe(root, MANIFEST))
    validate_manifest(manifest)
    if not isinstance(manifest, dict) or manifest.get('update_protocol') != 1:
        raise UpdateError('不支持的更新协议或缺少发行清单')
    version(manifest.get('version'))
    if manifest.get('repository') != 'oTATo-Boss/AI-SMA' or not re.fullmatch('[0-9a-f]{40}', manifest.get('source_commit', '')):
        raise UpdateError('发行来源不符')
    if manifest.get('development') and not allow_development:
        raise UpdateError('开发包不能进入稳定更新')
    files = manifest.get('files', {})
    if not files or any(p not in files for p in ('新建项目.py', '发布.json', '更新项目.py')):
        raise UpdateError('发行包缺少必要文件')
    for rel, spec in files.items():
        path = safe(root, rel)
        if sha(path) != spec.get('sha256'):
            raise UpdateError('发行文件摘要不匹配：' + rel)
    actual = {p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc'}
    if actual != set(files) | {MANIFEST}:
        raise UpdateError('发行包存在未登记文件')
    if read(root / '发布.json')['version'] != manifest['version']:
        raise UpdateError('发行与装配版本不一致')
    return manifest


def unpack(data, destination, allow_development=False, expected_manifest=None):
    try:
        return _unpack(data, destination, allow_development, expected_manifest)
    except (zipfile.BadZipFile, zipfile.LargeZipFile, KeyError, TypeError, UnicodeError) as exc:
        raise UpdateError('发行归档损坏或格式无效：' + str(exc)) from exc


def _unpack(data, destination, allow_development=False, expected_manifest=None):
    destination = Path(destination)
    if destination.exists():
        return verify(destination, allow_development)
    if len(data) > LIMIT:
        raise UpdateError('发行包过大')
    # Validate every member BEFORE writing any archive data.
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        infos = archive.infolist()
        names = [i.filename for i in infos]
        if len(names) != len(set(n.casefold() for n in names)) or sum(i.file_size for i in infos) > LIMIT:
            raise UpdateError('发行包重名或展开大小超限')
        for info in infos:
            safe(destination, info.filename)
            if info.flag_bits & 1:
                raise UpdateError('发行归档不能加密')
            if info.is_dir() or (info.external_attr >> 16) & 0o170000 == 0o120000:
                raise UpdateError('发行包不接受目录条目或链接')
        manifest_data = archive.read(MANIFEST)
        if expected_manifest is not None and manifest_data != expected_manifest:
            raise UpdateError('下载包与发行清单不一致')
        manifest = json.loads(manifest_data)
        validate_manifest(manifest)
        if set(names) != set(manifest['files']) | {MANIFEST}:
            raise UpdateError('发行包边界不符')
        for rel, spec in manifest['files'].items():
            if hashlib.sha256(archive.read(rel)).hexdigest() != spec.get('sha256'):
                raise UpdateError('下载包摘要错误：' + rel)
        # Temporary extraction cannot become executable target until verify succeeds.
        temp = destination.with_name(destination.name + '.partial')
        if temp.exists():
            import shutil
            shutil.rmtree(temp)
        for info in infos:
            path = safe(temp, info.filename)
            put(path, archive.read(info.filename))
            if info.filename in manifest['files']:
                os.chmod(path, manifest['files'][info.filename].get('mode', 0o644) & 0o777)
        verify(temp, allow_development)
        temp.rename(destination)
    return manifest


def get(url):
    global LAST_TRANSPORT
    if not url.startswith(('https://api.github.com/', 'https://github.com/oTATo-Boss/AI-SMA/releases/download/')):
        raise UpdateError('不接受其他发行下载来源')
    request = urllib.request.Request(url, headers={'User-Agent': 'AI-SMA-update/1', 'Accept': 'application/vnd.github+json'})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            data = response.read(LIMIT + 1)
        LAST_TRANSPORT = 'urllib'
    except urllib.error.URLError as exc:
        # Some standalone macOS Python installations lack the OS CA bundle. Keep TLS verification;
        # use the installed system curl trust store, never an unverified SSL context or curl -k.
        executable = shutil.which('curl')
        if not isinstance(exc.reason, ssl.SSLCertVerificationError) or not executable:
            raise
        result = subprocess.run([executable, '-q', '--fail', '--location', '--proto', '=https', '--proto-redir', '=https',
            '--max-time', '30', '--max-filesize', str(LIMIT), '--silent', '--show-error',
            '--write-out', '\n%{http_code}', '--user-agent', 'AI-SMA-update/1', url], capture_output=True, timeout=35)
        body, separator, code = result.stdout.rpartition(b'\n')
        status = int(code) if separator and code.isdigit() else 0
        if result.returncode:
            message = result.stderr.decode('utf-8', errors='replace')[-1000:]
            if status >= 400:
                raise urllib.error.HTTPError(url, status, message, {}, None) from exc
            raise urllib.error.URLError('系统 TLS 下载失败：' + message) from exc
        if status != 200:
            raise UpdateError('下载未返回成功状态')
        data = body
        LAST_TRANSPORT = 'curl-system-trust'
    if len(data) > LIMIT:
        raise UpdateError('下载大小超限')
    return data


def releases():
    result = []
    # Pagination avoids missing an older compatible major after a new major release.
    for page in range(1, 11):
        rows = json.loads(get(f'https://api.github.com/repos/oTATo-Boss/AI-SMA/releases?per_page=100&page={page}'))
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise UpdateError('发行列表格式错误')
        for row in rows:
            if not row.get('draft') and not row.get('prerelease'):
                try:
                    version(row['tag_name'])
                except UpdateError:
                    continue
                result.append(row)
        if len(rows) < 100:
            break
    return sorted(result, key=lambda r: version(r['tag_name']), reverse=True)


def fetch(row, cache):
    assets = {a['name']: a['browser_download_url'] for a in row['assets']}
    if not {MANIFEST, ASSET} <= assets.keys():
        raise UpdateError('稳定发行缺少更新资产')
    raw = get(assets[MANIFEST])
    manifest = json.loads(raw)
    if version(row['tag_name']) != version(manifest['version']):
        raise UpdateError('发行标签与清单版本不一致')
    identity = fingerprint(manifest)
    root = safe(cache, 'releases/' + identity)
    with lock(safe(cache, 'locks/' + identity + '.lock')):
        if not root.exists():
            unpack(get(assets[ASSET]), root, expected_manifest=raw)
        verified = verify(root)
    if fingerprint(verified) != identity:
        raise UpdateError('发行缓存身份不一致')
    return root, verified
