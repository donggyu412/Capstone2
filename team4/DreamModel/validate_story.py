"""Reproducible visual ablation of story/emotion/sound/memory/audience inputs."""
from dataclasses import replace
from pathlib import Path
import argparse
import json
import cv2
import numpy as np
from PIL import Image,ImageDraw
from .config import RenderConfig,REPO_ROOT
from .developmental_pipeline import prepare
from .developmental_world import DevelopmentalWorld
from .developmental_renderer import DevelopmentalRenderer
from .audio_analyzer import AudioAnalyzer
from .audience import AudienceAtmosphere


def validate(audio_path,output):
    cv2.setNumThreads(1)
    config=replace(RenderConfig(),width=320,height=180)
    bundle,plans,memories,events,_,_=prepare(config,audio_path)
    audio=AudioAnalyzer(bundle.audio_path)
    variants=[('all',{}),('story_off',{'story':False}),('emotion_off',{'emotion':False}),
        ('sound_off',{'sound':False}),('memory_off',{'memory':False}),
        ('audience_changed',{'atmosphere':AudienceAtmosphere(.9,.8,.2,'synthetic comparison')})]
    frames={};snapshots={};results=[]
    for name,flags in variants:
        world=DevelopmentalWorld(plans,memories=memories,events=events,**flags)
        renderer=DevelopmentalRenderer(320,180,memories)
        for frame in range(2551):
            t=frame/30
            world.step(t,1/30,*audio.features(t))
            if frame==0:renderer.background(world)
            if frame in (2100,2550):
                frames[(name,t)]=renderer.render(world)
                snapshots[(name,t)]=world.snapshot()
        for t in (70.,85.):
            state=snapshots[(name,t)]
            results.append({'variant':name,'seconds':t,
                'mean_pixel_difference_from_all':float(np.abs(frames[(name,t)].astype(float)-frames[('all',t)]).mean()),
                'development_time':state['development_time'],'incoming_development':state['incoming_development'],
                'page_turn':state['story_channels'].get('page_turn'),
                'memory_field_mass':state['memory_field_mass'],'genes':state['genes']})
    contact=Image.new('RGB',(960,800));draw=ImageDraw.Draw(contact)
    for i,(name,_) in enumerate(variants):
        for j,t in enumerate((70.,85.)):
            pos=((i%3)*320,((i//3)*2+j)*200)
            contact.paste(Image.fromarray(frames[(name,t)]),pos)
            draw.text((pos[0]+6,pos[1]+183),f'{name} / {t}s',fill='white')
    output.mkdir(exist_ok=True,parents=True)
    contact.save(output/'dreammodel_story_ablation.jpg',quality=93)
    (output/'dreammodel_story_ablation.json').write_text(json.dumps({
        'same_seed':101,'same_source_audio':str(bundle.audio_path),
        'sound_off':'visual modulation disabled; source WAV is unchanged',
        'audience_changed':'synthetic comparison, not measured audience data',
        'interpretation':'Differences establish causal input use, not perceptual success.',
        'results':results},ensure_ascii=False,indent=2),encoding='utf-8')
    return results


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--audio',type=Path,required=True)
    parser.add_argument('--output',type=Path,default=REPO_ROOT/'team4/output')
    args=parser.parse_args()
    values=validate(args.audio,args.output)
    print(json.dumps([{k:v for k,v in row.items() if k!='genes'} for row in values],indent=2))
