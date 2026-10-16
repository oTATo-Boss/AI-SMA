#!/usr/bin/env python3
"""Checks facts that can be measured; never invents visual/listening approval."""
import hashlib
import json
import subprocess
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw
from render_samples import ROOT,OUT,DURATIONS,FPS,RATE,frame,font,probe,sha


def main():
    results=[]
    for film,expected in DURATIONS.items():
        path=OUT/f'{film}.mp4'
        info=probe(path)
        vs=next(x for x in info['streams'] if x['codec_type']=='video')
        aus=next(x for x in info['streams'] if x['codec_type']=='audio')
        actual=float(info['format']['duration'])
        assert abs(expected-actual)<1/FPS
        assert vs['r_frame_rate']=='30/1'
        assert aus['channels']==2 and aus['sample_rate']=='48000'
        subprocess.run(['ffmpeg','-v','error','-i',str(path),'-f','null','-'],check=True,capture_output=True)
        # Decode the encoded output, rather than evaluating only source frames.
        raw=subprocess.check_output(['ffmpeg','-v','error','-i',str(path),'-vf','fps=10,scale=160:90','-pix_fmt','gray','-f','rawvideo','-'])
        samples=np.frombuffer(raw,np.uint8).reshape(-1,90,160)
        diffs=np.abs(np.diff(samples.astype(np.float32),axis=0)).mean(axis=(1,2))
        pcm=subprocess.check_output(['ffmpeg','-v','error','-i',str(path),'-vn','-f','f32le','-ar','48000','-ac','2','-'])
        sound=np.frombuffer(pcm,dtype='<f4')
        assert np.max(np.abs(sound))>.01 and np.max(np.abs(sound))<.99
        a=frame(film,1.234).tobytes();frame(film,expected-.21);b=frame(film,1.234).tobytes()
        assert a==b
        cues=OUT/f'{film}.cues.json'
        max_speech_end=None
        if cues.exists():
            data=json.loads(cues.read_text())
            assert all(0<=c['start']<c['end']<=expected for c in data)
            assert all(data[k]['end']<=data[k+1]['start'] for k in range(len(data)-1))
            max_speech_end=max(c['end'] for c in data)
        times=np.linspace(.8,expected-.8,6)
        sheet=Image.new('RGB',(960,400),'#EEE8DB')
        for k,t in enumerate(times):
            png=subprocess.check_output(['ffmpeg','-v','error','-ss',str(t),'-i',str(path),'-frames:v','1','-f','image2pipe','-vcodec','png','-'])
            import io
            image=Image.open(io.BytesIO(png));image.thumbnail((320,180))
            x=(k%3)*320;y=(k//3)*200
            sheet.paste(image,(x+(320-image.width)//2,y))
            ImageDraw.Draw(sheet).text((x+8,y+182),f'{film} {t:.2f}s',font=font(13),fill='#192520')
        sheet_path=OUT/f'{film}-encoded-contact.png';sheet.save(sheet_path)
        result={'film':film,'path':path.name,'sha256':sha(path),'duration_s':actual,'dimensions':[vs['width'],vs['height']],'fps':vs['r_frame_rate'],'audio':[aus['codec_name'],aus['sample_rate'],aus['channels']],'full_decode':'passed','audio_peak_dbfs':round(float(20*np.log10(np.max(np.abs(sound)))),2),'audio_rms_dbfs':round(float(20*np.log10(np.sqrt(np.mean(sound*sound)))) ,2),'motion_mean_absolute_difference_10fps':round(float(diffs.mean()),3),'frames_with_nonzero_motion_fraction':round(float(np.mean(diffs>.05)),3),'seek_determinism':'A-B-A exact pixel match','captions':'measured segment timing within video; no cue overlap' if cues.exists() else 'not applicable','last_speech_end_s':max_speech_end,'contact_sheet':sheet_path.name,'playback':'pending separate playback record','listening':'unverified; signal measurement is not listening','creative_approval':'pending independent review'}
        results.append(result)
    output=ROOT/'reports'/'media-verification.json'
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps({'schema_version':1,'results':results,'notes':['Local macOS test only. Native Windows/Linux production rendering not tested.','Art direction and public redistribution rights are not inferred from these checks.']},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(results,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
