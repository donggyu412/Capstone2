"""Independent layer/condition ablations; 10Hz state comparison, 30fps media QA separate."""
from pathlib import Path
from dataclasses import replace
import argparse,json,hashlib
import cv2,numpy as np
from PIL import Image,ImageDraw
from team4.DreamModel.config import RenderConfig
from team4.DreamModel.runtime.dream_pipeline import prepare
from team4.DreamModel.runtime.dream_world import DreamWorld
from team4.DreamModel.runtime.dream_surfaces import DreamSurfaces


def validate(audio,output):
    output.mkdir(parents=True,exist_ok=True)
    config=replace(RenderConfig(),width=320,height=180)
    b,plans,a,templates,src,layout,_,score,_=prepare(config,audio)
    modes=['reference','repeat','seed','background_evolution','pattern_competition','story','emotion','sound',
           'collective','memory','memory_bias','selection','novelty','diversity']
    records={};frames={};times=(0,20,40,60,85)
    for mode in modes:
        flags={} if mode in ('reference','repeat','seed') else {mode:False}
        seed=102 if mode=='seed' else 101
        w=DreamWorld(b.scenes,plans,templates,seed,config.audience,**flags);w.score=score
        r=DreamSurfaces(templates,320,180,score,seed);images=[];snapshots=[]
        for f in range(851):
            t=f/10;w.step(t,.1,*a.features(t))
            if t in times:images.append(r.render(w,separate=True));snapshots.append(w.snapshot())
        frames[mode]=images
        bg=w.states[0]['space']
        records[mode]={'hash':{layer:hashlib.sha256(b''.join(im[layer].tobytes() for im in images)).hexdigest()
                              for layer in ('background','objects','integrated')},
            'background':bg.report(),'state_samples':snapshots,'object_events':w.evolution.events,'inheritance':w.inheritance}
        print('[urgent ablation]',mode,flush=True)
    comparisons={}
    for mode in modes[1:]:
        comparisons[mode]={layer:{str(t):float(np.abs(ref[layer].astype(float)-test[layer]).mean())
            for t,ref,test in zip(times,frames['reference'],frames[mode])} for layer in ('background','objects','integrated')}
    assert records['reference']['hash']==records['repeat']['hash']
    for mode in modes[2:]:assert records[mode]['hash']['integrated']!=records['reference']['hash']['integrated'],mode
    for mode in ('story','emotion','sound','collective'):
        for layer in ('background','objects'):
            assert max(comparisons[mode][layer].values())>.02,(mode,layer)
    ref=records['reference']['background']
    assert len(ref['search_events'])>=8
    assert sum(ref['local_extinctions'])>0 and sum(ref['local_reseeds'])>0
    assert ref['dominance_changes']>0
    assert max(comparisons['background_evolution']['background'].values())>.05
    assert max(comparisons['pattern_competition']['background'].values())>.05
    assert records['background_evolution']['background']['search_events']==[]
    assert sum(records['pattern_competition']['background']['local_extinctions'])==0
    assert any('cross_role_inheritance' in e for e in records['reference']['object_events'])
    assert not any('cross_role_inheritance' in e for e in records['memory']['object_events'])
    output_report={'passed':True,'state_comparison_dt':.1,'source_times':times,
        'scope':'causality/stability/reproducibility; no claim of perceptual acceptance',
        'comparisons':comparisons,'runs':records}
    (output/'mechanism_validation.json').write_text(json.dumps(output_report,ensure_ascii=False,indent=2),encoding='utf-8')
    sheet=Image.new('RGB',(960,len(modes)*200));d=ImageDraw.Draw(sheet)
    for i,mode in enumerate(modes):
        for j,layer in enumerate(('background','objects','integrated')):sheet.paste(Image.fromarray(frames[mode][3][layer]),(320*j,i*200))
        d.text((5,i*200+183),mode+' | source 60s | background / objects / integrated',fill='white')
    sheet.save(output/'mechanism_comparisons.jpg',quality=95)
    print(json.dumps({'passed':True,'reference_extinctions':ref['local_extinctions'],
                     'reference_reseeds':ref['local_reseeds'],'comparisons':comparisons},indent=2),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--audio',type=Path,required=True)
    p.add_argument('--output',type=Path,default=Path(__file__).resolve().parents[1]/'output/urgent_revision/validation_v1')
    args=p.parse_args();validate(args.audio.resolve(),args.output.resolve())
