"""Decode the delivered MP4, verify timing/audio/provenance, export actual frames."""
import argparse,hashlib,json,re,subprocess,time
from pathlib import Path
import cv2,numpy as np
from PIL import Image,ImageDraw
from team4.DreamModel.runtime.audio_analyzer import AudioAnalyzer
from team4.DreamModel.archive.frame_renderer import find_ffmpeg,subprocess_options
from team4.DreamModel.archive.run_report import file_digest


def verify(video,report_path):
    cv2.setNumThreads(1);started=time.perf_counter()
    report=json.loads(report_path.read_text(encoding='utf-8'))
    output=video.parent/'full_review';output.mkdir(exist_ok=True)
    cap=cv2.VideoCapture(str(video))
    fps=cap.get(cv2.CAP_PROP_FPS);width=int(cap.get(cv2.CAP_PROP_FRAME_WIDTH));height=int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    declared=int(cap.get(cv2.CAP_PROP_FRAME_COUNT));n=0;old=None;deltas=[];frames={};ranges={};means={}
    times=[0,10,20,35,55,68,75,84,100,115,138,145,150,160,185,208,220,225,240,255,275,289,297,299.9667]
    transitions=[72,75,79,85,147,150,155,162,222,225,230,238]
    wanted={round(t*30) for t in (*times,*transitions)}
    while True:
        ok,im=cap.read()
        if not ok:break
        thumb=cv2.resize(im,(160,90),interpolation=cv2.INTER_AREA).astype('float32')
        if old is not None:deltas.append(float(np.mean(abs(thumb-old))))
        old=thumb
        if n%30==0 or n==8999:
            ranges[n]=float(np.ptp(thumb,axis=(0,1)).max());means[n]=float(thumb.mean())
        if n in wanted:frames[n]=Image.fromarray(cv2.cvtColor(im,cv2.COLOR_BGR2RGB)).resize((480,270))
        n+=1
        if n%1500==0:print(f'[verify] decoded {n}/9000 frames',flush=True)
    cap.release()
    assert (width,height,fps,declared,n)==(1920,1080,30.,9000,9000),(width,height,fps,declared,n)
    assert ranges[0]==0,'First decoded frame contains formed shapes'
    assert ranges[8999]<5,'Final scene did not disappear'
    for t in (35,100,185,255):assert ranges[t*30]>50,f'Missing material at {t}s'
    source=Path(report['audio']['path']);src=AudioAnalyzer(source);aud=AudioAnalyzer(video)
    assert 299.96<aud.duration<300.10,aud.duration
    ts=np.arange(.2,299.8,.05)
    src_env=np.interp(ts,src.times,src.values);out_env=np.interp(ts,aud.times,aud.values)
    correlation=float(np.corrcoef(src_env,out_env)[0,1]);assert correlation>.995,correlation
    # An envelope lag search checks common timing drift/offset rather than lossy
    # AAC sample equality. Zero is expected to win at the 50ms analysis resolution.
    lags={round(float(lag),3):float(np.corrcoef(src_env,np.interp(ts+lag,aud.times,aud.values))[0,1])
          for lag in np.arange(-.20,.201,.05)}
    best_lag=min(lags,key=lambda lag:-lags[lag]);assert abs(best_lag)<=.05,best_lag
    changed_inputs=[row['path'] for row in report['input_files'] if file_digest(Path(row['path']))!=row['sha256']]
    changed_code=[row['path'] for row in report['code_files'] if file_digest(Path(row['path']))!=row['sha256']]
    assert not changed_inputs,changed_inputs
    assert not changed_code,changed_code
    repo=Path(__file__).resolve().parents[3]
    manifest=repo.parent.parent/'work/formation-review/protected_before.json'
    protected=json.loads(manifest.read_text(encoding='utf-8')) if manifest.exists() else {}
    changed_protected=[p for p,h in protected.items() if not (repo/p).is_file() or file_digest(repo/p)!=h]
    assert not changed_protected,changed_protected
    def contact(name,timestamps):
        sheet=Image.new('RGB',(1920,294*((len(timestamps)+3)//4)),(13,17,21));d=ImageDraw.Draw(sheet)
        for i,t in enumerate(timestamps):
            x=i%4*480;y=i//4*294;sheet.paste(frames[round(t*30)],(x,y));d.text((x+8,y+275),f'{t:.2f}s',fill='white')
        sheet.save(output/name,quality=95)
    contact('final_decoded_contact.jpg',times);contact('final_transitions.jpg',transitions)
    probe=subprocess.run([find_ffmpeg(),'-hide_banner','-i',str(video)],capture_output=True,**subprocess_options())
    streams=probe.stderr.decode('utf-8',errors='replace')
    assert 'Audio: aac' in streams and 'Video: h264' in streams,streams
    result={'passed':True,'file':str(video),'size_bytes':video.stat().st_size,'resolution':[width,height],
        'fps':fps,'decoded_frames':n,'duration_seconds':n/fps,'audio_duration_seconds':aud.duration,
        'audio_codec':'aac','video_codec':'h264','audio_source':str(source),
        'audio_envelope_correlation':correlation,'best_audio_lag_seconds':best_lag,
        'frame_change':{'mean':float(np.mean(deltas)),'max':max(deltas),
            'at_nominal_boundaries':{str(t):deltas[t*30-1] for t in (75,150,225)}},
        'first_frame_spatial_range':ranges[0],'last_frame_spatial_range':ranges[8999],
        'source_hashes_match':not changed_inputs,'code_hashes_match':not changed_code,
        'protected_files_checked':len(protected),'protected_files_changed':changed_protected,
        'video_sha256':file_digest(video),'elapsed_seconds':time.perf_counter()-started,
        'visual_review':'contact sheets are actual decoded output frames; numerical checks are not audience acceptance'}
    (output/'final_validation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2),flush=True)
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('video',type=Path);p.add_argument('report',type=Path)
    args=p.parse_args();verify(args.video,args.report)
