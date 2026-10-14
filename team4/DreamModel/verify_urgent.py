"""Verify every decoded frame/audio stream of the three real review outputs."""
from pathlib import Path
import argparse,json,subprocess
import cv2,numpy as np
from PIL import Image,ImageDraw
from .audio_analyzer import AudioAnalyzer
from .run_report import file_digest
from .frame_renderer import find_ffmpeg,subprocess_options


def verify(folder):
    cv2.setNumThreads(1)
    report=json.loads((folder/'preview_report.json').read_text(encoding='utf-8'))
    edits={round(row['preview'][0]*30) for row in report['review_windows'][1:]}
    baseline=AudioAnalyzer(Path(report['audio']['preview_wav']));ts=np.arange(.1,84.9,.05)
    reference=np.interp(ts,baseline.times,baseline.values)
    records={};wanted=(0,300,599,749,1049,1050,1200,1350,1649,1650,1949,2099,2100,2399,2549)
    for name,file in report['files'].items():
        path=Path(file);cap=cv2.VideoCapture(str(path));fps=cap.get(cv2.CAP_PROP_FPS)
        size=[int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))]
        declared=int(cap.get(cv2.CAP_PROP_FRAME_COUNT));frames=[];changes=[];cuts=[];old=None;n=0;first_range=None
        while True:
            ok,pixels=cap.read()
            if not ok:break
            thumb=cv2.resize(pixels,(160,90),interpolation=cv2.INTER_AREA).astype('float32')
            if n==0:first_range=float(np.ptp(thumb,axis=(0,1)).max())
            if old is not None:
                value=float(np.mean(abs(thumb-old)))
                (cuts if n in edits else changes).append({'frame':n,'difference':value})
            old=thumb
            if n in wanted:frames.append((n/30,Image.fromarray(cv2.cvtColor(pixels,cv2.COLOR_BGR2RGB)).resize((480,270))))
            n+=1
        cap.release()
        assert (size,fps,declared,n)==([960,540],30.,2550,2550),(name,size,fps,declared,n)
        assert first_range==0,(name,first_range)
        audio=AudioAnalyzer(path);assert 84.96<audio.duration<85.1
        envelope=np.interp(ts,audio.times,audio.values)
        correlation=float(np.corrcoef(reference,envelope)[0,1]);assert correlation>.995,(name,correlation)
        lags={round(float(lag),3):float(np.corrcoef(reference,np.interp(ts+lag,audio.times,audio.values))[0,1])
              for lag in np.arange(-.2,.201,.05)}
        best_lag=max(lags,key=lags.get);assert abs(best_lag)<=.05,(name,best_lag)
        stream=subprocess.run([find_ffmpeg(),'-hide_banner','-i',str(path)],capture_output=True,**subprocess_options()).stderr.decode('utf-8',errors='replace')
        assert 'Video: h264' in stream and 'Audio: aac' in stream
        sheet=Image.new('RGB',(1920,294*4),(13,17,21));d=ImageDraw.Draw(sheet)
        for i,(t,image) in enumerate(frames):
            row=next(w for w in report['review_windows'] if w['preview'][0]<=t<w['preview'][1])
            source=t-row['preview'][0]+row['source'][0]
            x=i%4*480;y=i//4*294;sheet.paste(image,(x,y));d.text((x+5,y+275),f'preview {t:.2f}s / source {source:.2f}s',fill='white')
        sheet.save(folder/(name+'_decoded_contact.jpg'),quality=95)
        records[name]={'decoded_frames':n,'fps':fps,'resolution':size,'video_seconds':n/fps,
            'audio_seconds':audio.duration,'audio_envelope_correlation':correlation,'best_audio_lag_seconds':best_lag,
            'maximum_change_excluding_review_cuts':max(changes,key=lambda r:r['difference']),
            'mean_change_excluding_review_cuts':float(np.mean([c['difference'] for c in changes])),
            'review_cuts':cuts,'first_frame_spatial_range':first_range,'bytes':path.stat().st_size,'sha256':file_digest(path)}
        print('[verified]',name,json.dumps(records[name]),flush=True)
    changed_inputs=[r['path'] for r in report['input_files'] if file_digest(Path(r['path']))!=r['sha256']]
    changed_code=[r['path'] for r in report['code_files'] if file_digest(Path(r['path']))!=r['sha256']]
    assert not changed_inputs and not changed_code,(changed_inputs,changed_code)
    repo=Path(__file__).resolve().parents[2]
    protected=json.loads((repo.parent.parent/'work/formation-review/protected_before.json').read_text(encoding='utf-8'))
    changed=[p for p,h in protected.items() if not (repo/p).is_file() or file_digest(repo/p)!=h]
    assert not changed,changed
    result={'passed':True,'videos':records,'source_hashes_match':True,'listed_code_hashes_match':True,
        'protected_files_checked':len(protected),'protected_files_changed':changed,
        'total_final_render_resumed':False,'limits':'numerical/media verification; audience/visual approval remains separate'}
    (folder/'media_validation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('folder',type=Path);verify(p.parse_args().folder.resolve())
