#!/usr/bin/env python3
"""Validate and organize one existing post in a time-first folder. Offline; never generates, compresses, or publishes."""
# 源自 otato-social-media v2.2 的 scripts/package_post.py（该技能已于 2026-10-14 卸载）；规格对应 agents/账号/账号配置.yaml 的 cover 与 delivery。
import argparse, hashlib, json, re, shutil, struct, subprocess
from datetime import datetime, timezone, timedelta
from pathlib import Path


def file_sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def inspect_copy(path):
    text = path.read_text(encoding='utf-8-sig').strip()
    match = re.fullmatch(r'标题\s*\n(.+?)\n\s*正文\s*\n(.+?)\n\s*标签\s*\n(.+)', text, re.S)
    if not match:
        raise ValueError('TXT must have 标题, 正文, 标签 sections in that order, each nonempty')
    title, body, tags = (s.strip() for s in match.groups())
    if not all((title, body, tags)):
        raise ValueError('Title, body, and tags must all contain non-whitespace content')
    if '\n' in title or len(title) > 120:
        raise ValueError('Title must be one concise line (maximum 120 characters for this file helper, not a platform limit)')
    if not re.fullmatch(r'#[^\s#]+(?:\s+#[^\s#]+)*', tags):
        raise ValueError('Tags must be space-separated #标签 tokens')
    if any(x in text for x in ['REPLACE_WITH', '{{', '待填写', '此处填写']):
        raise ValueError('Unresolved placeholder in copy')
    return title, text + '\n'


def png_size(path):
    with path.open('rb') as f:
        h = f.read(24)
    if len(h) != 24 or h[:8] != b'\x89PNG\r\n\x1a\n' or h[12:16] != b'IHDR':
        raise ValueError('Cover must be a real PNG, not a renamed file')
    w,h = struct.unpack('>II', h[16:24])
    if w <= 0 or h <= 0 or w * 4 != h * 3:
        raise ValueError(f'Cover must be exact 3:4, got {w}x{h}')
    return w,h


def run(args):
    return subprocess.run(args, check=True, capture_output=True, text=True)


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--video', required=True, type=Path)
    ap.add_argument('--cover', required=True, type=Path)
    ap.add_argument('--copy', required=True, type=Path)
    ap.add_argument('--out', required=True, type=Path)
    ap.add_argument('--timestamp', help='Beijing time YYYYMMDD_HHMM; defaults to current UTC+08')
    a=ap.parse_args()
    for f in (a.video,a.cover,a.copy):
        if not f.is_file() or f.stat().st_size == 0: raise ValueError(f'Missing or empty input: {f}')
    for binary in ('ffprobe','ffmpeg'):
        if not shutil.which(binary): raise ValueError(f'{binary} is required for technical validation')
    title, copy=inspect_copy(a.copy)
    cover_size=png_size(a.cover)
    probe=json.loads(run(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(a.video)]).stdout)
    videos=[s for s in probe['streams'] if s.get('codec_type')=='video']
    if len(videos)!=1 or float(probe['format'].get('duration',0))<=0: raise ValueError('Expected one usable video stream and a positive duration')
    if 'mp4' not in probe['format'].get('format_name',''): raise ValueError('Video must be MP4')
    run(['ffmpeg','-v','error','-xerror','-i',str(a.video),'-f','null','-'])
    run(['ffmpeg','-v','error','-xerror','-i',str(a.cover),'-f','null','-'])
    stamp=a.timestamp or datetime.now(timezone(timedelta(hours=8))).strftime('%Y%m%d_%H%M')
    if not re.fullmatch(r'\d{8}_\d{4}', stamp): raise ValueError('Timestamp must be exactly YYYYMMDD_HHMM')
    datetime.strptime(stamp,'%Y%m%d_%H%M')
    safe=re.sub(r'[<>:"/\\|?*\x00-\x1f]', '－',title).strip(' .')
    if not safe: raise ValueError('Title produces an empty filename')
    a.out.mkdir(parents=True,exist_ok=True)
    target=a.out/f'{stamp}_{safe}'
    report=a.out/f'{target.name}.qa.json'
    if target.exists() or report.exists(): raise ValueError('Output exists; choose a new timestamp or output directory, never overwrite silently')
    # Atomic exclusive directory reservation prevents concurrent overwrite.
    target.mkdir(exist_ok=False)
    try:
        shutil.copyfile(a.video,target/'视频.mp4')
        shutil.copyfile(a.cover,target/'封面.png')
        (target/'发布文案.txt').write_text(copy,encoding='utf-8')
        source_hash=file_sha256(a.video)
        output_hash=file_sha256(target/'视频.mp4')
        if source_hash != output_hash: raise ValueError('Copied video differs from source')
        if sorted(f.name for f in target.iterdir()) != sorted(['视频.mp4','封面.png','发布文案.txt']):
            raise ValueError('Unexpected content folder entries')
        summary={'folder':target.name,'title':title,'beijing_timestamp':stamp,'cover_size':cover_size,
                 'duration_seconds':float(probe['format']['duration']),
                 'video_size':[videos[0]['width'],videos[0]['height']],
                 'audio_streams':sum(s.get('codec_type')=='audio' for s in probe['streams']),
                 'full_decode_passed':True,'source_video_sha256':source_hash,
                 'output_video_sha256':output_hash,
                 'visual_review':'NOT_PERFORMED_BY_SCRIPT','audio_listening':'NOT_PERFORMED_BY_SCRIPT'}
        with report.open('x',encoding='utf-8') as f:
            f.write(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    except Exception:
        # Only remove this invocation's newly reserved, incomplete output.
        shutil.rmtree(target)
        raise
    print(json.dumps(summary,ensure_ascii=False,indent=2))

if __name__=='__main__':
    main()
