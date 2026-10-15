"""Decode all four previews, compare conditioning and write a synchronized video.

Pixel differences show causal change, not artistic/semantic success.
Run after main.py --preview and the three --conditioning-off variants.
"""
from __future__ import annotations
import json
from pathlib import Path
import cv2
import numpy as np
from PIL import Image, ImageDraw
from team4.DreamModel.config import REPO_ROOT
from team4.DreamModel.archive.frame_renderer import VideoWriter


def main():
    cv2.setNumThreads(1)
    output = REPO_ROOT / 'team4/output'
    folder = output / 'validation/geometric'
    names = ['normal', 'story_off', 'emotion_off', 'sound_off']
    paths = [output / 'dreammodel_geometric_preview.mp4'] + [folder / (n+'.mp4') for n in names[1:]]
    reports = [output/'dreammodel_geometric_preview_report.json'] + [folder/(n+'_run_report.json') for n in names[1:]]
    metadata = [json.loads(p.read_text(encoding='utf-8')) for p in reports]
    captures = [cv2.VideoCapture(str(p)) for p in paths]
    lengths = [int(c.get(cv2.CAP_PROP_FRAME_COUNT)) for c in captures]
    if len(set(lengths)) != 1 or lengths[0] != 600:
        raise ValueError(f'Expected four 600-frame previews, got {lengths}')
    if any(m['seed'] != metadata[0]['seed'] for m in metadata):
        raise ValueError('Ablations must have the same seed')
    audio_paths = [Path(m['audio']['path']) for m in metadata]
    # The muxed soundtrack remains identical, including in sound-off.
    import hashlib
    audio_hashes = [hashlib.sha256(p.read_bytes()).hexdigest() for p in audio_paths]
    if len(set(audio_hashes)) != 1:
        raise ValueError('Different soundtracks would confound the visual ablation')
    metrics = {n: [] for n in names[1:]}
    blurred = {n: [] for n in names[1:]}
    temporal, coverage = [], []
    previous = None
    stills = Image.new('RGB',(1280,816),(20,23,28))
    drawing = ImageDraw.Draw(stills)
    contact = Image.new('RGB',(1280,816),(20,23,28))
    contact_draw = ImageDraw.Draw(contact)
    with VideoWriter(folder/'conditioning_comparison.mp4',1280,768,30,
                     audio_path=audio_paths[0],expected_frames=600) as writer:
        for frame in range(600):
            imgs=[]
            for cap in captures:
                ok,pixels=cap.read()
                if not ok:raise ValueError(f'Unable to decode frame {frame}')
                imgs.append(cv2.cvtColor(pixels,cv2.COLOR_BGR2RGB))
            reference=imgs[0].astype('float32')
            low=cv2.GaussianBlur(cv2.resize(reference,(240,135),interpolation=cv2.INTER_AREA),(0,0),2)
            for name,other in zip(names[1:],imgs[1:]):
                metrics[name].append(float(np.mean(np.abs(reference-other))))
                reduced=cv2.resize(other,(240,135),interpolation=cv2.INTER_AREA).astype('float32')
                blurred[name].append(float(np.mean(np.abs(low-cv2.GaussianBlur(reduced,(0,0),2)))))
            temporal.append(0. if previous is None else float(np.mean(np.abs(reference-previous))))
            coverage.append(float(np.mean(reference.max(axis=2)>25)))
            previous=reference
            board=np.zeros((768,1280,3),dtype='uint8')+18
            for i,(name,img) in enumerate(zip(names,imgs)):
                x,y=(i%2)*640,(i//2)*384
                board[y+24:y+384,x:x+640]=cv2.resize(img,(640,360))
                label=name.upper().replace('_',' ') + f' | {frame/30:05.2f}s'
                cv2.putText(board,label,(x+12,y+17),cv2.FONT_HERSHEY_SIMPLEX,.44,(235,235,235),1,cv2.LINE_AA)
            writer.write(board)
            if frame%150==149:print(f'[comparison] {frame+1}/600 frames',flush=True)
            scene=frame//150
            if frame%150==96:
                for i,(name,img) in enumerate(zip(names,imgs)):
                    stills.paste(Image.fromarray(img).resize((320,180)),(i*320,scene*204+24))
                    drawing.text((i*320+8,scene*204+6),f'Scene {scene+1} / {name}',fill='white')
            if frame%150 in (15,51,96,144):
                col=(15,51,96,144).index(frame%150)
                contact.paste(Image.fromarray(imgs[0]).resize((320,180)),(col*320,scene*204+24))
                contact_draw.text((col*320+8,scene*204+6),f'Scene {scene+1} / {(frame%150)/30:.1f}s',fill='white')
    for c in captures:c.release()
    stills.save(folder/'conditioning_contact.png')
    contact.save(output/'geometric_contact.png')
    summary={'all_frames_decoded':lengths,'soundtrack_identical':True,'seed':metadata[0]['seed'],
        'events':{n:m['event_counts'] for n,m in zip(names,metadata)},
        'ablation':{n:{'mae_0_255':float(np.mean(metrics[n])), 'blurred_mae_0_255':float(np.mean(blurred[n])),
            'scene_mae':[float(np.mean(metrics[n][i*150:(i+1)*150])) for i in range(4)]} for n in names[1:]},
        'temporal':{'mean_frame_change':float(np.mean(temporal)), 'max_frame_change':float(np.max(temporal)),
            'p95_frame_change':float(np.percentile(temporal,95)),
            'boundary_frame_changes':[temporal[i] for i in (150,300,450)],
            'mean_lit_area':float(np.mean(coverage))},
        'blur_metric':'240x135 area downsample, sigma=2; approximately sigma=8 at source resolution',
        'interpretation':'Causal differences only; visual resemblance, novelty quality and artistic merit require review.'}
    (folder/'validation.json').write_text(json.dumps(summary,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(summary,indent=2))


if __name__=='__main__':main()
