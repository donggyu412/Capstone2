"""Causal comparisons at identical source times/seeds, with recorded frame deltas."""
import argparse,json,hashlib
from pathlib import Path
from dataclasses import replace
import cv2,numpy as np
from PIL import Image,ImageDraw
from team4.DreamModel.config import RenderConfig
from team4.DreamModel.runtime.dream_pipeline import prepare
from team4.DreamModel.runtime.dream_world import DreamWorld
from team4.DreamModel.runtime.dream_surfaces import DreamSurfaces


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--audio',type=Path,required=True)
    args=parser.parse_args();out=Path(__file__).resolve().parents[1]/'output/full_review';out.mkdir(parents=True,exist_ok=True)
    c=replace(RenderConfig(),width=320,height=180)
    b,p,a,templates,src,layout,_,score,_=prepare(c,args.audio)
    captures={};metrics={};raw={}
    modes=['reference','repeat','seed','story','emotion','sound','collective','memory','memory_bias','selection','novelty','diversity']
    for mode in modes:
        flags={} if mode in ('reference','repeat','seed') else {mode:False}
        seed=102 if mode=='seed' else c.seed
        w=DreamWorld(b.scenes,p,templates,seed,c.audience,**flags);w.score=score
        r=DreamSurfaces(templates,320,180,score,seed);images=[];snap=[]
        for f in range(2401):
            w.step(f/30,1/30,*a.features(f/30))
            if f in (0,300,750,1650,2400):
                image=r.render(w);images.append(image.copy());snap.append(w.snapshot())
        captures[mode]=images;raw[mode]=hashlib.sha256(b''.join(im.tobytes() for im in images)).hexdigest()
        metrics[mode]={'sha256':raw[mode],'snapshots':snap,'genomes':[e['id'] for e in w.evolution.events],
            'cells':{k:len(v) for k,v in w.evolution.archive.items()},'inheritance':w.inheritance}
        print('[ablation]',mode,flush=True)
    comparisons={}
    for mode in modes[1:]:
        comparisons[mode]={'mean_absolute_rgb_by_time':{str(t):float(np.mean(np.abs(x.astype(float)-y)))
            for t,x,y in zip((0,10,25,55,80),captures['reference'],captures[mode])},
            'identical':raw['reference']==raw[mode]}
    assert comparisons['repeat']['identical'],'Same seed did not reproduce frames'
    assert np.ptp(captures['reference'][0],axis=(0,1)).max()==0,'Nonempty initial surface'
    for mode in modes[2:]:
        assert not comparisons[mode]['identical'],f'{mode} had no causal effect'
    sheet=Image.new('RGB',(960,202*len(modes)))
    d=ImageDraw.Draw(sheet)
    for i,mode in enumerate(modes):
        for j,k in enumerate((2,3,4)):sheet.paste(Image.fromarray(captures[mode][k]),(j*320,i*202))
        d.text((5,i*202+183),mode+' | 25s / 55s / 80s',fill='white')
    sheet.save(out/'causal_comparisons.jpg',quality=94)
    (out/'causal_validation.json').write_text(json.dumps({'passed':True,'comparisons':comparisons,'runs':metrics,
        'interpretation':'pixel/state causality only, not a claim of perceptual significance or audience validation'},ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(comparisons,indent=2),flush=True)


if __name__=='__main__':main()
