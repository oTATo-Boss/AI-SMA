#!/usr/bin/env python3
"""Render a controlled continuity defect, repair one unit, preserve other units."""
import json
import subprocess
from pathlib import Path
from render_samples import OUT, FPS, frame, sha, run, probe


def unit(index,version,wrong=False):
    path=OUT/'units'/f'drama2-shot{index+1:02d}-v{version:02d}.mp4'
    path.parent.mkdir(parents=True,exist_ok=True)
    command=['ffmpeg','-v','error','-y','-f','rawvideo','-pixel_format','rgb24','-video_size','1280x720','-framerate',str(FPS),'-i','-','-ss',str(index*5),'-t','5','-i',str(OUT/'drama2.wav'),'-map','0:v:0','-map','1:a:0','-c:v','libx264','-preset','fast','-crf','19','-g','30','-threads','4','-pix_fmt','yuv420p','-c:a','aac','-b:a','192k','-t','5',str(path)]
    proc=subprocess.Popen(command,stdin=subprocess.PIPE)
    for k in range(5*FPS):proc.stdin.write(frame('drama2',index*5+k/FPS,wrong=wrong).tobytes())
    proc.stdin.close()
    if proc.wait():raise RuntimeError('unit render failed')
    run(['ffmpeg','-v','error','-i',str(path),'-f','null','-'],stdout=subprocess.DEVNULL)
    return {'unit':f'E02/S{index+1:02d}','version':version,'path':str(path.relative_to(OUT)),'sha256':sha(path),'duration':float(probe(path)['format']['duration']),'defect':'seeded wrong red prop' if wrong else None}


def main():
    before=sha(OUT/'drama1.mp4')
    rejected=unit(0,1,True)
    unchanged=[unit(i,1) for i in range(1,6)]
    hashes_before={x['path']:sha(OUT/x['path']) for x in unchanged}
    repaired=unit(0,2)
    paths=[repaired]+unchanged
    concat=OUT/'units'/'concat-v02.txt'
    concat.write_text(''.join(f"file '{Path(item['path']).name}'\n" for item in paths),encoding='utf-8')
    output=OUT/'drama2-repaired-v02.mp4'
    # Use the original uninterrupted master audio to avoid AAC segment padding seams.
    run(['ffmpeg','-v','error','-y','-f','concat','-safe','0','-i',str(concat),'-i',str(OUT/'drama2.wav'),'-map','0:v:0','-map','1:a:0','-c:v','copy','-c:a','aac','-b:a','192k','-t','30','-movflags','+faststart',str(output)])
    run(['ffmpeg','-v','error','-i',str(output),'-f','null','-'],stdout=subprocess.DEVNULL)
    hashes_after={x['path']:sha(OUT/x['path']) for x in unchanged}
    assert hashes_before==hashes_after
    assert before==sha(OUT/'drama1.mp4')
    report={'test_type':'controlled continuity defect and actual single-shot rerender','canonical_prop':'beige ticket; upper-left missing corner; lower-right red thread; 南站 21:10','rejected':rejected,'repaired':repaired,'unchanged_units':unchanged,'untouched_hashes_identical':hashes_before==hashes_after,'episode1_sha256_before':before,'episode1_sha256_after':sha(OUT/'drama1.mp4'),'assembly':{'path':output.name,'sha256':sha(output),'duration':float(probe(output)['format']['duration'])},'review_mode':'self','listening':'unverified','scope':'Tests media repair isolation only; task state invalidation is verified by the separate project tools tests.'}
    (OUT/'repair-media-receipt.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
